"""TTS file-worker concurrency through the real panel (v0.6.5 Phase 6 P14; v0.7.1 Edge multi-file workers).

``Workers = X`` is a requested *whole-file* concurrency level, never permission to parallelize the chunks inside one
source file. The run resolves an effective count through ``tts.worker_limits`` (its own pure tests:
``test_worker_limits.py``) and logs ``Requested workers: X | Effective workers: Y`` plus the limit that applied.

* **v0.7.1:** directly added Edge files are no longer serialized. ``runner.run_conversion_job`` used to ``os.chdir``
  into a private folder behind a process-wide lock, so an all-direct queue resolved to one worker; the engine now
  takes an explicit working folder (``test_edge_direct_concurrency.py`` proves the runner itself). Section E here
  proves it end to end through the real panel, with the **real runner, engine and folder worker** and only the
  network request replaced: a ``threading.Barrier`` that every file must reach from inside synthesis.
* Kokoro, Chatterbox and Qwen3 never run more than one file, however many workers are requested (section C).
* Pause/Cancel/Retry Failed and "no partial/corrupt publication" stay correct with several files in flight.

Determinism follows ``test_tts_jobs.py``: bounded waits, every fixture under ``tmp_path``, and the machine injected
(``worker_limits.logical_cpus`` / ``memory_info``) so no expectation depends on the computer running the suite.
Tests that must prove an *absence* of concurrency bound their wait with a short, explicit settle window.
"""

from __future__ import annotations

import errno
import io
import os
import queue
import re
import sys
import threading
import time
import types
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from tts import epub2tts_gui as panel_module  # noqa: E402
from tts import worker_limits  # noqa: E402

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
    accept,
    direct_panel,
    finish,
    folder_panel,
    gated_stubs,
    mixed_panel,
    run_attempt,
    wait_for,
)

#: How long to let a (correctly) non-concurrent engine "settle" before concluding a second file never started.
SETTLE = 0.3
GB = 1024 ** 3


def machine(monkeypatch, cpus: int = 8, available_gb: float = 64, total_gb: float = 128) -> None:
    monkeypatch.setattr(worker_limits, "logical_cpus", lambda: cpus)
    monkeypatch.setattr(worker_limits, "memory_info",
                        lambda: worker_limits.MemoryInfo(int(available_gb * GB), int(total_gb * GB)))


@pytest.fixture(autouse=True)
def _known_machine(monkeypatch):
    """A known, portable machine for every test here: 8 processors and plenty of free memory."""
    machine(monkeypatch)


def log_text(panel) -> str:
    return "\n".join(panel.log.details)


# --------------------------------------------------------------------------- #
# A. The run resolves and states its workers truthfully
# --------------------------------------------------------------------------- #


def test_the_run_log_states_requested_and_effective_workers_truthfully(make_panel, output_base, tmp_path, stubs):
    panel, _folders = folder_panel(make_panel, tmp_path)
    panel.workers_var.set("2")
    run_attempt(panel)
    assert "Requested workers: 2 | Effective workers: 2" in log_text(panel)
    assert "Worker limit:" not in log_text(panel), "nothing was limited, so no limit is reported"


def test_an_oversized_workers_request_degrades_to_the_queue_and_says_so(make_panel, output_base, tmp_path, stubs):
    panel, _folders = folder_panel(make_panel, tmp_path, roots=2)
    panel.workers_var.set("100")
    run_attempt(panel)
    assert "Requested workers: 100 | Effective workers: 4" in log_text(panel)
    assert "Worker limit: only 4 files are queued." in log_text(panel)


def test_an_all_direct_edge_queue_is_no_longer_capped_to_one(make_panel, output_base, tmp_path, stubs):
    panel, _chosen = direct_panel(make_panel, tmp_path, "a.txt", "b.txt", "c.txt")
    panel.workers_var.set("2")
    run_attempt(panel)
    assert "Requested workers: 2 | Effective workers: 2" in log_text(panel)


def test_a_mixed_edge_queue_uses_every_queued_file(make_panel, output_base, tmp_path, stubs):
    panel, _direct, _folders = mixed_panel(make_panel, tmp_path)
    panel.workers_var.set("8")
    run_attempt(panel)
    assert "Requested workers: 8 | Effective workers: 4" in log_text(panel)


def test_a_request_for_100_is_held_to_the_machines_processors(make_panel, output_base, tmp_path, stubs, monkeypatch):
    machine(monkeypatch, cpus=16)
    names = [f"{index:02d}.txt" for index in range(20)]
    panel, _chosen = direct_panel(make_panel, tmp_path, *names)
    panel.workers_var.set("100")
    params = run_attempt(panel)
    assert "Requested workers: 100 | Effective workers: 16" in log_text(panel)
    assert "Worker limit: this computer has 16 logical processors (one file per processor)." in log_text(panel)
    assert params["workers"] == 100, "the request itself is frozen unchanged"


def test_a_low_memory_machine_holds_large_files_back_and_says_why(make_panel, output_base, tmp_path, stubs,
                                                                   monkeypatch):
    # 3.5 GB free of 8 GB: 2 GB stays in reserve. Each file is one ~38 KB paragraph, in memory until it is whole, and is
    # budgeted about 0.7 GB for that and the same again to assemble: two at once would not fit in the 1.5 GB left.
    machine(monkeypatch, cpus=8, available_gb=3.5, total_gb=8)
    chosen = sources(tmp_path / "Big", "a.txt", "b.txt", "c.txt", "d.txt")
    for path in chosen:
        path.write_text("Long chapter text. " * 2000, encoding="utf-8")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    panel.workers_var.set("4")
    run_attempt(panel)
    text = log_text(panel)
    assert "Requested workers: 4 | Effective workers: 1" in text
    assert "Worker limit: memory" in text


def test_the_workers_box_accepts_up_to_100(make_panel, output_base):
    panel = make_panel()
    assert int(float(str(panel.spin_workers.cget("from")))) == 1
    assert int(float(str(panel.spin_workers.cget("to")))) == panel_module.MAX_REQUESTED_WORKERS == 100


# --------------------------------------------------------------------------- #
# B. Direct and folder items share one pool and one resolved count
# --------------------------------------------------------------------------- #


def test_a_mixed_queue_still_converts_every_item_through_its_own_engine(make_panel, output_base, tmp_path, stubs):
    """Merging direct+folder dispatch must not change *which* engine call a file takes."""
    panel, _direct, _folders = mixed_panel(make_panel, tmp_path)
    panel.workers_var.set("2")
    params = run_attempt(panel)

    assert len(stubs.conversion_jobs) == 2, "the two directly added files"
    assert len(stubs.batch_items) == 2, "the two folder-derived files"
    for item in params["items"]:
        assert item["destination"].exists()


# --------------------------------------------------------------------------- #
# C. Dispatch overlap for Edge; Kokoro, Chatterbox and Qwen3 never overlap
# --------------------------------------------------------------------------- #


def test_two_folder_edge_files_actually_overlap_under_workers_2(make_panel, output_base, tmp_path, gated_stubs):
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


def test_two_direct_edge_files_are_dispatched_together_under_workers_2(make_panel, output_base, tmp_path,
                                                                        gated_stubs):
    gated_stubs.gate_on = ""
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", "two.txt")
    panel.workers_var.set("2")
    panel.run_job()
    worker = panel._worker
    try:
        wait_for(lambda: len(gated_stubs.order) >= 2, "the second direct file waited for the first")
    finally:
        gated_stubs.release.set()
        worker.join(WAIT)


def test_a_gated_direct_edge_file_does_not_block_a_concurrent_folder_edge_file(make_panel, output_base, tmp_path,
                                                                                gated_stubs):
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
        wait_for(lambda: "b.txt" in gated_stubs.order, "the folder file never ran while the direct file was gated")
    finally:
        gated_stubs.release.set()
        worker.join(WAIT)


def test_kokoro_never_exceeds_one_concurrent_file_even_when_more_are_requested(make_panel, output_base, tmp_path,
                                                                                monkeypatch):
    """Kokoro's cached per-lang-code pipeline shares a non-reentrant espeak-ng G2P fallback (v0.6.5 Phase 9)."""
    entered = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def kokoro_file_to_mp3(source_path, output_mp3_path, voice_id, **kwargs):
        order.append(Path(source_path).name)
        entered.set()
        assert release.wait(WAIT), "the gate was never released"
        Path(output_mp3_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_mp3_path).write_bytes(b"audio")

    module = types.ModuleType("tts.kokoro_synth")
    module.kokoro_file_to_mp3 = kokoro_file_to_mp3
    monkeypatch.setitem(sys.modules, "tts.kokoro_synth", module)

    from tts import voice_registry as vr
    from tts.epub2tts_edge import epub2tts_edge as engine
    monkeypatch.setattr(engine, "ensure_punkt", lambda: None)
    monkeypatch.setattr(panel_module, "ensure_punkt", lambda: None)
    machine(monkeypatch, cpus=64, available_gb=500, total_gb=512)

    kokoro = next(voice for voice in vr.VOICES if voice.backend == "kokoro")
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", "two.txt")
    panel.selected_voice_label.set(kokoro.display_label)
    panel._on_voice_selected()
    panel.workers_var.set("100")
    panel.run_job()
    worker = panel._worker
    try:
        assert entered.wait(WAIT), "the first Kokoro file never started"
        time.sleep(SETTLE)
        assert order == ["one.txt"], "a second Kokoro file started concurrently"
    finally:
        release.set()
        worker.join(WAIT)
    wait_for(lambda: "Worker limit: Kokoro converts one file at a time." in log_text(panel),
             "the run log never said why Kokoro ran one file", panel=panel)


class _GatedChatterboxStub:
    """Stands in for ``tts.chatterbox_synth`` at ``sys.modules``; every call gates."""

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


def test_chatterbox_never_exceeds_one_concurrent_file_even_when_more_are_requested(make_panel, output_base,
                                                                                    tmp_path, monkeypatch):
    from tts import voice_registry as vr

    stub = _GatedChatterboxStub().install(monkeypatch)
    from tts.epub2tts_edge import epub2tts_edge as engine
    monkeypatch.setattr(engine, "ensure_punkt", lambda: None)
    monkeypatch.setattr(panel_module, "ensure_punkt", lambda: None)
    machine(monkeypatch, cpus=64, available_gb=500, total_gb=512)

    chatterbox_voices = [v for v in vr.VOICES if v.backend == "chatterbox"]
    voice_a = chatterbox_voices[0]
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", "two.txt")
    panel.selected_voice_label.set(voice_a.display_label)
    panel._on_voice_selected()
    panel.workers_var.set("8")
    panel.run_job()
    worker = panel._worker
    try:
        assert stub.entered.wait(WAIT), "the engine never started"
        time.sleep(SETTLE)
        assert stub.order == ["one.txt"], f"a second Chatterbox file started concurrently: {stub.order!r}"
    finally:
        stub.release.set()
        worker.join(WAIT)
    assert sorted(stub.order) == ["one.txt", "two.txt"], "both files should still complete once serialized"
    assert set(stub.voice_ids) == {voice_a.voice_id}


# --------------------------------------------------------------------------- #
# D. No partial/corrupt publication under concurrent cancellation (dispatch level)
# --------------------------------------------------------------------------- #


def test_a_success_finishing_during_cancellation_is_recorded_not_orphaned(make_panel, output_base, tmp_path,
                                                                          gated_stubs):
    """An item that finishes successfully *after* cancel was requested is still recorded, and its output kept."""
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
    wait_for(lambda: panel._result is not None, "the settled result never reached the panel", panel=panel)
    result = panel._result
    assert result.cancelled is True
    assert result.succeeded_count == 2
    for name in ("keep.txt", "gate.txt"):
        destination = next(entry.destination for entry in panel.destinations().values() if entry.source.name == name)
        assert destination.exists(), f"{name}'s output must survive -- a recorded success is never discarded"


# --------------------------------------------------------------------------- #
# E. Real engines through the real panel: only the network request is replaced
# --------------------------------------------------------------------------- #


_CLIP: dict[str, bytes] = {}


def _clip() -> bytes:
    if "mp3" not in _CLIP:
        from pydub.generators import Sine
        from shared import ffmpeg_utils

        ffmpeg_utils.configure_pydub()
        buf = io.BytesIO()
        Sine(440, sample_rate=24000).to_audio_segment(duration=90, volume=-20).export(buf, format="mp3")
        _CLIP["mp3"] = buf.getvalue()
    return _CLIP["mp3"]


class FakeService:
    """The Edge network request, both routes. Everything else -- runner, engine, folder worker -- is real.

    ``barrier`` must be reached by every file from inside its first request: a file that could not start until
    another finished would break it. ``fail_word`` makes requests containing it fail; ``after_barrier`` runs once
    every file is inside synthesis.
    """

    def __init__(self, barrier=None, fail_word=None, after_barrier=None):
        self.barrier = barrier
        self.fail_word = fail_word
        self.after_barrier = after_barrier
        self.lock = threading.Lock()
        self.seen: set[str] = set()
        self.requests: list[tuple[str, str]] = []

    def _request(self, key: str, text: str, path) -> None:
        with self.lock:
            self.requests.append((key, text))
            first = key not in self.seen
            self.seen.add(key)
        if first and self.barrier is not None:
            self.barrier.wait(WAIT)
            if self.after_barrier is not None:
                self.after_barrier()
        if self.fail_word and self.fail_word in text:
            raise ValueError("simulated request failure")  # a local error: never retried, never slept on
        Path(path).write_bytes(_clip())

    def edgespeak(self, sentence, speaker, filename):
        self._request(os.path.dirname(os.path.abspath(filename)), sentence, filename)

    def chunk(self, text, path, voice, rate):
        self._request(str(Path(path).parent), text, path)

    def install(self, monkeypatch):
        from tts import batch_convert
        from tts.epub2tts_edge import epub2tts_edge as engine

        monkeypatch.setattr(engine, "run_edgespeak", self.edgespeak)
        monkeypatch.setattr(engine, "_SENTENCE_TOKENIZER", None, raising=False)
        monkeypatch.setattr(batch_convert, "synthesize_chunk_mp3", self.chunk)
        monkeypatch.setattr(batch_convert, "INTER_CHUNK_DELAY_SEC", 0)
        return self

    def texts_by_source(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for key, text in self.requests:
            grouped.setdefault(key, []).append(text)
        return {texts[0].split()[0]: texts for texts in grouped.values()}


def _once(action):
    """*action* the first time only, for a hook every worker passes through."""
    asked = threading.Lock()

    def run():
        if asked.acquire(blocking=False):
            action()

    return run


def book(folder: Path, name: str, word: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(f"{word} speaks first. {word} speaks again.\n\n{word} closes the file.\n", encoding="utf-8")
    return path


def real_panel(make_panel, direct=(), folders=()):
    pending = list(folders)
    panel = make_panel(choose_files=lambda: tuple(direct),
                       choose_folder=lambda: (pending.pop(0),) if pending else ())
    if direct:
        panel.importer.add_files()
    for _ in folders:
        panel.importer.add_folder()
        panel._pump.tick()
    return panel


needs_ffmpeg = pytest.mark.skipif(
    not __import__("shared.ffmpeg_utils", fromlist=["have_ffmpeg"]).have_ffmpeg(),
    reason="requires a real ffmpeg/ffprobe pair")


@needs_ffmpeg
def test_eight_direct_edge_files_convert_at_once_through_the_real_panel(make_panel, output_base, tmp_path,
                                                                        monkeypatch):
    machine(monkeypatch, cpus=16)
    service = FakeService(barrier=threading.Barrier(8)).install(monkeypatch)
    words = [f"Voice{chr(65 + i)}" for i in range(8)]
    chosen = tuple(book(tmp_path / "Loose", f"{w}.txt", w) for w in words)
    panel = real_panel(make_panel, direct=chosen)
    panel.workers_var.set("8")
    progress: list[tuple[int, int]] = []
    real_progress = panel_module.RunPublisher.progress

    def spy(self, completed, total=None, **kwargs):
        progress.append((completed, total))
        return real_progress(self, completed, total, **kwargs)

    monkeypatch.setattr(panel_module.RunPublisher, "progress", spy)

    params = run_attempt(panel)

    assert "Requested workers: 8 | Effective workers: 8" in log_text(panel)
    result = panel._result
    assert result is not None and result.succeeded_count == 8 and not result.cancelled
    for item in params["items"]:
        assert item["destination"].is_file() and item["destination"].stat().st_size > 0
    grouped = service.texts_by_source()
    assert sorted(grouped) == sorted(words)
    for word, texts in grouped.items():
        assert texts == [f"{word} speaks first.", f"{word} speaks again.", f"{word} closes the file."]
    assert progress[0] == (0, 8) and [c for c, _t in progress[1:]] == list(range(1, 9)), progress


@needs_ffmpeg
def test_the_detailed_log_stays_readable_while_eight_files_convert_at_once(make_panel, output_base, tmp_path,
                                                                           monkeypatch):
    """Found on HOME-PC's real 8-file run: tqdm stacks simultaneous bars with newlines and cursor-up codes, which the
    log pane showed as empty "[file] " lines and raw escape characters. Every line must say something, and no
    terminal control codes reach the pane; each file still gets its own progress line, as with one worker."""
    machine(monkeypatch, cpus=16)
    FakeService(barrier=threading.Barrier(8)).install(monkeypatch)  # every file's bar is live at the same time
    words = [f"Voice{chr(65 + i)}" for i in range(8)]
    chosen = tuple(book(tmp_path / "Loose", f"{w}.txt", w) for w in words)
    panel = real_panel(make_panel, direct=chosen)
    panel.workers_var.set("8")

    run_attempt(panel)

    assert panel._result.succeeded_count == 8
    details = list(panel.log.details)
    assert not [line for line in details if "\x1b" in line]
    assert not [line for line in details if re.fullmatch(r"\[[^\]]+\]\s*", line)]
    for word in words:
        bars = [line for line in details if line.startswith(f"[{word}.txt] ") and "Generating audio files" in line]
        assert len(bars) == 1 and "100%" in bars[0], bars


@needs_ffmpeg
def test_direct_and_folder_files_overlap_with_the_real_engines(make_panel, output_base, tmp_path, monkeypatch):
    service = FakeService(barrier=threading.Barrier(4)).install(monkeypatch)
    direct = (book(tmp_path / "Loose", "a.txt", "DirectA"), book(tmp_path / "Loose", "b.txt", "DirectB"))
    root = tmp_path / "Library"
    book(root, "c.txt", "FolderC")
    book(root / "Sub", "d.txt", "FolderD")
    panel = real_panel(make_panel, direct=direct, folders=(root,))
    panel.workers_var.set("4")

    params = run_attempt(panel)

    assert "Requested workers: 4 | Effective workers: 4" in log_text(panel)
    assert panel._result.succeeded_count == 4
    assert all(item["destination"].is_file() for item in params["items"])
    grouped = service.texts_by_source()
    assert sorted(grouped) == ["DirectA", "DirectB", "FolderC", "FolderD"]
    # The folder route sends whole chunks; the direct route sends sentences. Both carry only their own file's text.
    assert grouped["FolderC"] == ["FolderC speaks first. FolderC speaks again.\n\nFolderC closes the file."]


@needs_ffmpeg
def test_a_direct_pdf_and_a_direct_txt_convert_together(make_panel, output_base, tmp_path, monkeypatch):
    from tts import pdf_extractor

    service = FakeService(barrier=threading.Barrier(2)).install(monkeypatch)
    doc = pdf_extractor.fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter 1")  # the PDF's first line becomes its spoken heading
    page.insert_text((72, 144), "Paper speaks from a page.")
    pdf = tmp_path / "Loose" / "paper.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(pdf))
    doc.close()
    txt = book(tmp_path / "Loose", "plain.txt", "Plain")
    panel = real_panel(make_panel, direct=(pdf, txt))
    panel.workers_var.set("2")

    run_attempt(panel)

    assert panel._result.succeeded_count == 2
    grouped = service.texts_by_source()
    # Speech preparation (the panel's default) reads the heading's number as a word.
    assert grouped["Chapter"] == ["Chapter one", "Paper speaks from a page."]
    assert grouped["Plain"][0] == "Plain speaks first."


@needs_ffmpeg
def test_retry_failed_reruns_only_the_file_that_failed_beside_others(make_panel, output_base, tmp_path,
                                                                     monkeypatch):
    service = FakeService(barrier=threading.Barrier(4), fail_word="Fragile").install(monkeypatch)
    words = ["Sturdy", "Fragile", "Solid", "Stable"]
    chosen = tuple(book(tmp_path / "Loose", f"{w}.txt", w) for w in words)
    panel = real_panel(make_panel, direct=chosen)
    panel.workers_var.set("4")

    params = run_attempt(panel)

    first = panel._result
    assert first.succeeded_count == 3 and first.has_retryable
    by_name = {item["source"].name: item["destination"] for item in params["items"]}
    assert not by_name["Fragile.txt"].exists(), "the failed file published nothing"
    kept = {name: path.read_bytes() for name, path in by_name.items() if name != "Fragile.txt"}

    service.fail_word = None
    service.barrier = None
    before = len(service.requests)
    retry = run_attempt(panel, panel.retry_failed)

    assert [item["source"].name for item in retry["items"]] == ["Fragile.txt"]
    assert {text.split()[0] for _key, text in service.requests[before:]} == {"Fragile"}
    assert by_name["Fragile.txt"].is_file(), "the retry lands on the occurrence's own planned destination"
    for name, data in kept.items():
        assert by_name[name].read_bytes() == data, f"{name} was rewritten by the retry"


def _stage_files(folder: Path) -> list[Path]:
    from shared import output_paths

    return [p for p in folder.rglob("*") if p.name.startswith(output_paths.TEMP_SIBLING_PREFIX)]


def _fail_publication_of(monkeypatch, word: str, failure: OSError) -> None:
    """A full disk at the moment *word*'s file gets its final name in the run folder."""
    from tts import publication

    for name in ("_publish_no_clobber", "_publish_replacing"):
        real = getattr(publication, name)

        def publish(staged, destination, _real=real):
            if word in Path(destination).name and "tts_direct_" not in str(destination):
                raise failure
            _real(staged, destination)

        monkeypatch.setattr(publication, name, publish)


@needs_ffmpeg
def test_retry_failed_recovers_an_interrupted_publication_and_keeps_its_siblings(make_panel, output_base, tmp_path,
                                                                                 monkeypatch):
    """Direct route: the disk filled just as one finished file was to get its name. It is an ordinary failed item:
    nothing under its name, no staging left, the others intact, and Retry Failed finishes the job."""
    service = FakeService().install(monkeypatch)
    words = ["Sturdy", "Fragile", "Solid"]
    chosen = tuple(book(tmp_path / "Loose", f"{w}.txt", w) for w in words)
    panel = real_panel(make_panel, direct=chosen)
    panel.workers_var.set("3")
    with monkeypatch.context() as during_the_fault:
        _fail_publication_of(during_the_fault, "Fragile", OSError(errno.ENOSPC, "simulated: disk full"))
        params = run_attempt(panel)

    first = panel._result
    assert first.succeeded_count == 2 and first.has_retryable
    by_name = {item["source"].name: item["destination"] for item in params["items"]}
    assert not by_name["Fragile.txt"].exists()
    assert _stage_files(params["run_directory"]) == []
    kept = {name: by_name[name].read_bytes() for name in ("Sturdy.txt", "Solid.txt")}

    before = len(service.requests)
    retry = run_attempt(panel, panel.retry_failed)

    assert [item["source"].name for item in retry["items"]] == ["Fragile.txt"]
    assert {text.split()[0] for _key, text in service.requests[before:]} == {"Fragile"}
    assert by_name["Fragile.txt"].stat().st_size > 0
    assert panel._result.has_retryable is False
    for name, data in kept.items():
        assert by_name[name].read_bytes() == data, name


@needs_ffmpeg
def test_retry_failed_recovers_an_interrupted_folder_publication_in_its_mirrored_folder(make_panel, output_base, tmp_path,
                                                                                        monkeypatch):
    """Folder route, a nested source: the same recovery, at the same mirrored destination."""
    service = FakeService().install(monkeypatch)
    root = tmp_path / "Library"
    book(root, "Sturdy.txt", "Sturdy")
    book(root / "Volume One", "Fragile.txt", "Fragile")
    panel = real_panel(make_panel, folders=(root,))
    panel.workers_var.set("2")
    with monkeypatch.context() as during_the_fault:
        _fail_publication_of(during_the_fault, "Fragile", OSError(errno.ENOSPC, "simulated: disk full"))
        params = run_attempt(panel)

    by_name = {item["source"].name: item["destination"] for item in params["items"]}
    assert "Volume One" in by_name["Fragile.txt"].parts, "mirrored"
    assert not by_name["Fragile.txt"].exists()
    assert by_name["Sturdy.txt"].stat().st_size > 0
    assert _stage_files(params["run_directory"]) == []
    kept = by_name["Sturdy.txt"].read_bytes()

    retry = run_attempt(panel, panel.retry_failed)

    assert [item["source"].name for item in retry["items"]] == ["Fragile.txt"]
    assert retry["items"][0]["destination"] == by_name["Fragile.txt"], "the frozen destination"
    assert by_name["Fragile.txt"].stat().st_size > 0
    assert by_name["Sturdy.txt"].read_bytes() == kept
    assert service.requests


@needs_ffmpeg
def test_overwrite_off_keeps_a_file_that_appears_during_synthesis_and_fails_only_that_item(make_panel, output_base,
                                                                                           tmp_path, monkeypatch):
    """Codex HIGH-001, through the real panel: a planned name is taken while the run is converting."""
    holder: dict = {}

    def claim_the_name():
        destinations = holder["panel"].destinations()
        for entry in destinations.values():
            if entry.source.name == "Contested.txt":
                entry.destination.parent.mkdir(parents=True, exist_ok=True)
                entry.destination.write_bytes(b"someone else's file")

    FakeService(barrier=threading.Barrier(2), after_barrier=_once(claim_the_name)).install(monkeypatch)
    chosen = (book(tmp_path / "Loose", "Contested.txt", "Contested"), book(tmp_path / "Loose", "Free.txt", "Free"))
    panel = real_panel(make_panel, direct=chosen)
    holder["panel"] = panel
    panel.workers_var.set("2")
    assert panel.overwrite_var.get() is False, "a default run"

    params = run_attempt(panel)

    by_name = {item["source"].name: item["destination"] for item in params["items"]}
    assert by_name["Contested.txt"].read_bytes() == b"someone else's file"
    assert by_name["Free.txt"].stat().st_size > 0
    result = panel._result
    assert result.succeeded_count == 1 and result.has_retryable
    assert _stage_files(params["run_directory"]) == []


@needs_ffmpeg
@pytest.mark.parametrize("route", ["direct", "folder"])
def test_a_default_retry_never_replaces_a_file_at_its_destination(make_panel, output_base, tmp_path, monkeypatch, route):
    """The real engines. The first attempt fails; something is then saved at that path; Retry Failed must leave it."""
    service = FakeService(fail_word="Fragile").install(monkeypatch)
    root = tmp_path / "Library"
    chosen = (book(root, "Fragile.txt", "Fragile"), book(root, "Sturdy.txt", "Sturdy"))
    panel = (real_panel(make_panel, direct=chosen) if route == "direct" else real_panel(make_panel, folders=(root,)))
    panel.workers_var.set("2")
    params = run_attempt(panel)
    by_name = {item["source"].name: item["destination"] for item in params["items"]}
    foreign = by_name["Fragile.txt"]
    assert not foreign.exists()
    foreign.write_bytes(b"not from any attempt")
    kept = by_name["Sturdy.txt"].read_bytes()

    service.fail_word = None
    before = len(service.requests)
    run_attempt(panel, panel.retry_failed)

    assert foreign.read_bytes() == b"not from any attempt"
    assert panel._result.has_retryable, "it failed, and says so"
    assert "already exists" in log_text(panel)
    assert len(service.requests) == before, "and did not synthesise a file it could never publish"
    assert by_name["Sturdy.txt"].read_bytes() == kept
    assert _stage_files(params["run_directory"]) == []


@needs_ffmpeg
@pytest.mark.parametrize("route", ["direct", "folder"])
def test_a_ticked_box_replaces_on_retry_whole_and_only_for_that_run(make_panel, output_base, tmp_path, monkeypatch, route):
    service = FakeService(fail_word="Fragile").install(monkeypatch)
    root = tmp_path / "Library"
    chosen = (book(root, "Fragile.txt", "Fragile"), book(root, "Sturdy.txt", "Sturdy"))
    panel = (real_panel(make_panel, direct=chosen) if route == "direct" else real_panel(make_panel, folders=(root,)))
    panel.workers_var.set("2")
    panel.overwrite_var.set(True)
    params = run_attempt(panel)
    by_name = {item["source"].name: item["destination"] for item in params["items"]}
    target = by_name["Fragile.txt"]
    target.write_bytes(b"replace me")
    panel.overwrite_var.set(False)  # the run froze its own choice

    service.fail_word = None
    run_attempt(panel, panel.retry_failed)

    assert panel._result.has_retryable is False
    assert target.read_bytes() != b"replace me" and target.stat().st_size > 0
    assert _stage_files(params["run_directory"]) == []


class _LocalEngineStubs:
    """All three local engines at ``sys.modules``. Each writes to the path it is given, as the real ones do."""

    def __init__(self, monkeypatch, *, during=None, failing=None):
        self.calls: list[str] = []
        self.during = during
        self.failing = failing
        for module_name, entry in (("tts.kokoro_synth", "kokoro_file_to_mp3"), ("tts.chatterbox_synth", "chatterbox_file_to_mp3"),
                                   ("tts.qwen3_synth", "qwen3_file_to_mp3")):
            module = types.ModuleType(module_name)
            setattr(module, entry, self.engine)
            monkeypatch.setitem(sys.modules, module_name, module)

    def engine(self, source_path, output_mp3_path, voice_id, **kwargs):
        self.calls.append(str(output_mp3_path))
        if self.during is not None:
            self.during()
        Path(output_mp3_path).write_bytes(b"half an encode")
        if self.failing is not None:
            raise self.failing
        Path(output_mp3_path).write_bytes(b"new audio")


LOCAL_ENGINES = [panel_module.convert_with_kokoro, panel_module.convert_with_chatterbox, panel_module.convert_with_qwen3]


def _local_params(overwrite=None):
    params = {"voice_id": "v", "kokoro_speed": 1.0, "end_pause": 0, "paragraph_pause": 1, "bitrate": "192k"}
    if overwrite is not None:
        params["overwrite"] = overwrite
    return params


def _local_item(tmp_path):
    source = tmp_path / "book.txt"
    source.write_text("Words.", encoding="utf-8")
    destination = tmp_path / "run" / "book-Voice.mp3"
    destination.parent.mkdir(parents=True, exist_ok=True)
    return {"item_id": "occ-1", "source": source, "destination": destination}


@pytest.mark.parametrize("convert", LOCAL_ENGINES)
def test_a_local_engine_publishes_whole_and_never_writes_at_the_destination_itself(tmp_path, monkeypatch, convert):
    item = _local_item(tmp_path)
    stubs = _LocalEngineStubs(monkeypatch)
    convert(item, _local_params(False), None, lambda _m: None, lambda: False)
    assert item["destination"].read_bytes() == b"new audio"
    assert Path(stubs.calls[0]) != item["destination"]
    assert _stage_files(item["destination"].parent) == []


@pytest.mark.parametrize("convert", LOCAL_ENGINES)
@pytest.mark.parametrize("overwrite", [False, None], ids=["off", "absent"])
def test_a_local_engine_does_not_even_start_when_it_could_not_publish(tmp_path, monkeypatch, convert, overwrite):
    item = _local_item(tmp_path)
    item["destination"].write_bytes(b"theirs")
    stubs = _LocalEngineStubs(monkeypatch)
    with pytest.raises(FileExistsError):
        convert(item, _local_params(overwrite), None, lambda _m: None, lambda: False)
    assert stubs.calls == [], "no model loaded for a file it could never publish"
    assert item["destination"].read_bytes() == b"theirs"


@pytest.mark.parametrize("convert", LOCAL_ENGINES)
def test_a_local_engine_never_replaces_a_file_that_appears_while_it_runs(tmp_path, monkeypatch, convert):
    item = _local_item(tmp_path)
    _LocalEngineStubs(monkeypatch, during=lambda: item["destination"].write_bytes(b"appeared meanwhile"))
    with pytest.raises(FileExistsError):
        convert(item, _local_params(False), None, lambda _m: None, lambda: False)
    assert item["destination"].read_bytes() == b"appeared meanwhile"
    assert _stage_files(item["destination"].parent) == []


@pytest.mark.parametrize("convert", LOCAL_ENGINES)
def test_a_ticked_box_lets_a_local_engine_replace_whole(tmp_path, monkeypatch, convert):
    item = _local_item(tmp_path)
    item["destination"].write_bytes(b"replace me")
    _LocalEngineStubs(monkeypatch)
    convert(item, _local_params(True), None, lambda _m: None, lambda: False)
    assert item["destination"].read_bytes() == b"new audio"


@pytest.mark.parametrize("convert", LOCAL_ENGINES)
@pytest.mark.parametrize("failure", [RuntimeError("the engine failed"), panel_module.ConversionCancelled("cancelled")],
                         ids=["failed", "cancelled"])
def test_a_failed_or_cancelled_local_engine_leaves_a_ticked_destination_untouched(tmp_path, monkeypatch, convert, failure):
    """The engine's half-written file is in scratch; the old output stays whole, even with permission to replace it."""
    item = _local_item(tmp_path)
    item["destination"].write_bytes(b"the old valid output")
    _LocalEngineStubs(monkeypatch, failing=failure)
    with pytest.raises(type(failure)):
        convert(item, _local_params(True), None, lambda _m: None, lambda: False)
    assert item["destination"].read_bytes() == b"the old valid output"
    assert _stage_files(item["destination"].parent) == []


@needs_ffmpeg
def test_a_run_whose_assemblies_cannot_overlap_still_synthesises_side_by_side(make_panel, output_base, tmp_path,
                                                                              monkeypatch):
    """The second memory layer: when memory allows one assembly at a time, only assembly waits. The barrier proves all
    four files were inside synthesis together; the counter proves no two were assembling at once."""
    from tts.epub2tts_edge import runner

    machine(monkeypatch)
    # The plan admits all four; the gate then sees real sizes and only 1 GiB usable, so each takes the whole of it.
    tight = worker_limits.MemoryInfo(5 * GB, 16 * GB)
    gate = worker_limits.AssemblyGate(lambda: tight, poll_seconds=0.01)
    monkeypatch.setattr(worker_limits, "ASSEMBLY_GATE", gate)
    monkeypatch.setattr(worker_limits, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    monkeypatch.setattr(worker_limits, "FILE_BASE_BYTES", int(0.8 * GB))  # each join budgeted at more than half of it
    lock = threading.Lock()
    inside = [0]
    peak = [0]
    real_make = runner.make_mp3

    def make_mp3(*args, **kwargs):
        with lock:
            inside[0] += 1
            peak[0] = max(peak[0], inside[0])
        try:
            time.sleep(0.05)
            return real_make(*args, **kwargs)
        finally:
            with lock:
                inside[0] -= 1

    monkeypatch.setattr(runner, "make_mp3", make_mp3)
    FakeService(barrier=threading.Barrier(4)).install(monkeypatch)
    chosen = tuple(book(tmp_path / "Loose", f"{w}.txt", w) for w in ("One", "Two", "Three", "Four"))
    panel = real_panel(make_panel, direct=chosen)
    panel.workers_var.set("4")

    params = run_attempt(panel)

    assert panel._result.succeeded_count == 4
    assert peak[0] == 1
    assert all(item["destination"].stat().st_size > 0 for item in params["items"])


@needs_ffmpeg
def test_cancelling_a_real_concurrent_run_leaves_no_output(make_panel, output_base, tmp_path, monkeypatch):
    panel_holder: dict = {}
    asked = threading.Lock()

    def cancel_once():
        # Exactly what the Cancel button asks of the controller, once, while all four files are mid-synthesis.
        if asked.acquire(blocking=False):
            panel_holder["panel"]._controller.request_cancel()

    service = FakeService(barrier=threading.Barrier(4), after_barrier=cancel_once)
    service.install(monkeypatch)
    chosen = tuple(book(tmp_path / "Loose", f"{w}.txt", w) for w in ("One", "Two", "Three", "Four"))
    panel = real_panel(make_panel, direct=chosen)
    panel_holder["panel"] = panel
    panel.workers_var.set("4")

    params = run_attempt(panel)

    result = panel._result
    assert result is not None and result.cancelled
    assert result.succeeded_count == 0
    assert not any(item["destination"].exists() for item in params["items"])


@needs_ffmpeg
def test_same_named_direct_files_from_two_folders_get_their_own_outputs(make_panel, output_base, tmp_path,
                                                                        monkeypatch):
    service = FakeService(barrier=threading.Barrier(2)).install(monkeypatch)
    first = book(tmp_path / "Book A", "chapter.txt", "Ashen")
    second = book(tmp_path / "Book B", "chapter.txt", "Birch")
    panel = real_panel(make_panel, direct=(first, second))
    panel.workers_var.set("2")

    params = run_attempt(panel)

    destinations = [item["destination"] for item in params["items"]]
    assert len(set(destinations)) == 2 and all(path.is_file() for path in destinations)
    assert sorted(service.texts_by_source()) == ["Ashen", "Birch"]


# --------------------------------------------------------------------------- #
# F. Engine text from several files never interleaves mid-line
# --------------------------------------------------------------------------- #


def drain(q: queue.Queue) -> str:
    out = []
    while True:
        try:
            out.append(q.get_nowait()[1])
        except queue.Empty:
            return "".join(out)


def test_each_file_writes_whole_prefixed_lines(tmp_path):
    q: queue.Queue = queue.Queue()
    writer = panel_module.QueueWriter(q)
    a_started, b_wrote = threading.Event(), threading.Event()

    def file_a():
        with writer.file_scope("a.txt"):
            writer.write("Chapter name: ")
            a_started.set()
            assert b_wrote.wait(WAIT)
            writer.write("Alpha\n")

    def file_b():
        assert a_started.wait(WAIT)
        with writer.file_scope("b.txt"):
            writer.write("Chapter name: Beta\n")
        b_wrote.set()

    threads = [threading.Thread(target=file_a), threading.Thread(target=file_b)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT)
    assert drain(q).splitlines() == ["[b.txt] Chapter name: Beta", "[a.txt] Chapter name: Alpha"]


def test_a_partial_line_is_kept_until_its_file_ends():
    q: queue.Queue = queue.Queue()
    writer = panel_module.QueueWriter(q)
    with writer.file_scope("x.txt"):
        writer.write("no newline yet")
        assert drain(q) == ""
    assert drain(q) == "[x.txt] no newline yet\n"


def test_text_outside_any_file_is_unprefixed_and_flushed_at_the_end():
    q: queue.Queue = queue.Queue()
    writer = panel_module.QueueWriter(q)
    writer.write("Run line\n")
    writer.write("dangling")
    assert drain(q) == "Run line\n"
    writer.flush_all()
    assert drain(q) == "dangling\n"


def test_a_blank_line_stays_blank_rather_than_a_bare_file_label():
    q: queue.Queue = queue.Queue()
    writer = panel_module.QueueWriter(q)
    with writer.file_scope("x.txt"):
        writer.write("\n\nChapter name: X\n")
    assert drain(q) == "\n\n[x.txt] Chapter name: X\n"


# --------------------------------------------------------------------------- #
# G. Every registered Edge voice has the same multi-file capability
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("voice", [v for v in __import__("tts.voice_registry", fromlist=["VOICES"]).VOICES
                                   if v.backend == "edge"], ids=lambda v: v.voice_id)
def test_every_edge_voice_converts_eight_direct_files_at_once(make_panel, output_base, tmp_path, gated_stubs,
                                                              monkeypatch, voice):
    machine(monkeypatch, cpus=16)
    gated_stubs.gate_on = ""  # every file holds inside the engine until released: all eight must be in at once
    names = [f"{index}.txt" for index in range(8)]
    panel, _chosen = direct_panel(make_panel, tmp_path, *names)
    panel.selected_voice_label.set(voice.display_label)
    panel._on_voice_selected()
    panel.workers_var.set("8")
    panel.run_job()
    worker = panel._worker
    try:
        wait_for(lambda: len(gated_stubs.order) == 8, f"{voice.voice_id}: eight files were not in flight together")
    finally:
        gated_stubs.release.set()
        worker.join(WAIT)
    wait_for(lambda: "Requested workers: 8 | Effective workers: 8" in log_text(panel), "no worker line", panel=panel)
    assert {job["speaker"] for job in gated_stubs.conversion_jobs} == {voice.voice_id}
