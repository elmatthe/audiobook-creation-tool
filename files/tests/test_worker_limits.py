"""v0.7.1 — how many source files one TTS run converts at once (``tts.worker_limits``).

effective = max(1, min(requested, queued files, engine ceiling, Edge service ceiling, processors, memory)).
The memory ceiling comes from measured costs (``worker_limits`` constants; plan §2 F12-F14) and the queued files'
own sizes, so it reflects both the machine and the workload. Hardware is always injected here: no test reads the
machine it runs on, except the two probes' own sanity checks at the end.
"""

from __future__ import annotations

import math
import sys

import pytest

from tts import worker_limits as wl

GB = 1024 ** 3
MB = 1024 ** 2


def plan(requested, sizes, *, backend="edge", cpus=16, available_gb=16.0, total_gb=32.0):
    memory = None if available_gb is None else wl.MemoryInfo(int(available_gb * GB), int(total_gb * GB))
    return wl.plan_workers(requested, backend, sizes, cpu_count=cpus, memory=memory)


CHAPTER = 20_000      # a 20 KB chapter TXT: about 23 minutes of narration
SHORT = 1_000         # a QA sample: about a minute
VOLUME_PDF = 233 * wl.PDF_CHARS_PER_PAGE  # a whole light-novel volume, sized by its pages


# --------------------------------------------------------------------------- #
# The ordinary cases: the request is honoured
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("requested", [1, 2, 4, 8])
def test_a_capable_machine_honours_1_2_4_and_8_edge_workers(requested):
    result = plan(requested, [SHORT] * 8)
    assert result.effective == requested
    assert result.log_lines() == [f"Requested workers: {requested} | Effective workers: {requested}"]


def test_eight_workers_are_not_capped_at_four_on_a_home_pc_like_machine():
    assert plan(8, [CHAPTER] * 8, cpus=16, available_gb=16, total_gb=32).effective == 8


def test_the_request_never_exceeds_the_queue():
    result = plan(8, [SHORT] * 3)
    assert result.effective == 3
    assert result.log_lines()[1] == "Worker limit: only 3 files are queued."


# --------------------------------------------------------------------------- #
# Oversized requests are bounded by the real constraint, and say which
# --------------------------------------------------------------------------- #


def test_a_request_for_100_on_a_16_processor_machine_runs_16():
    result = plan(100, [SHORT] * 20, cpus=16)
    assert result.effective == 16
    assert result.log_lines() == [
        "Requested workers: 100 | Effective workers: 16",
        "Worker limit: this computer has 16 logical processors (one file per processor).",
    ]


def test_a_high_end_machine_stops_at_the_edge_service_ceiling():
    result = plan(100, [SHORT] * 100, cpus=64, available_gb=200, total_gb=256)
    assert result.effective == wl.EDGE_SERVICE_CEILING
    assert "Edge online service ceiling" in result.log_lines()[1]


def test_32_workers_on_a_16_processor_machine_run_16():
    assert plan(32, [SHORT] * 40, cpus=16).effective == 16


@pytest.mark.parametrize("cpus,expected", [(2, 2), (4, 4), (8, 8), (16, 16), (64, 32)])
def test_the_processor_ceiling_scales_with_the_machine(cpus, expected):
    assert plan(100, [SHORT] * 100, cpus=cpus, available_gb=500, total_gb=512).effective == expected


# --------------------------------------------------------------------------- #
# Memory: measured per-file cost, the machine's free memory, the queue's own sizes
# --------------------------------------------------------------------------- #


def test_a_low_memory_laptop_runs_only_what_fits():
    # 3 GB free of 8 GB: 2 GB stays in reserve (25 % of physical), 1 GB for files of about 317 MB each.
    result = plan(8, [CHAPTER] * 8, cpus=4, available_gb=3, total_gb=8)
    assert result.effective == 3
    assert result.log_lines()[1].startswith("Worker limit: memory")


def test_the_same_laptop_runs_more_short_files_because_they_need_less():
    assert plan(8, [SHORT] * 8, cpus=4, available_gb=3, total_gb=8).effective == 4  # processors bind now


def test_whole_volumes_on_a_home_pc_like_machine_are_held_to_what_memory_allows():
    # Each volume can need about 8.8 GB at assembly (measured slope, conservative sizing); 8 GB is usable.
    result = plan(8, [VOLUME_PDF] * 8, cpus=16, available_gb=16, total_gb=32)
    assert result.effective == 1
    assert "memory" in result.log_lines()[1]


def test_the_memory_ceiling_counts_the_largest_files_first():
    # One huge file and many small ones: the worst case is the huge one running with the next largest.
    sizes = [SHORT] * 15 + [VOLUME_PDF // 4]
    usable = int(11 * GB) - max(wl.MIN_MEMORY_RESERVE, int(wl.MEMORY_RESERVE_FRACTION * 32 * GB))
    peaks = sorted((wl.file_peak_bytes(size) for size in sizes), reverse=True)
    fits = max(n for n in range(1, len(peaks) + 1) if sum(peaks[:n]) <= usable)
    assert fits < 15, "the scenario must make memory the binding limit"
    assert plan(16, sizes, cpus=16, available_gb=11, total_gb=32).effective == fits


def test_when_free_memory_is_below_the_reserve_one_file_still_runs():
    result = plan(8, [CHAPTER] * 8, cpus=8, available_gb=1, total_gb=8)
    assert result.effective == 1


def test_unmeasurable_memory_is_not_invented_and_is_said():
    result = plan(100, [CHAPTER] * 40, cpus=8, available_gb=None)
    assert result.effective == 8
    assert "free memory could not be measured" in result.log_lines()[1]


def test_file_peak_bytes_follows_the_measured_slope():
    seconds = math.ceil(12_000 / wl.NARRATION_CHARS_PER_SECOND)
    assert wl.file_peak_bytes(12_000) == wl.FILE_BASE_BYTES + seconds * wl.PEAK_BYTES_PER_NARRATION_SECOND
    assert wl.file_peak_bytes(0) == wl.FILE_BASE_BYTES


# --------------------------------------------------------------------------- #
# Local engines never run more than one file
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("backend,name", [("kokoro", "Kokoro"), ("chatterbox", "Chatterbox Turbo"),
                                          ("qwen3", "Qwen3-TTS")])
@pytest.mark.parametrize("requested", [1, 2, 8, 100])
def test_local_engines_stay_at_one_file_on_any_machine(backend, name, requested):
    result = plan(requested, [SHORT] * 10, backend=backend, cpus=64, available_gb=500, total_gb=512)
    assert result.effective == 1
    if requested > 1:
        assert result.log_lines()[1] == f"Worker limit: {name} converts one file at a time."


def test_an_unknown_engine_runs_one_file():
    assert plan(8, [SHORT] * 8, backend="somethingelse").effective == 1


# --------------------------------------------------------------------------- #
# Degenerate input
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("requested", [0, -5])
def test_a_request_below_one_runs_one_file(requested):
    result = plan(requested, [SHORT] * 4)
    assert result.effective == 1
    assert result.log_lines() == [f"Requested workers: {requested} | Effective workers: 1"]


def test_an_empty_queue_resolves_to_one():
    assert plan(8, []).effective == 1


def test_an_unknown_processor_count_falls_back_to_four():
    result = plan(100, [SHORT] * 20, cpus=None)
    assert result.effective == 4
    assert "processor count could not be read" in result.log_lines()[1]


# --------------------------------------------------------------------------- #
# Sizing the queued sources
# --------------------------------------------------------------------------- #


def test_a_txt_is_sized_by_its_bytes(tmp_path):
    source = tmp_path / "a.txt"
    source.write_text("x" * 1234, encoding="utf-8")
    assert wl.estimate_source_chars(source) == 1234


def test_a_pdf_is_sized_by_its_pages(tmp_path):
    from tts import pdf_extractor

    doc = pdf_extractor.fitz.open()
    for index in range(3):
        doc.new_page().insert_text((72, 72), f"Page {index}")
    path = tmp_path / "three.pdf"
    doc.save(str(path))
    doc.close()
    assert wl.estimate_source_chars(path) == 3 * wl.PDF_CHARS_PER_PAGE


def test_an_unreadable_pdf_falls_back_to_its_size(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4 not really" * 10)
    assert wl.estimate_source_chars(path) == path.stat().st_size


def test_a_missing_source_counts_as_nothing(tmp_path):
    assert wl.estimate_source_chars(tmp_path / "gone.txt") == 0


def test_plan_for_sources_reads_sizes_and_the_injected_machine(tmp_path, monkeypatch):
    monkeypatch.setattr(wl, "logical_cpus", lambda: 2)
    monkeypatch.setattr(wl, "memory_info", lambda: wl.MemoryInfo(64 * GB, 128 * GB))
    sources = []
    for index in range(5):
        path = tmp_path / f"{index}.txt"
        path.write_text("Some text.", encoding="utf-8")
        sources.append(path)
    assert wl.plan_for_sources(8, "edge", sources).effective == 2


# --------------------------------------------------------------------------- #
# The two machine probes (the only tests that read this machine)
# --------------------------------------------------------------------------- #


def test_logical_cpus_reads_this_machine():
    assert (wl.logical_cpus() or 1) >= 1


def test_memory_info_reads_this_machine_where_it_can():
    info = wl.memory_info()
    if sys.platform == "win32" or sys.platform.startswith("linux"):
        assert info is not None and 0 < info.available <= info.total
    else:
        assert info is None
