"""v0.7.1 — how many source files one TTS run converts at once, and when one may assemble (``tts.worker_limits``).

effective = max(1, min(requested, queued files, engine ceiling, Edge service ceiling, processors, memory)).
The memory ceiling comes from a model of each queued file's narration, and a runtime gate admits each assembly by its
real size, because the model can be wrong. Hardware is always injected here: no test reads the machine it runs on,
except the two probes' own sanity checks at the end.
"""

from __future__ import annotations

import sys
import threading
import time

import pytest

from shared.cancellation import ConversionCancelled
from tts import worker_limits as wl

GB = 1024 ** 3
MB = 1024 ** 2

SENTENCE = "The lantern swung above the narrow bridge, and Kaelith counted the stones one by one."


def prose(chars: int) -> wl.FileBudget:
    """A file of ordinary prose this long, at the model's overall rate for prose: about 12 characters a second."""
    return wl.budget_for_seconds(chars / wl.NARRATION_CHARS_PER_SECOND)


def plan(requested, sizes, *, backend="edge", cpus=16, available_gb=16.0, total_gb=32.0):
    memory = None if available_gb is None else wl.MemoryInfo(int(available_gb * GB), int(total_gb * GB))
    return wl.plan_workers(requested, backend, [prose(size) for size in sizes], cpu_count=cpus, memory=memory)


CHAPTER = 20_000      # a 20 KB chapter TXT: about 23 minutes of narration
SHORT = 1_000         # a QA sample: about a minute
VOLUME = 370_000      # a whole light-novel volume (measured): about 8 hours at the model's rate


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
# Memory: the model's per-file peak, the machine's free memory, the queue's own files
# --------------------------------------------------------------------------- #


def test_a_low_memory_laptop_runs_only_what_fits():
    # 3 GB free of 8 GB: 2 GB stays in reserve (25 % of physical), 1 GB for one assembly of about 0.76 GB and three files'
    # working memory of about 0.06 GB each.
    result = plan(8, [60_000] * 8, cpus=8, available_gb=3, total_gb=8)
    assert result.effective == 3
    assert result.log_lines()[1].startswith("Worker limit: memory")


def test_the_same_laptop_runs_more_short_files_because_they_need_less():
    assert plan(8, [SHORT] * 8, cpus=4, available_gb=3, total_gb=8).effective == 4  # processors bind now


def test_whole_volumes_on_a_home_pc_like_machine_run_side_by_side_and_take_turns_to_assemble():
    """Each is budgeted about 4.4 GB at assembly, and 8 GB is usable: never two at once, which is the gate's job. Until
    then they need little, so synthesis stays parallel: "Effective workers: 1" on real books is what this release ends."""
    result = plan(8, [VOLUME] * 8, cpus=16, available_gb=16, total_gb=32)
    assert result.effective == 8
    assert result.log_lines() == ["Requested workers: 8 | Effective workers: 8"]


def test_a_machine_that_could_not_hold_even_one_assembly_runs_one_file_at_a_time():
    result = plan(8, [VOLUME] * 8, cpus=16, available_gb=12, total_gb=32)  # 4 GB usable, about 4.4 GB needed
    assert result.effective == 1
    assert "memory" in result.log_lines()[1] and "estimated" in result.log_lines()[1]


def test_the_largest_assembly_counts_once_and_each_file_its_working_memory():
    budgets = [wl.FileBudget(working=1 * GB, assembly=3 * GB)] * 4 + [wl.FileBudget(working=1 * GB, assembly=5 * GB)]
    memory = wl.MemoryInfo(16 * GB, 32 * GB)  # 8 GB usable
    assert wl.plan_workers(8, "edge", budgets, cpu_count=16, memory=memory).effective == 3  # 5 + 1 + 1 + 1


def test_a_source_holding_a_whole_book_in_one_paragraph_counts_it_all_as_working_memory():
    budgets = [wl.budget_for_seconds(30_000, longest_paragraph_seconds=30_000)] * 8
    memory = wl.MemoryInfo(64 * GB, 128 * GB)  # 32 GB usable; about 4.3 GB each, and one more on top
    assert wl.plan_workers(8, "edge", budgets, cpu_count=16, memory=memory).effective == 6


def test_when_free_memory_is_below_the_reserve_one_file_still_runs():
    result = plan(8, [CHAPTER] * 8, cpus=8, available_gb=1, total_gb=8)
    assert result.effective == 1


@pytest.mark.parametrize("available_gb,total_gb,reserve_gb", [(16, 32, 8), (3, 8, 2), (2, 2, 1), (50, 256, 64)])
def test_the_reserve_is_the_larger_of_a_gibibyte_and_a_quarter_of_memory(available_gb, total_gb, reserve_gb):
    assert wl.memory_reserve(wl.MemoryInfo(available_gb * GB, total_gb * GB)) == reserve_gb * GB


def test_a_large_reserve_is_what_limits_a_machine_with_plenty_in_absolute_terms():
    # 66 GB free of 256 GB is 2 GB usable after the 64 GB reserve: a limit from the reserve, not the free figure.
    assert plan(32, [VOLUME] * 32, cpus=64, available_gb=66, total_gb=256).effective == 1


def test_the_peak_budget_follows_the_measured_slope():
    assert wl.peak_bytes_for_seconds(100) == wl.FILE_BASE_BYTES + 100 * wl.PEAK_BYTES_PER_NARRATION_SECOND
    assert wl.peak_bytes_for_seconds(0) == wl.peak_bytes_for_seconds(-5) == wl.FILE_BASE_BYTES
    assert wl.peak_bytes_for_pcm(48_000 * 100) == wl.peak_bytes_for_seconds(100)


# --------------------------------------------------------------------------- #
# LOW-003: what could not be measured is said whenever it could have mattered
# --------------------------------------------------------------------------- #


def test_unmeasurable_memory_is_said_even_when_the_request_is_honoured():
    """Codex LOW-003: it was printed only when a worker reduction happened to print a line."""
    result = plan(4, [SHORT] * 4, available_gb=None)
    assert result.effective == 4
    assert result.log_lines() == [
        "Requested workers: 4 | Effective workers: 4",
        "Worker note: free memory could not be measured, so 4.0 GB was assumed, and large files assemble one at a time.",
    ]


def test_unmeasurable_memory_and_a_real_reduction_are_stated_apart_without_repeating_either():
    lines = plan(100, [CHAPTER] * 40, cpus=8, available_gb=None).log_lines()
    assert lines[1] == "Worker limit: this computer has 8 logical processors (one file per processor)."
    assert lines[2].startswith("Worker note: free memory could not be measured")
    joined = "\n".join(lines)
    assert joined.count("free memory could not be measured") == 1
    assert joined.count("logical processors") == 1


def test_unmeasurable_memory_gets_a_cautious_assumption_and_says_it_is_one():
    """Eight 80-hour files used to be admitted on a machine that could not say how much memory it has (found by review)."""
    result = plan(100, [VOLUME * 10] * 40, cpus=8, available_gb=None)
    assert result.effective == 1
    assert "it could not be measured, so 4.0 GB was assumed" in result.log_lines()[1]
    assert plan(8, [CHAPTER] * 8, cpus=16, available_gb=None).effective == 8, "ordinary files are not held back"


def test_a_note_about_the_files_survives_when_memory_itself_holds_the_run_to_one():
    """The note was dropped exactly when an estimate it qualifies had forced one worker (found by review)."""
    huge = wl.budget_for_seconds(100_000)
    result = wl.plan_workers(4, "edge", [huge] * 4, cpu_count=8, memory=wl.MemoryInfo(16 * GB, 32 * GB),
                             notes=("1 file(s) could not be read in time",))
    assert result.effective == 1
    assert result.notes == ("1 file(s) could not be read in time",)


@pytest.mark.parametrize("requested,queued", [(1, 8), (8, 1)])
def test_with_one_file_running_memory_could_not_have_mattered_so_nothing_is_said(requested, queued):
    assert plan(requested, [SHORT] * queued, available_gb=None).notes == ()


def test_local_engines_are_not_told_about_edge_memory():
    result = wl.plan_workers(4, "kokoro", [wl.budget_for_seconds(0)] * 4, cpu_count=None, memory=None)
    assert result.notes == ()


def test_notes_about_the_files_are_kept_when_memory_is_known():
    result = wl.plan_workers(2, "edge", [wl.budget_for_seconds(0)] * 2, cpu_count=4, memory=wl.MemoryInfo(16 * GB, 32 * GB),
                             notes=("1 file(s) could not be opened",))
    assert result.log_lines() == ["Requested workers: 2 | Effective workers: 2",
                                  "Worker note: 1 file(s) could not be opened."]


def test_a_reason_is_never_repeated_when_two_limits_are_equal():
    lines = plan(32, [SHORT] * 8, cpus=8).log_lines()
    assert lines[1].count("only 8 files are queued") == 1
    assert lines[1].count("logical processors") == 1


# --------------------------------------------------------------------------- #
# Local engines never run more than one file
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("backend,name", [("kokoro", "Kokoro"), ("chatterbox", "Chatterbox Turbo"),
                                          ("qwen3", "Qwen3-TTS"), ("omnivoice", "OmniVoice")])  # v0.8.0: OmniVoice
@pytest.mark.parametrize("requested", [1, 2, 8, 100])
def test_local_engines_stay_at_one_file_on_any_machine(backend, name, requested):
    result = plan(requested, [SHORT] * 10, backend=backend, cpus=64, available_gb=500, total_gb=512)
    assert result.effective == 1
    if requested > 1:
        assert result.log_lines()[1] == f"Worker limit: {name} converts one file at a time."


@pytest.mark.parametrize("backend", ["kokoro", "chatterbox", "qwen3", "omnivoice"])
def test_a_local_engine_reads_nothing_to_plan(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(wl, "estimate_text_seconds", lambda *a, **k: pytest.fail("no reason to read a local run's text"))
    monkeypatch.setattr(wl, "memory_info", lambda: pytest.fail("no reason to read memory"))
    source = tmp_path / "book.txt"
    source.write_text(SENTENCE, encoding="utf-8")
    assert wl.plan_for_sources(8, backend, [source]).effective == 1


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


@pytest.mark.parametrize("cpus", [0, -1])
def test_a_nonsense_processor_count_falls_back_to_four(cpus):
    assert plan(100, [SHORT] * 20, cpus=cpus).effective == 4


# --------------------------------------------------------------------------- #
# The model: real text, real pauses. Every expectation below is an upper bound on a measured or computed length.
# --------------------------------------------------------------------------- #


DEFAULTS = wl.NarrationSettings()


def direct(text: str, **settings) -> float:
    return wl.estimate_text_seconds(text, direct=True, settings=wl.NarrationSettings(**settings))


def folder(text: str, **settings) -> float:
    return wl.estimate_text_seconds(text, direct=False, settings=wl.NarrationSettings(**settings))


def test_the_estimator_keeps_the_engine_constants():
    """Copied so this module stays standard-library only; kept equal here."""
    from tts import batch_convert
    from tts.epub2tts_edge import epub2tts_edge as engine

    assert wl.COMMA_PAUSE_MS == engine.COMMA_PAUSE_MS
    assert wl.ELLIPSIS_PAUSE_MS == engine.ELLIPSIS_PAUSE_MS
    assert wl.EM_DASH_PAUSE_MS == engine.EM_DASH_PAUSE_MS
    assert wl.DEFAULT_SENTENCE_PAUSE_MS == engine.DEFAULT_SENTENCE_PAUSE_MS
    assert wl.DEFAULT_PARAGRAPH_PAUSE_MS == engine.DEFAULT_PARAGRAPH_PAUSE_MS
    assert wl.DEFAULT_TITLE_PAUSE_MS == engine.DEFAULT_TITLE_PAUSE_MS
    assert wl.DEFAULT_CHAPTER_PAUSE_MS == engine.DEFAULT_CHAPTER_PAUSE_MS
    assert wl.FOLDER_CHUNK_CHARS == batch_convert.CHUNK_TARGET
    assert wl.FOLDER_CHUNK_PAUSE_SECONDS == batch_convert.CHUNK_PAUSE_MS / 1000


def test_ten_tiny_paragraphs_are_no_longer_estimated_below_their_own_pauses():
    """Codex HIGH-002: "A." x 10 estimated 2.5 s, against 8.649 s observed with default pauses."""
    text = "\n\n".join(["A."] * 10) + "\n"
    estimated = direct(text)
    assert estimated >= 8.649
    assert estimated >= 9 * wl.DEFAULT_PARAGRAPH_PAUSE_MS / 1000 + 10 * 0.25  # the pauses plus the shortest real "A"
    assert estimated < 20, "an upper estimate, not a wild one"


@pytest.mark.parametrize("count", [1_000, 100_000])
def test_very_large_pause_counts_scale_with_the_pauses(count):
    text = "\n\n".join(["A."] * count)
    assert direct(text) >= count * wl.DEFAULT_PARAGRAPH_PAUSE_MS / 1000


def test_sentence_pauses_within_a_paragraph_are_counted():
    one_line = direct(" ".join(["Yes."] * 100))
    assert one_line >= 99 * wl.DEFAULT_SENTENCE_PAUSE_MS / 1000 + wl.DEFAULT_PARAGRAPH_PAUSE_MS / 1000


def test_comma_ellipsis_and_dash_pauses_are_counted():
    assert direct("a, b, c, d, e, f.") >= 5 * wl.COMMA_PAUSE_MS / 1000
    assert direct("a... b... c... d.") >= 3 * wl.ELLIPSIS_PAUSE_MS / 1000
    assert direct("a — b — c -- d.") >= 3 * wl.EM_DASH_PAUSE_MS / 1000


def test_headings_add_their_title_clip_and_pause_and_chapters_their_pause():
    book = "# One\n\nBody.\n\n# Two\n\nBody.\n\n# Three\n\nBody.\n"
    body_only = "Body.\n\nBody.\n\nBody.\n"
    extra = direct(book) - direct(body_only)
    assert extra >= 3 * wl.DEFAULT_TITLE_PAUSE_MS / 1000 + 2 * wl.DEFAULT_CHAPTER_PAUSE_MS / 1000


def test_the_frozen_pause_settings_are_what_count():
    text = "\n\n".join(["A."] * 100)
    assert direct(text, paragraph_pause_ms=5000) - direct(text, paragraph_pause_ms=0) == pytest.approx(500)
    run = wl.NarrationSettings.for_run({"sentencepause": 1, "paragraphpause": 2, "title_trailing_pause": 3,
                                        "chapter_trailing_pause": 4, "trim_tts_padding": False}, "-10%", None)
    assert (run.sentence_pause_ms, run.paragraph_pause_ms, run.title_pause_ms, run.chapter_pause_ms) == (1, 2, 3, 4)
    assert run.trim_padding is False and run.rate == "-10%"


def test_untrimmed_clips_carry_the_services_padding():
    text = "\n\n".join(["A."] * 10)
    assert direct(text, trim_padding=False) - direct(text, trim_padding=True) == pytest.approx(10 * wl.CLIP_PADDING_SECONDS)


def test_numbers_and_symbols_last_much_longer_than_their_characters():
    """Measured: "3.14159265358979" took up to 6.6 s, nine spoken symbols up to 4.6 s; 16 and 17 characters of prose
    would be about a second."""
    assert folder("3.14159265358979") >= 6.6
    assert folder("% & @ # $ + = / *") >= 4.6
    assert folder("A B C D E F G H I J") >= 3.3


def test_ordinary_prose_stays_within_a_margin_of_what_was_measured():
    """The prose sentence, 172 characters without punctuation, measured at most 10.0 s in five voices."""
    prose = ("The lantern swung above the narrow bridge and Kaelith counted the stones one by one until the river below "
             "fell quiet and the night closed around her small and steady flame.")
    assert 10.0 <= folder(prose) <= 20.0
    # 14.7-15.1 characters per second over real direct-route narrations, pauses included (plan F14).
    book = "\n\n".join([f"{SENTENCE} {SENTENCE}"] * 200)
    seconds = direct(book)
    assert len(book) / 15.1 <= seconds <= len(book) / 15.1 * 2


def test_slow_narration_takes_longer_on_the_folder_route_and_is_ignored_on_the_direct_route():
    text = SENTENCE * 20
    assert folder(text, rate="-50%") == pytest.approx((folder(text) - 0.05) * 2 + 0.05)
    assert folder(text, rate="-50%") > folder(text) > folder(text, rate="+50%")
    assert direct(text, rate="-50%") == direct(text), "the direct route sends no rate"


@pytest.mark.parametrize("rate,speed", [("+0%", 1.0), ("-50%", 0.5), ("+100%", 2.0), ("-99%", 0.1), ("-100%", 0.1),
                                        ("garbage", 1.0), ("", 1.0), ("10", 1.0), (" -25% ", 0.75)])
def test_the_rate_is_read_as_a_speed(rate, speed):
    assert wl.NarrationSettings(rate=rate).speed() == pytest.approx(speed)


def test_empty_or_structure_free_text_is_an_estimate_of_almost_nothing():
    assert direct("") == 0
    assert folder("") >= 0
    assert direct("   \n\n  ") == pytest.approx(0, abs=1)


def test_the_folder_route_has_no_inserted_pauses_but_the_service_has_its_own():
    """Measured on the folder route: ten sentences of "Kaelith." took up to 12.3 s."""
    assert folder(" ".join(["Kaelith."] * 10)) >= 12.3
    assert folder(", ".join(["Kaelith"] * 10)) >= 7.8
    assert folder("... ".join(["Kaelith"] * 10)) >= 13.3
    assert folder("\n\n".join(["A."] * 10)) >= 10.1


@pytest.mark.parametrize("text", [
    "." * 2_000_000 + "x",
    "!" * 2_000_000 + "x",
    "." * 1_000_000 + " " * 1_000_000 + "x",
    ". " * 1_000_000 + "x",
    "." + '"' * 2_000_000 + "x",
    "-" * 2_000_000 + "\n",
    "#" * 2_000_000,
    "#\n" * 1_000_000,
    " " * 2_000_000,
    "\r" * 2_000_000,
    ", " * 1_000_000,
], ids=["dots", "bangs", "dots-spaces", "dot-space", "quotes", "dashes", "hashes", "hash-lines", "spaces", "returns",
        "commas"])
def test_no_text_makes_planning_slow(text):
    """A pattern that backtracks costs the square of a run's length: 2 MB of dots would take hours, not milliseconds.
    Found by review, not by a user, and this is the bound: planning has no way to interrupt a running pattern."""
    started = time.perf_counter()
    direct(text)
    folder(text)
    assert time.perf_counter() - started < 15


def test_a_run_of_dots_is_still_counted_at_the_end_of_a_line():
    assert wl._count(wl._LINE_END, "Yes...\nNo!\nMaybe?\" \nA.b\nC. D") == 3


def test_sizing_a_large_text_is_quick():
    text = (SENTENCE + "\n\n") * 40_000  # 3.5 million characters: about 80 hours of narration
    started = time.perf_counter()
    direct(text)
    assert time.perf_counter() - started < 15, "linear, and small next to narrating it"


# --------------------------------------------------------------------------- #
# Real sources
# --------------------------------------------------------------------------- #


GIB16 = wl.MemoryInfo(8 * GB, 16 * GB)


def estimated(source, settings=DEFAULTS, *, in_time=True):
    """(seconds, basis) for one source."""
    estimate = wl._estimate_source(source, settings, lambda: in_time)
    return estimate.seconds, estimate.basis


def machine(monkeypatch, *, cpus=16, memory=wl.MemoryInfo(64 * GB, 128 * GB)):
    monkeypatch.setattr(wl, "logical_cpus", lambda: cpus)
    monkeypatch.setattr(wl, "memory_info", lambda: memory)


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def make_pdf(path, pages):
    from tts import pdf_extractor

    doc = pdf_extractor.fitz.open()
    for text, fontsize in pages:
        page = doc.new_page(width=1190, height=1684)
        page.insert_textbox(page.rect + (18, 18, -18, -18), text, fontsize=fontsize)
    doc.save(str(path))
    doc.close()
    return path


def pause_heavy(path, paragraphs):
    """A file of nothing but tiny paragraphs. Bytes, so its size is the same on every platform."""
    path.write_bytes(b"A.\n\n" * paragraphs)
    return path


def test_eight_large_pause_heavy_files_are_held_to_one_worker_on_16_gib(tmp_path, monkeypatch):
    """Codex HIGH-002: two were admitted on a simulated 16 GiB machine, though each file's paragraph pauses alone were
    more than its whole budget. Each file here is 160 KB: 40,000 paragraphs, so 34,000 s of pauses alone."""
    machine(monkeypatch, memory=GIB16)
    sources = [pause_heavy(tmp_path / f"{i}.txt", 40_000) for i in range(8)]  # about 7 GiB to assemble each, 4 GiB usable
    result = wl.plan_for_sources(8, "edge", [wl.QueuedSource(path, direct=True) for path in sources])
    assert result.effective == 1
    assert "memory" in result.log_lines()[1]
    # The old rule, characters / 12, budgeted each file below 2 GiB and so admitted two on the 4 GiB usable here.
    old_budget = wl.peak_bytes_for_seconds(160_000 / wl.NARRATION_CHARS_PER_SECOND)
    assert 2 * old_budget <= GIB16.available - wl.memory_reserve(GIB16)
    assert wl.budget_for_seconds(estimated(wl.QueuedSource(sources[0]))[0]).assembly > 3 * old_budget


def test_a_smaller_pause_heavy_file_still_runs_side_by_side_when_one_assembly_fits(tmp_path, monkeypatch):
    machine(monkeypatch, memory=GIB16)
    sources = [pause_heavy(tmp_path / f"{i}.txt", 10_000) for i in range(8)]
    assert wl.plan_for_sources(8, "edge", sources).effective == 8, "4 GiB usable, about 1.8 GiB to assemble, in turns"


def test_eight_files_with_no_paragraph_breaks_are_held_back_though_their_assembly_alone_would_fit(tmp_path, monkeypatch):
    """Their whole narration is in memory during synthesis, where no gate can help (found by review)."""
    machine(monkeypatch, memory=wl.MemoryInfo(16 * GB, 32 * GB))  # 8 GiB usable
    sources = [write(tmp_path / f"{i}.txt", SENTENCE * 1_000) for i in range(8)]  # about 1.2 GiB each, in memory all along
    assert wl.plan_for_sources(8, "edge", sources).effective == 5, "one assembly on top of five files' paragraphs"
    broken_up = [write(tmp_path / f"b{i}.txt", (SENTENCE + "\n\n") * 1_000) for i in range(8)]
    assert wl.plan_for_sources(8, "edge", broken_up).effective == 8


def test_the_same_pauses_matter_less_when_the_run_has_short_ones(tmp_path, monkeypatch):
    machine(monkeypatch, memory=GIB16)
    source = pause_heavy(tmp_path / "a.txt", 30_000)
    long_pause = wl.NarrationSettings(paragraph_pause_ms=850)
    no_pause = wl.NarrationSettings(paragraph_pause_ms=0)
    assert (wl.plan_for_sources(2, "edge", [wl.QueuedSource(source)] * 2, settings=long_pause).effective
            < wl.plan_for_sources(2, "edge", [wl.QueuedSource(source)] * 2, settings=no_pause).effective)


def test_ordinary_files_on_a_home_pc_like_machine_admit_eight_workers(tmp_path, monkeypatch):
    """The eight 1-hour chapters a person would really queue: the normal 8-worker capability, unreduced."""
    machine(monkeypatch, cpus=16, memory=wl.MemoryInfo(20 * GB, 32 * GB))
    chapter = "# Chapter\n\n" + "\n\n".join([f"{SENTENCE} {SENTENCE}"] * 300)
    sources = [wl.QueuedSource(write(tmp_path / f"{i}.txt", chapter)) for i in range(8)]
    result = wl.plan_for_sources(8, "edge", sources)
    assert result.effective == 8
    assert result.log_lines() == ["Requested workers: 8 | Effective workers: 8"]


def test_each_file_is_counted_by_its_own_route(tmp_path, monkeypatch):
    """One long line: in memory until it is whole on the direct route; chunks on disk on the folder route."""
    machine(monkeypatch)  # 32 GiB usable
    path = write(tmp_path / "a.txt", "Word. " * 50_000)
    assert wl.plan_for_sources(8, "edge", [wl.QueuedSource(path, direct=True)] * 8).effective == 2
    assert wl.plan_for_sources(8, "edge", [wl.QueuedSource(path, direct=False)] * 8).effective == 8
    mixed = [wl.QueuedSource(path, direct=False)] * 7 + [wl.QueuedSource(path, direct=True)]
    assert wl.plan_for_sources(8, "edge", mixed).effective == 8


def test_a_bare_path_is_sized_as_the_longer_direct_route(tmp_path, monkeypatch):
    machine(monkeypatch, memory=GIB16)
    path = pause_heavy(tmp_path / "a.txt", 40_000)
    assert wl.plan_for_sources(8, "edge", [path] * 8).effective == 1


def test_speech_preparation_expansion_is_seen_when_it_is_on(tmp_path):
    from tts.speech import pipeline

    snapshot = pipeline.build_snapshot(pipeline.SETTING_V1, user_dir=None)
    assert snapshot.enabled
    text = "It cost $1,234,567.89 in 1999 and Dr. Smith paid 3/4 of it.\n" * 50
    prepared = wl._prepared(text, True, wl.NarrationSettings(speech_prep=snapshot))
    assert len(prepared) > len(text), "the expanded text is what gets sized"
    source = write(tmp_path / "a.txt", text)
    settings = wl.NarrationSettings(speech_prep=snapshot)
    on, basis = estimated(wl.QueuedSource(source), settings)
    assert basis == "text"
    # What is sized is the text the run will speak, exactly, not the text on disk.
    spoken = wl._prepared(source.read_text(encoding="utf-8"), True, settings)
    assert on == pytest.approx(wl.estimate_text_seconds(spoken, settings=settings))
    assert on != estimated(wl.QueuedSource(source))[0]


def test_speech_preparation_off_never_runs_it(tmp_path, monkeypatch):
    from tts.speech import pipeline

    monkeypatch.setattr(pipeline, "normalize", lambda *a, **k: pytest.fail("off means off"))
    assert wl._prepared("text", True, wl.NarrationSettings(speech_prep=pipeline.OFF)) == "text"
    assert wl._prepared("text", True, wl.NarrationSettings()) == "text"


def test_speech_preparation_on_an_enormous_text_falls_back_to_the_digit_weights(monkeypatch):
    from tts.speech import pipeline

    snapshot = pipeline.build_snapshot(pipeline.SETTING_V1, user_dir=None)
    monkeypatch.setattr(wl, "PREPARE_SCAN_CHARS", 10)
    monkeypatch.setattr(pipeline, "prepare", lambda *a, **k: pytest.fail("beyond the bound"))
    assert wl._prepared("x" * 11, True, wl.NarrationSettings(speech_prep=snapshot)) == "x" * 11


def test_a_dense_one_page_pdf_is_sized_by_its_text_not_by_its_page_count(tmp_path, monkeypatch):
    """Codex HIGH-002: a one-page PDF held 11,399 characters against an assumed 3,000 per page."""
    path = make_pdf(tmp_path / "dense.pdf", [("Dense words in a line of text. " * 500, 5)])
    seconds, basis = estimated(wl.QueuedSource(path))
    from tts import pdf_extractor

    extracted = pdf_extractor.extract_text_from_pdf(str(path))
    assert len(extracted) > 10_000, "the fixture is the dense case"
    assert basis == "text"
    assert seconds >= len(extracted) / wl.NARRATION_CHARS_PER_SECOND
    assert seconds > 3_000 / wl.NARRATION_CHARS_PER_SECOND * 3


def test_a_long_pdf_is_read_at_a_bounded_number_of_pages_and_scaled_up(tmp_path, monkeypatch):
    monkeypatch.setattr(wl, "PDF_SCAN_PAGES", 2)
    path = make_pdf(tmp_path / "long.pdf", [(f"Words on page {i}. " * 50, 10) for i in range(8)])
    seconds, basis = estimated(wl.QueuedSource(path))
    monkeypatch.setattr(wl, "PDF_SCAN_PAGES", 400)
    whole, whole_basis = estimated(wl.QueuedSource(path))
    assert (basis, whole_basis) == ("sampled", "text")
    assert seconds == pytest.approx(whole, rel=0.3)


def test_the_page_sample_spreads_through_the_document(tmp_path):
    from tts import pdf_extractor

    path = make_pdf(tmp_path / "p.pdf", [(f"Marker{i} words here.", 12) for i in range(10)])
    pages, read, text = pdf_extractor.pdf_text_sample(str(path), 3)
    assert (pages, read) == (10, 3)
    assert "Marker0" in text and "Marker3" in text and "Marker6" in text
    assert pdf_extractor.pdf_text_sample(str(path), 100)[1] == 10


def test_pdf_sizing_goes_through_the_pymupdf_lock(tmp_path, monkeypatch):
    """PyMuPDF is not thread-safe: a sizing call waits for a conversion's extraction like any other."""
    from tts import pdf_extractor

    path = make_pdf(tmp_path / "p.pdf", [("Some words.", 12)])
    with pdf_extractor._PYMUPDF_LOCK:
        finished = threading.Event()
        worker = threading.Thread(target=lambda: (pdf_extractor.pdf_text_sample(str(path), 10), finished.set()))
        worker.start()
        assert not finished.wait(0.2), "it must wait for the lock"
    worker.join(30)
    assert finished.is_set()


@pytest.mark.parametrize("name,content", [("broken.pdf", b"%PDF-1.4 not really" * 10), ("empty.pdf", b"")])
def test_a_malformed_pdf_is_unreadable_and_counts_as_nothing(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    assert estimated(wl.QueuedSource(path)) == (0.0, "unreadable")


def test_an_unexpected_error_while_sizing_never_costs_the_run(tmp_path, monkeypatch):
    machine(monkeypatch)
    path = write(tmp_path / "a.txt", "words")
    monkeypatch.setattr(wl, "estimate_text_seconds", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("a defect")))
    result = wl.plan_for_sources(2, "edge", [path, path])
    assert result.effective == 2
    assert "2 file(s) could not be opened" in result.log_lines()[1]


def test_a_textless_pdf_needs_no_budget(tmp_path):
    path = make_pdf(tmp_path / "scan.pdf", [("", 12)])
    seconds, basis = estimated(wl.QueuedSource(path))
    assert seconds == 0 and basis == "text"


def test_an_empty_txt_needs_no_budget(tmp_path):
    path = write(tmp_path / "empty.txt", "")
    assert estimated(wl.QueuedSource(path)) == (0.0, "text")


def test_a_missing_source_counts_as_nothing_and_the_log_says_so(tmp_path, monkeypatch):
    machine(monkeypatch)
    good = write(tmp_path / "good.txt", SENTENCE)
    result = wl.plan_for_sources(2, "edge", [good, tmp_path / "gone.txt"])
    assert result.effective == 2
    note = result.log_lines()[1]
    assert note.startswith("Worker note: 1 file(s) could not be opened")
    assert "checked again before it is assembled" in note


def test_an_inaccessible_txt_is_sized_from_its_length(tmp_path, monkeypatch):
    path = write(tmp_path / "locked.txt", "x" * 8_000)
    real_open = open

    def refuse(file, *args, **kwargs):
        if str(file) == str(path):
            raise PermissionError(13, "simulated: in use")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", refuse)
    source = wl.QueuedSource(path)
    seconds, basis = estimated(source)
    assert basis == "length"
    assert seconds == wl._rough_seconds(8_000, source, DEFAULTS)


def test_a_length_alone_still_counts_the_runs_frozen_pauses(tmp_path):
    """It was 2.5 x low at default pauses and 10.8 x low at a 5 s paragraph pause (found by review)."""
    source = wl.QueuedSource(tmp_path / "a.txt")
    long_pause = wl._rough_seconds(40_000, source, wl.NarrationSettings(paragraph_pause_ms=5000))
    assert long_pause - wl._rough_seconds(40_000, source, wl.NarrationSettings(paragraph_pause_ms=0)) == pytest.approx(5000)
    slow = wl._rough_seconds(40_000, wl.QueuedSource(tmp_path / "a.txt", direct=False), wl.NarrationSettings(rate="-50%"))
    assert slow == pytest.approx(2 * 40_000 / wl.ROUGH_CHARS_PER_SECOND)


def test_old_mac_line_endings_are_lines_here_as_they_are_to_the_engine(tmp_path):
    """The engine's text mode reads a lone CR as a line end; a bytes read here saw one giant line (found by review)."""
    crlf, cr, lf = tmp_path / "crlf.txt", tmp_path / "cr.txt", tmp_path / "lf.txt"
    crlf.write_bytes(b"Item one\r\n" * 5_000)
    cr.write_bytes(b"Item one\r" * 5_000)
    lf.write_bytes(b"Item one\n" * 5_000)
    assert estimated(wl.QueuedSource(cr)) == estimated(wl.QueuedSource(lf)) == estimated(wl.QueuedSource(crlf))


def test_text_that_will_not_decode_still_has_a_length_to_count(tmp_path):
    path = tmp_path / "latin1.txt"
    path.write_bytes(("Déjà vu. " * 100).encode("latin-1"))
    seconds, basis = estimated(wl.QueuedSource(path))
    assert basis == "text" and seconds > 10


def test_a_bom_is_not_counted_as_text(tmp_path):
    path = tmp_path / "bom.txt"
    path.write_bytes(b"\xef\xbb\xbf# One\n\nBody.\n")
    text, scale = wl._read_for_sizing(path, path.stat().st_size)
    assert text.startswith("# One") and scale == 1.0


def test_an_enormous_txt_is_read_only_in_part_and_scaled_up(tmp_path, monkeypatch):
    monkeypatch.setattr(wl, "TXT_SCAN_BYTES", 40_000)
    path = pause_heavy(tmp_path / "huge.txt", 100_000)  # 400,000 bytes
    seconds, basis = estimated(wl.QueuedSource(path))
    assert basis == "sampled"
    assert seconds >= 100_000 * wl.DEFAULT_PARAGRAPH_PAUSE_MS / 1000 * 0.9


def test_a_slow_rate_raises_the_folder_estimate_of_a_real_file(tmp_path):
    path = write(tmp_path / "a.txt", SENTENCE * 10)
    normal, _ = estimated(wl.QueuedSource(path, direct=False))
    slow, _ = estimated(wl.QueuedSource(path, direct=False), wl.NarrationSettings(rate="-50%"))
    assert slow > normal * 1.8


# --------------------------------------------------------------------------- #
# Planning is bounded
# --------------------------------------------------------------------------- #


def test_out_of_time_every_remaining_source_is_sized_from_its_length(tmp_path, monkeypatch):
    machine(monkeypatch)
    sources = [write(tmp_path / f"{i}.txt", "x" * 4_000) for i in range(4)]
    now = [0.0]
    read = []
    real = wl._read_for_sizing

    def counting(path, size):
        read.append(path)
        now[0] = wl.PLAN_SCAN_SECONDS + 1  # the first file used up all the time there was
        return real(path, size)

    monkeypatch.setattr(wl, "_read_for_sizing", counting)
    result = wl.plan_for_sources(4, "edge", sources, clock=lambda: now[0])

    assert len(read) == 1, "the time limit stopped the reading, not the planning"
    assert result.effective == 4
    assert "3 file(s) could not be read in time" in result.log_lines()[1]


def test_out_of_time_a_pdf_is_not_opened_at_all(tmp_path, monkeypatch):
    from tts import pdf_extractor

    path = make_pdf(tmp_path / "p.pdf", [("Some words.", 12)] * 3)
    monkeypatch.setattr(pdf_extractor, "pdf_text_sample", lambda *a, **k: pytest.fail("out of time"))
    source = wl.QueuedSource(path)
    seconds, basis = estimated(source, in_time=False)
    assert basis == "length"
    assert seconds == wl._rough_seconds(path.stat().st_size, source, DEFAULTS)


def test_a_cancelled_run_looks_at_no_more_files(tmp_path, monkeypatch):
    machine(monkeypatch)
    sources = [write(tmp_path / f"{i}.txt", "words") for i in range(4)]
    monkeypatch.setattr(wl, "_estimate_source", lambda *a, **k: pytest.fail("cancelled"))
    assert wl.plan_for_sources(4, "edge", sources, should_stop=lambda: True).effective == 4


@pytest.mark.parametrize("stop_with", ["deadline", "cancel"])
def test_a_long_pdf_stops_being_read_between_its_pages(tmp_path, monkeypatch, stop_with):
    """The bound used to be checked only between files: 49 s on one 400-page vector PDF, Cancel ignored (found by review)."""
    machine(monkeypatch)
    path = make_pdf(tmp_path / "long.pdf", [(f"Words on page {i}. " * 20, 10) for i in range(6)])
    from tts import pdf_extractor

    # Counted where a page is read. (Until v0.7.2 Phase 9 this counted the cleaning, which then ran page by page; the pages
    # are now cleaned together once they have been read, because what is a page number is decided across pages.)
    pages_read = []
    real_read = pdf_extractor._read_page

    def read_page(page, index, **limits):
        pages_read.append(1)
        return real_read(page, index, **limits)

    monkeypatch.setattr(pdf_extractor, "_read_page", read_page)
    now = [0.0]
    stopped = [False]

    def after_two_pages():
        if len(pages_read) >= 2:
            if stop_with == "deadline":
                now[0] = wl.PLAN_SCAN_SECONDS + 1
            else:
                stopped[0] = True
        return now[0]

    result = wl.plan_for_sources(2, "edge", [path, path], clock=after_two_pages, should_stop=lambda: stopped[0])
    assert len(pages_read) == 2, "the rest of the first file, and all of the second, were never read"
    assert result.effective == 2


def test_stopping_before_any_page_falls_back_to_the_length(tmp_path):
    path = make_pdf(tmp_path / "p.pdf", [("Some words.", 12)] * 3)
    answers = iter([True, False])  # yes to starting; no to the first page
    estimate = wl._estimate_source(wl.QueuedSource(path), DEFAULTS, lambda: next(answers))
    assert estimate.basis == "length"


def test_an_abnormal_page_is_not_given_the_conversions_costly_cleaning(tmp_path, monkeypatch):
    """Its cost grows with the square of the lines: 57 s and a 12 s freeze on one 108 KB page (found by review)."""
    from tts import pdf_extractor

    monkeypatch.setattr(pdf_extractor, "SIZING_CLEAN_CHARS", 500)
    path = make_pdf(tmp_path / "abnormal.pdf", [("abc def ghi " * 200, 6)])
    monkeypatch.setattr(pdf_extractor, "_clean_page_text", lambda raw, furniture=(): pytest.fail("beyond the limit"))
    monkeypatch.setattr(pdf_extractor, "_edge_lines", lambda *a, **k: pytest.fail("beyond the limit: not measured either"))
    pages, read, text = pdf_extractor.pdf_text_sample(str(path), 10)
    assert (pages, read) == (1, 1)
    assert text.count("abc") == 200
    assert "\n" not in text.strip(), "its soft line breaks are not counted as paragraphs"


def test_an_ordinary_dense_page_is_cleaned_as_a_conversion_cleans_it(tmp_path, monkeypatch):
    from tts import pdf_extractor

    assert pdf_extractor.SIZING_CLEAN_CHARS >= 16_000, "the densest page anyone has reported is 15,499 characters"
    path = make_pdf(tmp_path / "dense.pdf", [("Dense words in a line of text. " * 500, 5)])
    cleaned = []
    real_clean = pdf_extractor._clean_page_text
    monkeypatch.setattr(pdf_extractor, "_clean_page_text",
                        lambda raw, furniture=(): (cleaned.append(1), real_clean(raw, furniture))[1])
    pdf_extractor.pdf_text_sample(str(path), 10)
    assert cleaned == [1]


@pytest.mark.parametrize("requested,queued", [(1, 4), (8, 1)])
def test_with_one_file_at_a_time_nothing_is_read_at_all(tmp_path, monkeypatch, requested, queued):
    machine(monkeypatch)
    sources = [write(tmp_path / f"{i}.txt", "words") for i in range(queued)]
    monkeypatch.setattr(wl, "_estimate_source", lambda *a, **k: pytest.fail("the answer can only be one"))
    assert wl.plan_for_sources(requested, "edge", sources).effective == 1


def test_a_file_too_long_for_one_mp3_is_mentioned_before_the_hours_of_synthesis(tmp_path, monkeypatch):
    machine(monkeypatch)
    long_file = pause_heavy(tmp_path / "long.txt", 100_000)
    assert "may be too long for one MP3" in "\n".join(wl.plan_for_sources(2, "edge", [long_file, long_file]).log_lines())
    short = write(tmp_path / "short.txt", SENTENCE)
    assert "too long" not in "\n".join(wl.plan_for_sources(2, "edge", [short, short]).log_lines())


def test_a_sampled_source_is_disclosed(tmp_path, monkeypatch):
    machine(monkeypatch)
    monkeypatch.setattr(wl, "TXT_SCAN_BYTES", 10)
    path = write(tmp_path / "a.txt", "words " * 100)
    assert "2 very long file(s) were sized from a sample" in wl.plan_for_sources(2, "edge", [path, path]).log_lines()[1]


def test_planning_a_large_real_queue_stays_within_its_time_bound(tmp_path, monkeypatch):
    machine(monkeypatch)
    sources = [write(tmp_path / f"{i}.txt", (SENTENCE + "\n\n") * 500) for i in range(200)]
    started = time.perf_counter()
    wl.plan_for_sources(100, "edge", sources)
    assert time.perf_counter() - started < wl.PLAN_SCAN_SECONDS + 15


# --------------------------------------------------------------------------- #
# The runtime gate: real sizes, immediately before assembly
# --------------------------------------------------------------------------- #


def eventually(predicate, timeout=30.0):
    """Wait for something another thread is about to do; a slow machine makes this slower, not wrong."""
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "it never happened"
        time.sleep(0.005)


class Machine:
    """A memory reading a test can change."""

    def __init__(self, available_gb=16, total_gb=32):
        self.info = wl.MemoryInfo(int(available_gb * GB), int(total_gb * GB))

    def __call__(self):
        return self.info


def enter(gate, need, entered, release, *, cancel_check=None, note=None, errors=None):
    def body():
        try:
            with gate.reserve(need, cancel_check=cancel_check, note=note):
                entered.set()
                release.wait(30)
        except BaseException as exc:  # noqa: BLE001 - recorded for the assertion
            if errors is not None:
                errors.append(exc)

    thread = threading.Thread(target=body)
    thread.start()
    return thread


def test_assemblies_that_fit_overlap():
    gate = wl.AssemblyGate(Machine(16, 32), poll_seconds=0.01)  # 8 GB usable
    first, second, release = threading.Event(), threading.Event(), threading.Event()
    threads = [enter(gate, 3 * GB, first, release), enter(gate, 3 * GB, second, release)]
    assert first.wait(5) and second.wait(5)
    release.set()
    for thread in threads:
        thread.join(5)


def test_an_assembly_that_would_not_fit_waits_for_the_memory_and_says_why():
    gate = wl.AssemblyGate(Machine(16, 32), poll_seconds=0.01)
    first, second, release_first, release_second = (threading.Event() for _ in range(4))
    notes: list[str] = []
    threads = [enter(gate, 6 * GB, first, release_first)]
    assert first.wait(5)
    threads.append(enter(gate, 6 * GB, second, release_second, note=notes.append))
    assert not second.wait(0.2), "the two together exceed what was usable"
    eventually(lambda: notes)
    assert len(notes) == 1 and "Waiting for memory" in notes[0] and "Synthesis of other files continues" in notes[0]

    release_first.set()
    assert second.wait(5), "it runs as soon as the memory is back"
    release_second.set()
    for thread in threads:
        thread.join(5)


def test_a_lone_assembly_that_does_not_fit_is_never_held_in_memory():
    """Codex HIGH-002B: being the only assembly says nothing about what else is using the memory. It still finishes: on
    disk, not by being refused. ``test_assembly_on_disk`` proves that route gives the same file."""
    gate = wl.AssemblyGate(Machine(2, 32))  # free memory already below the reserve
    with gate.reserve(100 * GB) as in_memory:
        assert in_memory is False
        assert gate._in_use == wl.DISK_ASSEMBLY_BYTES, "and what it reserves is what that route really needs"
    assert gate._in_use == 0


def test_a_lone_assembly_too_large_for_free_memory_goes_to_disk_and_says_so():
    gate = wl.AssemblyGate(Machine(10, 32))  # 2 GB usable after the 8 GB reserve
    notes: list[str] = []
    with gate.reserve(3 * GB, note=notes.append) as in_memory:
        assert in_memory is False
        assert len(notes) == 1 and "more than this computer has free" in notes[0] and "on disk" in notes[0]
    notes.clear()
    with gate.reserve(1 * GB, note=notes.append) as in_memory:
        assert in_memory is True
        assert notes == []


def test_a_note_that_fails_neither_stops_the_work_nor_leaks_the_reservation():
    """Reading a closed pipe's print, for one: the budget must come back, or a later assembly waits forever (found by
    review). And a log that cannot be written, most likely out of memory itself, is no reason to lose a narration (R2)."""
    gate = wl.AssemblyGate(Machine(10, 32))

    def broken_note(_message):
        raise BrokenPipeError

    entered = False
    with gate.reserve(3 * GB, note=broken_note) as in_memory:
        entered = True
        assert in_memory is False
    assert entered and gate._in_use == 0 and gate._on_disk == 0


def test_a_lone_assembly_where_memory_cannot_be_read_says_nothing_it_cannot_know():
    gate = wl.AssemblyGate(lambda: None)
    notes: list[str] = []
    with gate.reserve(100 * GB, note=notes.append) as in_memory:
        assert in_memory is False, "too large for the amount assumed when nothing can be read"
        assert len(notes) == 1 and "cannot be read" in notes[0] and "has free" not in notes[0]
    notes.clear()
    with gate.reserve(wl.UNKNOWN_MEMORY_ASSEMBLY_BYTES, note=notes.append) as in_memory:
        assert in_memory is True and notes == []


def test_the_gate_is_first_come_first_served():
    gate = wl.AssemblyGate(Machine(16, 32), poll_seconds=0.01)
    big_entered, huge_entered, small_entered = threading.Event(), threading.Event(), threading.Event()
    release = threading.Event()
    threads = [enter(gate, 6 * GB, big_entered, release)]
    assert big_entered.wait(5)
    huge_release, small_release = threading.Event(), threading.Event()
    threads.append(enter(gate, 7 * GB, huge_entered, huge_release))
    eventually(lambda: len(gate._queue) == 1)  # the large one is waiting
    threads.append(enter(gate, 1 * GB, small_entered, small_release))
    assert not small_entered.wait(0.2), "a small one that would fit does not overtake the waiting large one"
    release.set()
    assert huge_entered.wait(5)
    assert small_entered.wait(5)
    huge_release.set()
    small_release.set()
    for thread in threads:
        thread.join(5)


def test_a_cancel_while_waiting_raises_and_gives_up_its_place():
    gate = wl.AssemblyGate(Machine(16, 32), poll_seconds=0.01)
    first, release = threading.Event(), threading.Event()
    cancelled = threading.Event()
    errors: list[BaseException] = []
    threads = [enter(gate, 6 * GB, first, release)]
    assert first.wait(5)
    waiter_entered, waiter_release = threading.Event(), threading.Event()
    waiter = enter(gate, 6 * GB, waiter_entered, waiter_release, cancel_check=cancelled.is_set, errors=errors)
    assert not waiter_entered.wait(0.1)
    cancelled.set()
    waiter.join(5)
    assert not waiter.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], ConversionCancelled)
    assert not gate._queue, "it no longer blocks anyone"
    release.set()
    for thread in threads:
        thread.join(5)


def test_the_budget_comes_back_after_an_exception():
    gate = wl.AssemblyGate(Machine(16, 32), poll_seconds=0.01)
    with pytest.raises(MemoryError):
        with gate.reserve(6 * GB):
            raise MemoryError
    assert gate._in_use == 0
    with gate.reserve(6 * GB):
        with gate.reserve(1 * GB):
            assert gate._in_use == 7 * GB


def test_a_reserved_assembly_that_has_not_allocated_yet_is_still_counted():
    """The free figure cannot see it yet: 5 GB reserved, 8 GB usable, so an 8 GB assembly must wait (found by review)."""
    gate = wl.AssemblyGate(Machine(16, 32), poll_seconds=0.01)
    first, second, release, release_second = (threading.Event() for _ in range(4))
    threads = [enter(gate, 5 * GB, first, release)]
    assert first.wait(5)
    threads.append(enter(gate, 8 * GB, second, release_second))
    assert not second.wait(0.2)
    release.set()
    assert second.wait(5)
    release_second.set()
    for thread in threads:
        thread.join(5)


def test_live_memory_pressure_from_other_programs_holds_a_second_assembly_back():
    machine_now = Machine(16, 32)
    gate = wl.AssemblyGate(machine_now, poll_seconds=0.01)
    first, second, release = threading.Event(), threading.Event(), threading.Event()
    threads = [enter(gate, 2 * GB, first, release)]
    assert first.wait(5)
    machine_now.info = wl.MemoryInfo(int(9 * GB), 32 * GB)  # something else took 7 GB: 1 GB usable now
    release_second = threading.Event()
    threads.append(enter(gate, 2 * GB, second, release_second))
    assert not second.wait(0.2)
    machine_now.info = wl.MemoryInfo(int(16 * GB), 32 * GB)
    assert second.wait(5)
    release.set()
    release_second.set()
    for thread in threads:
        thread.join(5)


def test_unknown_memory_lets_only_a_little_assemble_at_once():
    gate = wl.AssemblyGate(lambda: None, poll_seconds=0.01)
    first, second, release, release_second = (threading.Event() for _ in range(4))
    threads = [enter(gate, wl.UNKNOWN_MEMORY_ASSEMBLY_BYTES - 1 * GB, first, release)]
    assert first.wait(5)
    threads.append(enter(gate, 2 * GB, second, release_second))
    assert not second.wait(0.2), "together they are over the assumed budget"
    release.set()
    assert second.wait(5)
    release_second.set()
    for thread in threads:
        thread.join(5)
    with gate.reserve(wl.UNKNOWN_MEMORY_ASSEMBLY_BYTES // 4):
        with gate.reserve(wl.UNKNOWN_MEMORY_ASSEMBLY_BYTES // 4):
            pass


def test_eight_workers_assemble_serially_when_only_one_fits_and_all_finish():
    """What a queue the plan got wrong does at runtime: nothing exceeds the budget, and nothing is refused."""
    gate = wl.AssemblyGate(Machine(16, 32), poll_seconds=0.005)
    lock = threading.Lock()
    inside = [0]
    peak = [0]
    done = []

    def worker():
        with gate.reserve(5 * GB):
            with lock:
                inside[0] += 1
                peak[0] = max(peak[0], inside[0])
            time.sleep(0.01)
            with lock:
                inside[0] -= 1
        done.append(1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert len(done) == 8
    assert peak[0] == 1, "two of 5 GB do not fit in 8 GB"


def test_an_ordinary_join_never_touches_the_gate(monkeypatch):
    monkeypatch.setattr(wl.ASSEMBLY_GATE, "reserve", lambda *a, **k: pytest.fail("below the threshold"))
    with wl.assembly_slot(wl.ASSEMBLY_GATE_MIN_PCM_BYTES - 1):
        pass


def test_a_large_join_asks_the_gate_for_its_budget(monkeypatch):
    asked = []

    class Spy:
        def __enter__(self):
            return wl.AssemblyPlace(None, True, 0)

        def __exit__(self, *exc):
            return False

    def place(need, **_kwargs):
        asked.append(need)
        return Spy()

    gate = wl.AssemblyGate()
    gate.place = place
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", gate)
    pcm = 48_000 * 3600  # an hour
    with wl.assembly_slot(pcm):
        pass
    assert asked == [wl.peak_bytes_for_pcm(pcm)]


def test_decoded_size_reads_real_headers_without_decoding(tmp_path):
    from pydub.generators import Sine

    from shared import ffmpeg_utils

    if not ffmpeg_utils.have_ffmpeg():
        pytest.skip("needs ffmpeg to make the fixtures")
    ffmpeg_utils.configure_pydub()
    tone = Sine(440, sample_rate=24000).to_audio_segment(duration=2000, volume=-20)
    flac, mp3 = tmp_path / "a.flac", tmp_path / "b.mp3"
    tone.export(str(flac), format="flac")
    tone.export(str(mp3), format="mp3", bitrate="48k")
    assert wl.decoded_size([flac]) == pytest.approx(2 * 48_000, rel=0.01)
    assert wl.decoded_size([mp3]) == pytest.approx(2 * 48_000, rel=0.05)
    assert wl.decoded_size([flac, mp3]) == pytest.approx(4 * 48_000, rel=0.05)


def test_long_silence_is_counted_by_its_length_not_its_compressed_size(tmp_path):
    """FLAC stores silence in almost nothing, so a file's bytes say nothing about what it decodes to. This is the
    pause-heavy case again, and why the gate reads headers."""
    from pydub import AudioSegment

    from shared import ffmpeg_utils

    if not ffmpeg_utils.have_ffmpeg():
        pytest.skip("needs ffmpeg to make the fixtures")
    ffmpeg_utils.configure_pydub()
    flac = tmp_path / "pauses.flac"
    AudioSegment.silent(duration=120_000, frame_rate=24000).export(str(flac), format="flac")
    assert flac.stat().st_size < 120 * 48_000 / 100
    assert wl.decoded_size([flac]) == pytest.approx(120 * 48_000, rel=0.01)


def test_a_file_whose_header_cannot_be_read_is_sized_generously_and_a_missing_one_not_at_all(tmp_path):
    junk = tmp_path / "junk.mp3"
    junk.write_bytes(b"not audio" * 100)
    assert wl.decoded_size([junk]) == 900 * wl.UNREADABLE_AUDIO_EXPANSION
    assert wl.decoded_size([tmp_path / "gone.flac"]) == 0


# --------------------------------------------------------------------------- #
# One policy, whoever asks
# --------------------------------------------------------------------------- #


def test_the_panel_and_the_command_line_reach_the_same_decision(tmp_path, monkeypatch):
    """Both call ``plan_for_sources`` with the folder route's real settings: the same files, the same answer."""
    from tts import batch_convert

    in_dir = tmp_path / "in"
    in_dir.mkdir()
    for index in range(8):
        write(in_dir / f"{index}.txt", "A.\n\n" * 10_000)
    machine(monkeypatch, memory=GIB16, cpus=16)
    captured: dict = {}
    real_plan = wl.plan_for_sources

    def spy(requested, backend, sources, **kwargs):
        captured["sources"], captured["settings"] = list(sources), kwargs.get("settings")
        plan_made = real_plan(requested, backend, captured["sources"], **kwargs)
        captured["plan"] = plan_made
        return plan_made

    monkeypatch.setattr(wl, "plan_for_sources", spy)
    monkeypatch.setattr(batch_convert, "convert_single_pdf", lambda p, *a, **k: ("success", p, None))
    logged: list[str] = []
    batch_convert.run_batch_convert(in_dir, tmp_path / "out", workers=8, rate="-20%", use_tqdm=False, log=logged.append,
                                    label="Aria", speaker="en-US-AriaNeural")

    assert all(source.direct is False for source in captured["sources"])
    assert captured["settings"].rate == "-20%"
    assert any(line.strip() == captured["plan"].log_lines()[0] for line in logged)

    panel_plan = real_plan(8, "edge", captured["sources"], settings=wl.NarrationSettings.for_run({}, "-20%", None))
    assert panel_plan.effective == captured["plan"].effective
    assert panel_plan.log_lines() == captured["plan"].log_lines()


def test_requests_from_1_to_100_are_accepted():
    budgets = [wl.budget_for_seconds(0)] * 100
    roomy = wl.MemoryInfo(500 * GB, 512 * GB)
    for requested in range(1, 101):
        assert wl.plan_workers(requested, "edge", budgets, cpu_count=64, memory=roomy).effective == min(requested, 32)


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
