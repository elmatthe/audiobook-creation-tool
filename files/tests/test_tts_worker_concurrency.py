"""v0.6.5 Phase 6 — P14 file-worker concurrency.

``Workers = X`` is a requested *whole-file* concurrency level, never
permission to parallelize the chunks inside one source file. This file
covers the pieces Phase 6 added on top of the existing job-control/output
foundation (``test_tts_jobs.py``, ``test_tts_importing.py``):

* ``resolve_effective_workers`` -- the pure bound (requested, queued files,
  backend-safety ceiling, device-safe ceiling) -- exercised at representative
  1/2/4/oversized requests, with no GUI needed.
* Direct and folder items now share ONE pool and ONE resolved worker count
  (previously: direct items ran strictly one-at-a-time ahead of a separately
  pooled folder half).
* Edge folder/batch items and Kokoro actually overlap when more than one
  worker is available; Chatterbox never does, regardless of how many workers
  are requested.
* **Edge *direct* items are a special case, discovered while implementing
  this drop.** ``epub2tts_edge.runner.run_conversion_job`` isolates one
  conversion's scratch files by ``os.chdir``'ing into a private temp
  directory for the whole call -- safe when direct items ran strictly one at
  a time (every prior phase), unsafe the moment two could run concurrently,
  since ``os.chdir`` is process-wide state, not thread-local. This drop adds
  ``runner._CWD_ISOLATION_LOCK`` to serialize only that critical section, so
  two direct Edge conversions never truly overlap even when the pool
  dispatches both -- correctness over a rewrite of the vendored engine's
  path handling, which P14 calls a disproportionate change for this bounded
  subtask. Section E below proves the lock directly, and section C proves it
  does not block unrelated concurrent work (a folder Edge file, or Kokoro).
* Pause/Cancel/Retry Failed and "no partial/corrupt publication" all remain
  correct once more than one file can be in flight at once.

Safety and determinism follow the existing convention in ``test_tts_jobs.py``:
no test sleeps arbitrarily, every engine entry point is stubbed, and every
fixture lives under ``tmp_path``. Tests that must prove an *absence* of
concurrency (Chatterbox) bound their wait with a short, explicit settle
window rather than waiting forever for a negative.
"""

from __future__ import annotations

import sys
import threading
import time
import types
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from tts import epub2tts_gui as panel_module  # noqa: E402

from test_tts_importing import (  # noqa: E402,F401
    WAIT,
    make_panel,
    output_base,
    sources,
    stubs,
    tk_root,
)
from test_tts_jobs import (  # noqa: E402,F401
    GatedStubs,
    direct_panel,
    folder_panel,
    gated_stubs,
    mixed_panel,
    run_attempt,
    wait_for,
)

#: How long to let a (correctly) non-concurrent engine "settle" before
#: concluding a second file never started. Short and explicit -- proving an
#: absence cannot wait for a signal that will never come, so this is bounded
#: instead, the same way the rest of the suite bounds every wait.
SETTLE = 0.3


# --------------------------------------------------------------------------- #
# A. resolve_effective_workers -- pure function, no GUI needed
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _fixed_cpu_count(monkeypatch):
    """A known, portable core count for every test in this module.

    ``resolve_effective_workers`` reads the real machine's CPU count through
    ``panel_module._cpu_count`` (a thin, patchable seam); pinning it here
    keeps every expectation below exact and machine-independent.
    """
    monkeypatch.setattr(panel_module, "_cpu_count", lambda: 8)


@pytest.mark.parametrize("requested,queued,expected", [
    (1, 5, 1),
    (2, 5, 2),
    (4, 5, 4),
])
def test_edge_honors_a_representative_requested_count(requested, queued, expected):
    assert panel_module.resolve_effective_workers(requested, queued, "edge") == expected


@pytest.mark.parametrize("requested,queued,expected", [
    (1, 5, 1),
    (2, 5, 2),
    (4, 5, 4),
])
def test_kokoro_honors_a_representative_requested_count_within_its_headroom(
    requested, queued, expected
):
    # cpu_count=8 -> Kokoro's device-safe ceiling is 4 (half the cores).
    assert panel_module.resolve_effective_workers(requested, queued, "kokoro") == expected


@pytest.mark.parametrize("requested", [1, 2, 4, 999])
def test_chatterbox_always_resolves_to_one_regardless_of_the_request(requested):
    assert panel_module.resolve_effective_workers(requested, 10, "chatterbox") == 1


def test_effective_workers_never_exceeds_the_queued_file_count():
    assert panel_module.resolve_effective_workers(4, 2, "edge") == 2
    assert panel_module.resolve_effective_workers(4, 1, "kokoro") == 1


def test_an_oversized_edge_request_degrades_to_the_backend_safe_ceiling(monkeypatch):
    monkeypatch.setattr(panel_module, "_cpu_count", lambda: 64)
    assert (panel_module.resolve_effective_workers(100, 100, "edge")
            == panel_module.EDGE_BACKEND_SAFE_WORKERS == 32)


def test_an_oversized_request_degrades_to_the_devices_own_cpu_count():
    # cpu_count=8 (fixture default) binds before the backend-safe ceilings do.
    assert panel_module.resolve_effective_workers(100, 100, "edge") == 8
    assert panel_module.resolve_effective_workers(100, 100, "kokoro") == 4


def test_a_machine_that_cannot_report_cpu_count_still_resolves_safely(monkeypatch):
    monkeypatch.setattr(panel_module, "_cpu_count", lambda: None)
    assert panel_module.resolve_effective_workers(100, 100, "edge") >= 1
    assert panel_module.resolve_effective_workers(100, 100, "kokoro") >= 1


def test_resolve_effective_workers_never_returns_less_than_one():
    assert panel_module.resolve_effective_workers(0, 0, "edge") == 1
    assert panel_module.resolve_effective_workers(-5, 5, "kokoro") == 1


# --------------------------------------------------------------------------- #
# B. Direct and folder items now share one pool and one resolved count
# --------------------------------------------------------------------------- #


def test_a_mixed_queue_still_converts_every_item_through_its_own_engine(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    """Merging direct+folder dispatch must not change *which* engine call a
    file takes -- only that they now share one pool."""
    panel, _direct, _folders = mixed_panel(make_panel, tmp_path)
    panel.workers_var.set("2")
    params = run_attempt(panel)

    assert len(stubs.conversion_jobs) == 2, "the two directly added files"
    assert len(stubs.batch_items) == 2, "the two folder-derived files"
    for item in params["items"]:
        assert item["destination"].exists()


def test_the_run_log_states_requested_and_effective_workers_truthfully(
    make_panel, output_base, tmp_path, stubs
):
    panel, _chosen = direct_panel(make_panel, tmp_path, "a.txt", "b.txt", "c.txt")
    panel.workers_var.set("2")
    run_attempt(panel)
    log_text = "\n".join(panel.log.details)
    assert "Requested workers: 2 | Effective workers: 2" in log_text


def test_an_oversized_workers_request_degrades_safely_and_is_logged_truthfully(
    make_panel, output_base, tmp_path, stubs, monkeypatch
):
    monkeypatch.setattr(panel_module, "_cpu_count", lambda: 8)
    panel, _chosen = direct_panel(make_panel, tmp_path, "a.txt", "b.txt", "c.txt")
    panel.workers_var.set("100")
    run_attempt(panel)
    log_text = "\n".join(panel.log.details)
    # 3 queued files is the binding constraint here (3 < 8 cores < the Edge
    # backend-safe ceiling of 32) -- an oversized request never OOMs, thrashes,
    # or silently ignores itself; it degrades to what is actually supportable.
    assert "Requested workers: 100 | Effective workers: 3" in log_text


# --------------------------------------------------------------------------- #
# C. Edge/Kokoro actually overlap; Chatterbox never does
# --------------------------------------------------------------------------- #


def test_two_folder_edge_files_actually_overlap_under_workers_2(
    make_panel, output_base, tmp_path, gated_stubs
):
    """The positive proof for the path that was already safe pre-Phase-6:
    ``batch_convert.convert_single_pdf`` does not touch the process cwd, so
    two folder-derived Edge files really can run at once. (Two *direct* Edge
    files cannot -- see the runner-level lock tests in section E below.)"""
    gated_stubs.gate_on = ""  # every filename gates, so both must overlap
    panel, _folders = folder_panel(make_panel, tmp_path, roots=2)
    panel.workers_var.set("2")
    panel.run_job()
    worker = panel._worker
    try:
        wait_for(lambda: len(gated_stubs.order) >= 2,
                 "a second folder Edge file never started concurrently with the first")
    finally:
        gated_stubs.release.set()
        worker.join(WAIT)


def test_a_gated_direct_edge_file_does_not_block_a_concurrent_folder_edge_file(
    make_panel, output_base, tmp_path, gated_stubs
):
    """The unified pool must not serialize unrelated work behind the direct-
    Edge cwd lock (``runner._CWD_ISOLATION_LOCK``): a folder-derived file
    dispatched to a different worker must still run while a direct file is
    gated on a different one."""
    gated_stubs.gate_on = "gate"
    direct = sources(tmp_path / "Loose", "gate.txt")
    root = tmp_path / "Library"
    sources(root, "b.txt")
    panel = make_panel(choose_files=lambda: direct, choose_folder=lambda: (root,))
    panel.importer.add_files()
    panel.importer.add_folder()
    panel._pump.tick()
    panel.workers_var.set("2")
    panel.run_job()
    worker = panel._worker
    try:
        assert gated_stubs.entered.wait(WAIT)
        wait_for(lambda: "b.txt" in gated_stubs.order,
                 "the folder file never ran while the direct file was gated")
    finally:
        gated_stubs.release.set()
        worker.join(WAIT)


def test_four_direct_kokoro_files_overlap_up_to_the_requested_count(
    make_panel, output_base, tmp_path, monkeypatch
):
    from tts import voice_registry as vr

    entered = threading.Event()
    release = threading.Event()
    order: list[str] = []
    lock = threading.Lock()

    def kokoro_file_to_mp3(source_path, output_mp3_path, voice_id, **kwargs):
        with lock:
            order.append(Path(source_path).name)
            if len(order) >= 4:
                entered.set()
        assert release.wait(WAIT), "the gate was never released"
        Path(output_mp3_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_mp3_path).write_bytes(b"audio")

    module = types.ModuleType("tts.kokoro_synth")
    module.kokoro_file_to_mp3 = kokoro_file_to_mp3
    monkeypatch.setitem(sys.modules, "tts.kokoro_synth", module)

    from tts.epub2tts_edge import epub2tts_edge as engine
    monkeypatch.setattr(engine, "ensure_punkt", lambda: None)
    monkeypatch.setattr(panel_module, "ensure_punkt", lambda: None)
    monkeypatch.setattr(panel_module, "_cpu_count", lambda: 8)

    kokoro = next(voice for voice in vr.VOICES if voice.backend == "kokoro")
    panel, _chosen = direct_panel(
        make_panel, tmp_path, "a.txt", "b.txt", "c.txt", "d.txt")
    panel.selected_voice_label.set(kokoro.display_label)
    panel._on_voice_selected()
    panel.workers_var.set("4")
    panel.run_job()
    worker = panel._worker
    try:
        assert entered.wait(WAIT), "four Kokoro files never overlapped under workers=4"
        assert sorted(order) == ["a.txt", "b.txt", "c.txt", "d.txt"]
    finally:
        release.set()
        worker.join(WAIT)


class _GatedChatterboxStub:
    """Stands in for ``tts.chatterbox_synth`` at ``sys.modules``.

    Every call gates -- unlike ``GatedStubs`` (Edge/batch only), this proves
    Chatterbox specifically, since it is the one backend P14 requires to stay
    at an effective cap of 1 regardless of the requested worker count.
    """

    def __init__(self):
        self.order: list[str] = []
        self.voice_ids: list[str] = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def chatterbox_file_to_mp3(self, source_path, output_mp3_path, voice_id, **kwargs):
        self.order.append(Path(source_path).name)
        self.voice_ids.append(voice_id)
        self.entered.set()
        assert self.release.wait(WAIT), "the gate was never released"
        Path(output_mp3_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_mp3_path).write_bytes(b"audio")

    def voice_availability(self, voice_id):
        return True, "ok"

    def install(self, monkeypatch):
        module = types.ModuleType("tts.chatterbox_synth")
        module.chatterbox_file_to_mp3 = self.chatterbox_file_to_mp3
        module.voice_availability = self.voice_availability
        module.ChatterboxUnavailable = RuntimeError
        monkeypatch.setitem(sys.modules, "tts.chatterbox_synth", module)
        return self


def test_chatterbox_never_exceeds_one_concurrent_file_even_when_more_are_requested(
    make_panel, output_base, tmp_path, monkeypatch
):
    """The negative proof P14 requires before Chatterbox could ever be raised
    above 1: two files, two distinct reference voices, workers requested far
    above 1 -- and the second file must still not have started while the
    first is in flight."""
    from tts import voice_registry as vr

    stub = _GatedChatterboxStub().install(monkeypatch)
    from tts.epub2tts_edge import epub2tts_edge as engine
    monkeypatch.setattr(engine, "ensure_punkt", lambda: None)
    monkeypatch.setattr(panel_module, "ensure_punkt", lambda: None)

    chatterbox_voices = [v for v in vr.VOICES if v.backend == "chatterbox"]
    assert len(chatterbox_voices) >= 2, "need two distinct reference voices"
    voice_a, voice_b = chatterbox_voices[0], chatterbox_voices[1]

    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", "two.txt")
    panel.selected_voice_label.set(voice_a.display_label)
    panel._on_voice_selected()
    panel.workers_var.set("4")
    panel.run_job()
    worker = panel._worker
    try:
        assert stub.entered.wait(WAIT), "the engine never started"
        # A short, explicit settle window: proving an absence of concurrency
        # cannot wait for a signal that will never arrive if the cap holds.
        time.sleep(SETTLE)
        assert stub.order == ["one.txt"], (
            f"a second Chatterbox file started concurrently: {stub.order!r}")
    finally:
        stub.release.set()
        worker.join(WAIT)
    assert sorted(stub.order) == ["one.txt", "two.txt"], (
        "both files should still complete once serialized")
    # Every call used the one voice this run was frozen with -- concurrency
    # capping is orthogonal to voice selection; this just confirms the stub
    # itself received a real (if identical, single-voice-per-run) voice_id.
    assert set(stub.voice_ids) == {voice_a.voice_id}
    del voice_b  # documents that a second distinct voice exists; not used per-call


# --------------------------------------------------------------------------- #
# D. No partial/corrupt publication under concurrent cancellation
# --------------------------------------------------------------------------- #


def test_a_success_finishing_during_cancellation_is_recorded_not_orphaned(
    make_panel, output_base, tmp_path, gated_stubs
):
    """The P14 correctness fix this drop makes: an item that finishes
    successfully *after* the user asked to cancel must still be recorded --
    silently dropping it would leave a real output file on disk that the run
    never counted, logged, or could offer for retry, which is itself a form
    of corrupt/partial publication.

    Neither file here is individually cancelled: "keep.txt" runs to
    completion before the cancel is even requested, and the (stubbed) engine
    for "gate.txt" does not raise once released, so it also completes. The
    RUN still settles CANCELLED overall (the user asked to cancel mid-flight)
    -- but that must not cost either file its recorded success and its
    output file. Before this drop's fix, a pool that stopped draining
    results as soon as it noticed the cancellation would have silently
    discarded whichever of the two completed second.
    """
    panel, _chosen = direct_panel(make_panel, tmp_path, "keep.txt", "gate.txt")
    panel.workers_var.set("2")
    panel.run_job()
    worker = panel._worker
    controller = panel._controller
    try:
        assert gated_stubs.entered.wait(WAIT)
        panel.cancel_job()
        gated_stubs.release.set()
        wait_for(lambda: controller.is_terminal, "the run never settled", panel=panel)
    finally:
        worker.join(WAIT)

    result = panel._result
    assert result.cancelled is True
    assert result.succeeded_count == 2, (
        "both files actually finished successfully and must both be counted, "
        "not silently dropped because the run was cancelled overall")
    planned = panel.destinations()
    for name in ("keep.txt", "gate.txt"):
        destination = next(
            entry.destination for entry in planned.values()
            if entry.source.name == name)
        assert destination.exists(), (
            f"{name}'s output must survive -- a recorded success is never discarded")


# --------------------------------------------------------------------------- #
# E. The chdir isolation lock (runner.py) -- the real fix, tested directly
# --------------------------------------------------------------------------- #
#
# GatedStubs (section C) monkeypatches ``runner.run_conversion_job`` itself,
# which replaces the function -- lock and all -- so it cannot observe
# whether the REAL function's own ``_CWD_ISOLATION_LOCK`` actually prevents
# two concurrent calls from both chdir'ing into their own temp directory at
# once. These tests call the real ``run_conversion_job`` and stub only the
# slow internals it calls (``get_book``/``read_book``), so the lock itself is
# exercised end to end.


class _StopEarly(Exception):
    """Lets a stubbed ``read_book`` bail out once the gate has proved its
    point, without needing to stub the rest of the pipeline
    (``make_mp3``/``make_m4b``/``generate_metadata``) just to let
    ``run_conversion_job`` reach a normal return."""


def _write_source(path: Path, title: str) -> None:
    path.write_text(f"Title: {title}\nAuthor: Nobody\n# Chapter\nBody text.\n",
                    encoding="utf-8")


def test_runner_never_lets_two_conversions_be_inside_read_book_at_once(
    tmp_path, monkeypatch
):
    from tts.epub2tts_edge import runner

    inside = {"n": 0}
    max_seen = {"n": 0}
    probe_lock = threading.Lock()
    entered = threading.Event()
    release = threading.Event()

    def fake_get_book(work_txt):
        return (
            [{"title": "blank", "paragraphs": ["One sentence."]}],
            "Book", "Author", ["blank"],
        )

    def fake_read_book(book_contents, speaker, paragraphpause, sentencepause,
                       **kwargs):
        with probe_lock:
            inside["n"] += 1
            max_seen["n"] = max(max_seen["n"], inside["n"])
        entered.set()
        try:
            assert release.wait(WAIT), "the gate was never released"
        finally:
            with probe_lock:
                inside["n"] -= 1
        raise _StopEarly()

    monkeypatch.setattr(runner, "get_book", fake_get_book)
    monkeypatch.setattr(runner, "read_book", fake_read_book)

    src_a = tmp_path / "a.txt"
    src_b = tmp_path / "b.txt"
    _write_source(src_a, "A")
    _write_source(src_b, "B")

    def run(src, out_dir):
        try:
            runner.run_conversion_job(str(src), output_dir=str(out_dir),
                                      audio_format="mp3")
        except _StopEarly:
            pass

    t1 = threading.Thread(target=run, args=(src_a, tmp_path / "out_a"))
    t2 = threading.Thread(target=run, args=(src_b, tmp_path / "out_b"))
    t1.start()
    try:
        assert entered.wait(WAIT), "the first conversion never reached read_book"
        # A short, explicit settle window: t2 gets a real chance to reach
        # read_book too (proving the lock, not luck, is what stops it).
        t2.start()
        time.sleep(SETTLE)
        assert max_seen["n"] == 1, (
            "two conversions were inside read_book at the same time -- the "
            "cwd isolation lock did not hold")
    finally:
        release.set()
        t1.join(WAIT)
        t2.join(WAIT)
    assert max_seen["n"] == 1


def test_a_conversion_cancelled_while_waiting_for_the_lock_does_not_proceed(
    tmp_path, monkeypatch
):
    """A second direct conversion queued behind the lock must not start a
    whole new conversion once it finally acquires the lock, if a cancel was
    requested while it waited."""
    from tts.epub2tts_edge import runner
    from shared.cancellation import ConversionCancelled

    entered = threading.Event()
    release = threading.Event()
    get_book_calls: list[str] = []

    def fake_get_book(work_txt):
        # Both conversions share this patched function -- t1's own
        # (legitimate) call also lands here, so calls are tracked by which
        # source they came from rather than with a single shared flag.
        get_book_calls.append(Path(work_txt).stem)
        return (
            [{"title": "blank", "paragraphs": ["One sentence."]}],
            "Book", "Author", ["blank"],
        )

    def fake_read_book(book_contents, speaker, paragraphpause, sentencepause,
                       **kwargs):
        entered.set()
        assert release.wait(WAIT), "the gate was never released"
        raise _StopEarly()

    monkeypatch.setattr(runner, "get_book", fake_get_book)
    monkeypatch.setattr(runner, "read_book", fake_read_book)

    src_a = tmp_path / "a.txt"
    src_b = tmp_path / "b.txt"
    _write_source(src_a, "A")
    _write_source(src_b, "B")

    cancelled_for_second = threading.Event()

    def run_first():
        try:
            runner.run_conversion_job(str(src_a), output_dir=str(tmp_path / "out_a"),
                                      audio_format="mp3")
        except _StopEarly:
            pass

    def run_second():
        try:
            runner.run_conversion_job(
                str(src_b), output_dir=str(tmp_path / "out_b"), audio_format="mp3",
                cancel_check=cancelled_for_second.is_set)
        except ConversionCancelled:
            pass

    t1 = threading.Thread(target=run_first)
    t2 = threading.Thread(target=run_second)
    t1.start()
    try:
        assert entered.wait(WAIT), "the first conversion never reached read_book"
        t2.start()
        # t2 is now queued behind the lock. Cancel it while it waits, then
        # release the lock -- t2 must never call get_book/read_book at all.
        cancelled_for_second.set()
        release.set()
        t1.join(WAIT)
        t2.join(WAIT)
    finally:
        release.set()
    assert get_book_calls == ["a"], (
        "the second conversion (source stem 'b') must never reach get_book -- "
        f"it started real work after being cancelled while still queued "
        f"behind the cwd isolation lock: {get_book_calls!r}")
