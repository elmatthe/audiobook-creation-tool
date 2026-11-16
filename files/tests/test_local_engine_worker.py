"""v0.8.x P2 -- the macOS local-engine worker: protocol, validation, Cancel, recovery, release, parity (plan 11.2.1).

These run the REAL worker program (``tts/local_engine_worker.py``: its protocol channel, requests, events and errors)
started by the REAL host through a containment owner (class A: its own group, ``child_entry.py`` and the lifeline),
with a stand-in engine in place of the model (``local_engine_stub.py``), so they need no model and run anywhere the
POSIX containment does. The real model's own proofs (CX-1 with a 3,000-character chunk in flight, KX-1(a), KX-2(a),
KX-3(a), the phoneme and seeded-PCM parity) are ``test_macos_p2_kokoro_real.py``.

* CX-2: a worker that ignores SIGTERM while blocked inside a native call is ended by SIGKILL within the route's bound.
* No new work after the latch: a request is never sent once Cancel is latched.
* CX-7 (route): after a Cancel the next request starts a new worker, which loads again and says so.
* Failures: an exit mid-chunk, a hang, a broken message, and audio that is not what was reported (float64, not finite,
  another rate, short) each end the worker and fail with an accurate message; nothing waits beyond its bound.
* Release: an engine switch closes an idle worker (off the caller's thread) and never one serving a run.
* Windows: no worker is ever started; Kokoro stays in-process exactly as released.
* Parity: the parent's flow is the same on both routes -- the same prepared chunks (``v1`` and ``off``), in the same
  order, the same pauses, the same assembled PCM.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from shared import child_ownership
from shared.cancellation import ConversionCancelled
from tts import local_engine_host as hosts

NATIVE_P2 = "native macOS only (P2): the local-engine worker, POSIX containment and real Kokoro"
POSIX = pytest.mark.skipif(not child_ownership.supported(), reason=NATIVE_P2)

HERE = Path(__file__).resolve().parent
STUB = HERE / "local_engine_stub.py"
CANCEL_BOUND_S = 2.0  # plan 11.2.1: the local-engine worker's T_stop


@pytest.fixture
def stub(monkeypatch, tmp_path):
    """A factory of hosts whose worker is the real worker program serving the stand-in engine."""
    made: list[hosts.WorkerHost] = []
    record = tmp_path / "requests.jsonl"

    def make(mode: str = "ok", *, seconds: float = 0.0, owner=None, **kwargs) -> hosts.WorkerHost:
        monkeypatch.setenv("ACT_STUB_BEHAVIOUR", json.dumps({"mode": mode, "seconds": seconds, "record": str(record)}))
        host = hosts.WorkerHost("kokoro", sample_rate=24000, argv=[sys.executable, "-I", "-B", str(STUB), "kokoro"],
                                owner=owner or child_ownership.Owner(), log=lambda _s: None, **kwargs)
        made.append(host)
        return host

    make.record = record  # type: ignore[attr-defined]
    make.requests = lambda: ([json.loads(x) for x in record.read_text().splitlines()]  # type: ignore[attr-defined]
                             if record.exists() else [])
    yield make
    for host in made:
        host.close("test over")


def _request(text: str = "Hello there.") -> dict:
    return {"text": text, "voice": "af_heart", "speed": 1.0, "split_pattern": r"\n+", "seed": None}


def _gone(pid: int, start) -> bool:
    return child_ownership.process_start_time(pid) != start


def _latch_after(seconds: float):
    """A Cancel latch that closes ``seconds`` from now (a Timer, as the panel's button sets the controller's latch)."""
    state = {"set": False, "at": None}

    def close() -> None:
        state["at"] = time.monotonic()
        state["set"] = True

    threading.Timer(seconds, close).start()
    return state, (lambda: state["set"])


# --------------------------------------------------------------------------- the route is macOS-only (D17)
def test_isolation_is_macos_only():
    assert hosts.isolation_enabled("darwin") is True
    for platform in ("win32", "linux", "cygwin"):
        assert hosts.isolation_enabled(platform) is False, platform


def test_on_windows_kokoro_never_starts_a_worker_and_keeps_its_in_process_route(monkeypatch, tmp_path):
    """The released Windows route, byte for byte: the pipeline call in this process, no host, no worker."""
    import tts.kokoro_synth as ks

    monkeypatch.setattr(hosts.sys, "platform", "win32")
    assert ks._use_worker() is False
    monkeypatch.setattr(hosts, "host_for", lambda *a, **k: pytest.fail("a worker host was asked for on Windows"))
    calls: list[tuple] = []

    class Pipeline:
        def __call__(self, text, voice=None, speed=1.0, split_pattern=None):
            calls.append((text, voice, speed, split_pattern))
            yield ("g", "p", np.full(2400, 0.1, dtype=np.float32))

    monkeypatch.setattr(ks, "_get_pipeline", lambda lang_code: Pipeline())
    written: dict = {}
    monkeypatch.setattr(ks, "_export_mp3", lambda arr, rate, out, bitrate=None, log=None: written.update(pcm=arr))
    source = tmp_path / "w.txt"
    source.write_text("One sentence here. Another one there.", encoding="utf-8")
    ks.kokoro_file_to_mp3(str(source), str(tmp_path / "w.mp3"), voice_id="af_heart", log=lambda s: None)
    assert calls == [("One sentence here. Another one there.", "af_heart", 1.0, r"\n+")]
    assert written["pcm"].size == 2400


# --------------------------------------------------------------------------- protocol
@POSIX
def test_a_worker_is_a_contained_class_a_child_that_loads_once_and_returns_validated_pcm(stub):
    owner = child_ownership.Owner()
    host = stub(owner=owner)
    first = host.load({"lang_code": "a"})
    assert first["reused"] is False and first["worker_start"] == 1
    child = owner.child(host._proc)
    assert child is not None and child.kind == child_ownership.CLASS_A, "registered with its owner as class A"
    assert os.getpgid(host.pid) == host.pid, "it leads its own process group"
    assert host.hello["pgid"] == host.pid and host.hello["engine"] == "kokoro"
    # Every record of the worker's identity names the real process (a record without it once sent a containment test
    # after process 0, which ``killpg`` reads as the caller's own group).
    identities = [e.detail for e in host.history if e.name in ("hello", "ready")]
    assert identities and all(d.get("pid") == host.pid for d in identities), identities
    assert [e.detail.get("pgid") for e in host.history if e.name == "ready"] == [host.pid]
    assert host.load({"lang_code": "a"})["reused"] is True, "a warm worker answers a repeated load at once"
    result = host.synthesize(_request("Hello there."))
    assert result.pcm.dtype == np.float32 and result.pcm.size == 240 * len("Hello there.")
    assert result.phonemes == [".ereht olleH"]
    assert not list(Path(host._scratch).glob("*")), "the chunk's file is removed once read"
    assert [r["op"] for r in stub.requests()] == ["load", "synth"]


@POSIX
def test_library_output_never_reaches_the_protocol(stub):
    host = stub("noise")
    host.load({"lang_code": "a"})
    assert host.synthesize(_request()).pcm.size > 0
    assert any("chatter" in line for line in host._stderr), "library output is kept with stderr, not parsed"


@POSIX
@pytest.mark.parametrize("mode, words", [("float64", "float64"), ("nan", "not finite"), ("wrong-rate", "22050 Hz"),
                                          ("short-file", "samples, not the")])
def test_audio_that_is_not_what_was_reported_fails_the_chunk_and_ends_the_worker(stub, mode, words):
    host = stub(mode)
    host.load({"lang_code": "a"})
    pid = host.pid
    start = child_ownership.process_start_time(pid)
    with pytest.raises(hosts.LocalEngineFailed, match=words):
        host.synthesize(_request())
    assert not host.alive() and _gone(pid, start)


@POSIX
def test_a_worker_that_dies_mid_chunk_fails_the_file_with_its_last_words(stub):
    host = stub("crash")
    host.load({"lang_code": "a"})
    began = time.monotonic()
    with pytest.raises(hosts.LocalEngineFailed) as raised:
        host.synthesize(_request())
    assert time.monotonic() - began < 5.0
    text = str(raised.value)
    assert "Kokoro voice engine stopped unexpectedly" in text and "exit code 3" in text
    assert "last words before it fell over" in text


@POSIX
def test_a_worker_that_stops_answering_is_stopped_at_its_bound(stub):
    host = stub("hang", chunk_timeout_s=1.0)
    host.load({"lang_code": "a"})
    pid, start = host.pid, child_ownership.process_start_time(host.pid)
    began = time.monotonic()
    with pytest.raises(hosts.LocalEngineFailed, match="stopped answering"):
        host.synthesize(_request())
    assert time.monotonic() - began < 1.0 + CANCEL_BOUND_S
    assert _gone(pid, start)


@POSIX
def test_a_missing_model_is_refused_as_assets_unavailable_not_a_pipeline_failure(stub, monkeypatch, tmp_path):
    import tts.kokoro_synth as ks
    from tts import model_assets

    host = stub("assets")
    monkeypatch.setattr(hosts, "_HOST", host)
    with pytest.raises(model_assets.AssetsUnavailable, match="Nothing was downloaded"):
        ks._worker_host("a", log=lambda s: None)


# --------------------------------------------------------------------------- Cancel (C1-C3 on the worker route)
@POSIX
def test_cx2_a_worker_ignoring_sigterm_inside_a_native_call_is_killed_within_the_bound(stub):
    host = stub("ignore-term")
    host.load({"lang_code": "a"})
    pid, start = host.pid, child_ownership.process_start_time(host.pid)
    latch, cancelled = _latch_after(0.4)
    with pytest.raises(ConversionCancelled):
        host.synthesize(_request(), cancel_check=cancelled)
    stopped = time.monotonic()
    names = [e.name for e in host.history]
    assert names.index("started") < names.index("cancel-seen") < names.index("killed")
    assert stopped - latch["at"] <= CANCEL_BOUND_S, f"stopped {stopped - latch['at']:.3f} s after the latch"
    assert _gone(pid, start), "the worker is gone (and reaped: it is no longer even a zombie of ours)"
    assert host._proc is None and host.history[-2].detail["returncode"] == -signal.SIGKILL


@POSIX
def test_cx1_route_cancel_mid_chunk_does_not_wait_for_the_chunk(stub):
    """A chunk whose "inference" takes 30 s inside a native call: Cancel ends it in well under the bound."""
    host = stub("ok", seconds=30.0)
    host.load({"lang_code": "a"})
    latch, cancelled = _latch_after(0.5)
    began = time.monotonic()
    with pytest.raises(ConversionCancelled):
        host.synthesize(_request("x" * 3000), cancel_check=cancelled)
    assert time.monotonic() - latch["at"] <= CANCEL_BOUND_S
    assert time.monotonic() - began < 5.0, "never after the chunk"


@POSIX
def test_nothing_is_asked_of_the_worker_once_cancel_is_latched(stub):
    host = stub()
    host.load({"lang_code": "a"})
    with pytest.raises(ConversionCancelled):
        host.synthesize(_request("Never to be spoken."), cancel_check=lambda: True)
    assert [r["op"] for r in stub.requests()] == ["load"], "no chunk request after the latch"


@POSIX
def test_cx7_route_after_a_cancel_the_next_request_cold_starts_a_new_worker(stub):
    host = stub("ok", seconds=10.0)
    host.load({"lang_code": "a"})
    first = host.pid
    latch, cancelled = _latch_after(0.3)
    with pytest.raises(ConversionCancelled):
        host.synthesize(_request(), cancel_check=cancelled)
    os.environ["ACT_STUB_BEHAVIOUR"] = json.dumps({"mode": "ok", "record": str(stub.record)})
    again = host.load({"lang_code": "a"})
    assert again["reused"] is False and again["worker_start"] == 2, "the model is loaded again, in a new worker"
    assert host.pid != first
    assert host.synthesize(_request()).pcm.size > 0


@POSIX
def test_cancel_while_the_worker_is_starting_is_seen_within_the_poll(stub, monkeypatch):
    """Cancel during the worker's own start (before it has said hello) stops it at once too."""
    host = stub("ok")
    began = time.monotonic()
    with pytest.raises(ConversionCancelled):
        host.load({"lang_code": "a"}, cancel_check=lambda: time.monotonic() - began > 0.0)
    assert time.monotonic() - began <= CANCEL_BOUND_S and not host.alive()


# --------------------------------------------------------------------------- lifecycle and release
@POSIX
def test_an_engine_switch_closes_an_idle_worker_and_never_one_serving_a_run(stub, monkeypatch):
    host = stub()
    host.load({"lang_code": "a"})
    pid, start = host.pid, child_ownership.process_start_time(host.pid)
    monkeypatch.setattr(hosts, "_HOST", host)
    hosts.engine_selected("kokoro")
    assert host.alive(), "the same engine keeps its warm worker"
    with host._request():  # a run is using it
        hosts.engine_selected("edge")
        assert host.release_when_idle and host.alive(), "never released under a running file"
    host.release_when_idle = False
    hosts.engine_selected("edge")
    deadline = time.monotonic() + 3.0
    while not _gone(pid, start) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert _gone(pid, start) and hosts.current_host() is None


@POSIX
def test_host_for_another_engine_closes_the_previous_worker(stub, monkeypatch):
    host = stub()
    host.load({"lang_code": "a"})
    pid, start = host.pid, child_ownership.process_start_time(host.pid)
    monkeypatch.setattr(hosts, "_HOST", host)
    other = hosts.host_for("chatterbox", sample_rate=24000, log=lambda s: None)
    assert other is not host and _gone(pid, start)
    monkeypatch.setattr(hosts, "_HOST", None)


@POSIX
def test_a_closing_owner_refuses_a_new_worker_with_an_accurate_failure(stub):
    owner = child_ownership.Owner()
    owner.begin_closing()
    host = stub(owner=owner)
    with pytest.raises(hosts.LocalEngineFailed, match="could not be started under the app's control"):
        host.load({"lang_code": "a"})


# --------------------------------------------------------------------------- parity of the parent's flow
SOURCE = ("Title: Parity\n\nChapter 1\n\nDr. Smith paid $3.50 on 12/03/2024 at 5 p.m. for 2 items.\n\n"
          + " ".join(f"Sentence number {n} keeps going for a while so the chunker has work to do." for n in range(90)))


def _run_route(monkeypatch, tmp_path, *, worker: bool, speech_prep, stub_factory=None) -> dict:
    import tts.kokoro_synth as ks

    texts: list[str] = []
    logged: list[str] = []
    if worker:
        host = stub_factory()
        monkeypatch.setattr(hosts, "_HOST", host)
        monkeypatch.setattr(ks, "_use_worker", lambda: True)
    else:
        class Pipeline:
            def __call__(self, text, voice=None, speed=1.0, split_pattern=None):
                texts.append(text)
                length = 240 * max(1, len(text))
                yield ("g", text[::-1], (0.25 * np.sin(2 * np.pi * 220 * np.arange(length) / 24000)).astype(np.float32))

        monkeypatch.setattr(ks, "_use_worker", lambda: False)
        monkeypatch.setattr(ks, "_get_pipeline", lambda lang_code: Pipeline())
    written: dict = {}
    monkeypatch.setattr(ks, "_export_mp3", lambda arr, rate, out, bitrate=None, log=None: written.update(pcm=arr))
    source = tmp_path / f"parity-{worker}-{getattr(speech_prep, 'setting', speech_prep)}.txt"
    source.write_text(SOURCE, encoding="utf-8")
    ks.kokoro_file_to_mp3(str(source), str(tmp_path / "out.mp3"), voice_id="bm_george", speed=1.1, chunk_pause_ms=50,
                          log=logged.append, speech_prep=speech_prep)
    if worker:
        texts = [r["text"] for r in stub_factory.requests() if r["op"] == "synth"]
        voices = {(r["voice"], r["speed"], r["split_pattern"], r["seed"]) for r in stub_factory.requests()
                  if r["op"] == "synth"}
        assert voices == {("bm_george", 1.1, r"\n+", None)}
        loads = [r for r in stub_factory.requests() if r["op"] == "load"]
        assert loads == [{"pid": loads[0]["pid"], "op": "load", "id": loads[0]["id"], "lang_code": "b"}]
    monkeypatch.setattr(hosts, "_HOST", None)
    return {"texts": texts, "pcm": written["pcm"], "log": [line for line in logged if "worker" not in line]}


@POSIX
@pytest.mark.parametrize("speech_prep", ["v1", "off"])
def test_the_parent_flow_is_identical_on_both_routes(monkeypatch, tmp_path, stub, speech_prep):
    """Speech preparation once in the parent, the same chunks in the same order with the same settings, the same
    pauses, the same assembled PCM: only where the model call runs differs."""
    from tts.speech.pipeline import build_snapshot

    prep = build_snapshot(speech_prep, user_dir=None)
    assert prep.enabled is (speech_prep == "v1")
    in_process = _run_route(monkeypatch, tmp_path, worker=False, speech_prep=prep)
    via_worker = _run_route(monkeypatch, tmp_path, worker=True, speech_prep=prep, stub_factory=stub)
    assert len(in_process["texts"]) >= 2, "a multi-chunk text"
    assert via_worker["texts"] == in_process["texts"]
    assert np.array_equal(via_worker["pcm"], in_process["pcm"])
    assert via_worker["log"] == in_process["log"]


@POSIX
def test_speech_preparation_v1_and_off_reach_the_worker_as_the_parent_prepared_them(monkeypatch, tmp_path, stub):
    """The worker is handed exactly ``split_into_chunks(prepare(...))`` of the parent, for ``v1`` and for ``off``; the
    worker never prepares text itself (one pipeline, in the parent: plan 13 item 5)."""
    import tts.kokoro_synth as ks
    from tts.speech.document import read_source_text
    from tts.speech.pipeline import build_snapshot, prepare
    from tts.speech.profiles import KOKORO

    sent: dict = {}
    for mode in ("v1", "off"):
        stub.record.unlink(missing_ok=True)
        snapshot = build_snapshot(mode, user_dir=None)
        got = _run_route(monkeypatch, tmp_path, worker=True, speech_prep=snapshot, stub_factory=stub)
        source = tmp_path / f"parity-True-{snapshot.setting}.txt"
        expected = ks.split_into_chunks(prepare(read_source_text(source), snapshot, KOKORO).text)
        assert got["texts"] == expected, mode
        sent[mode] = " ".join(got["texts"])
    assert sent["v1"] != sent["off"], "v1 really prepared the text the worker was given"
    assert "Dr. Smith paid $3.50" in sent["off"], "off leaves the source's words as they are"


@POSIX
def test_cancel_of_a_run_ends_its_idle_worker_and_leaves_a_busy_one_to_its_own_poll(stub, monkeypatch):
    """Cancel while paused (the worker loaded and idle) ends it, so the next run cold-loads; Cancel of another engine's
    run leaves it; a worker answering a request is never touched by this hook (its request ends it within the poll)."""
    host = stub()
    host.load({"lang_code": "a"})
    pid, start = host.pid, child_ownership.process_start_time(host.pid)
    monkeypatch.setattr(hosts, "_HOST", host)
    hosts.cancel_requested("edge")
    time.sleep(0.3)
    assert host.alive(), "another engine's Cancel leaves it"
    held = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with host._request():
            held.set()
            release.wait(5)

    holder = threading.Thread(target=hold)
    holder.start()
    held.wait(5)
    hosts.cancel_requested("kokoro")
    time.sleep(0.3)
    assert host.alive(), "never killed under a request from this hook"
    release.set()
    holder.join(5)
    began = time.monotonic()
    hosts.cancel_requested("kokoro")
    while not _gone(pid, start) and time.monotonic() - began < CANCEL_BOUND_S:
        time.sleep(0.01)
    assert _gone(pid, start), "the idle worker ends within the bound"
    assert host.load({"lang_code": "a"})["worker_start"] == 2, "the next run cold-starts a new worker"
