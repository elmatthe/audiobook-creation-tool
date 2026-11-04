"""v0.7.1 — memory is kept safe by what is measured during the run, not only by a plan (Codex HIGH-002A and HIGH-002B on e19527e).

* **Sizing.** A PDF is sized from the text a conversion speaks, its pages joined the same way (HIGH-002A: 98.6 MB where the
  same model on the real paragraph says 2.57 GB, and eight workers on 8 GiB).
* **Synthesis.** What one file holds in memory while it is synthesised has a limit, whatever the plan believed (HIGH-002A:
  paragraph audio built up before any gate was asked).
* **Assembly.** No assembly is let into memory for being first (HIGH-002B). One that does not fit is assembled on disk, and
  that gives the same file, to the byte. Only when not even that has room does a file wait, and then fail with a reason.

Everything real except the network request; clips differ by text, so a part out of order or lost changes the bytes.
"""

from __future__ import annotations

import ast
import contextlib
import io
import itertools
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import tracemalloc
import wave
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError, CouldntEncodeError
from pydub.generators import Sine

from source_probe import application_python_files
from shared import ffmpeg_utils
from shared.cancellation import ConversionCancelled
from tts import audio_tail, batch_convert, disk_assembly, edge_failures, pdf_extractor, publication
from tts import worker_limits as wl
from tts.epub2tts_edge import epub2tts_edge as engine
from tts.epub2tts_edge import runner

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_utils.have_ffmpeg(), reason="requires a real ffmpeg/ffprobe pair")

GB = 1024 ** 3
MB = 1024 ** 2
_CLIPS: dict[str, bytes] = {}


class Machine:
    """What the operating system says is free. Mutable: a test can have other work take memory, or give it back."""

    def __init__(self, available: float, total: float = 32):
        self.available, self.total = int(available * GB), int(total * GB)
        self.reads = 0

    def __call__(self):
        self.reads += 1
        return wl.MemoryInfo(self.available, self.total)


def eventually(predicate, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "it never happened"
        time.sleep(0.005)


# --------------------------------------------------------------------------- #
# HIGH-002A, sizing: the reviewer's PDF, and what must stay true of ordinary ones
# --------------------------------------------------------------------------- #


def continuous_prose_pdf(path: Path, pages: int = 80) -> Path:
    """The review's reproduction: an explicit heading, then prose that never ends a sentence, on every page."""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        if index == 0:
            page.insert_text((50, 50), "# Prologue", fontsize=9, fontname="cour")
        assert page.insert_textbox(fitz.Rect(50, 80, 540, 790), "word " * 500, fontsize=9, fontname="cour") >= 0
    doc.save(path)
    doc.close()
    return path


def ordinary_pdf(path: Path, pages: int = 20) -> Path:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        text = "\n".join(f"Paragraph {line} of page {index} is short and finishes properly." for line in range(12))
        assert page.insert_textbox(fitz.Rect(50, 50, 540, 790), f"Chapter {index + 1}\n\n{text}\n{index + 1}", fontsize=10) >= 0
    doc.save(path)
    doc.close()
    return path


def test_a_fully_read_pdf_is_sized_by_the_paragraph_a_conversion_really_makes(tmp_path):
    source = continuous_prose_pdf(tmp_path / "prose.pdf")
    settings = wl.NarrationSettings()

    estimate = wl._estimate_source(wl.QueuedSource(source), settings)

    real = pdf_extractor.extract_text_from_pdf(str(source))
    assert estimate.basis == "text"
    assert estimate.longest_paragraph == wl._longest_paragraph_seconds(real, settings)
    assert estimate.longest_paragraph > 16_000, "was 209.1: one page of the 80-page paragraph"


def test_the_reviewed_pdf_no_longer_gets_eight_workers_on_an_8_gib_machine(tmp_path, monkeypatch):
    monkeypatch.setattr(wl, "memory_info", lambda: wl.MemoryInfo(8 * GB, 8 * GB))
    monkeypatch.setattr(wl, "logical_cpus", lambda: 16)
    source = continuous_prose_pdf(tmp_path / "prose.pdf")

    plan = wl.plan_for_sources(8, wl.EDGE, [wl.QueuedSource(source)] * 8)

    assert plan.effective == 1 and any("memory" in reason for reason in plan.reasons)


def test_an_ordinary_book_keeps_its_workers_on_that_machine(tmp_path, monkeypatch):
    """The correction above must not hold back what it has no reason to: paragraphs that finish are not joined."""
    monkeypatch.setattr(wl, "memory_info", lambda: wl.MemoryInfo(8 * GB, 8 * GB))
    monkeypatch.setattr(wl, "logical_cpus", lambda: 16)
    source = ordinary_pdf(tmp_path / "book.pdf")

    plan = wl.plan_for_sources(8, wl.EDGE, [wl.QueuedSource(source)] * 8)

    assert plan.effective == 8
    assert wl._estimate_source(wl.QueuedSource(source), wl.NarrationSettings()).longest_paragraph == 0


@pytest.mark.parametrize("make", [continuous_prose_pdf, ordinary_pdf], ids=["continuous", "ordinary"])
def test_sizing_reads_exactly_the_text_a_conversion_speaks(tmp_path, make):
    source = make(tmp_path / "doc.pdf")
    pages, read, text = pdf_extractor.pdf_text_sample(str(source), 1000)
    assert read == pages
    assert text == pdf_extractor.extract_text_from_pdf(str(source))


def test_a_sampled_pdf_scales_a_paragraph_that_continues_past_what_was_read(tmp_path, monkeypatch):
    source = continuous_prose_pdf(tmp_path / "prose.pdf")
    whole = wl._longest_paragraph_seconds(pdf_extractor.extract_text_from_pdf(str(source)), wl.NarrationSettings())
    monkeypatch.setattr(wl, "PDF_SCAN_PAGES", 10)

    estimate = wl._estimate_source(wl.QueuedSource(source), wl.NarrationSettings())

    assert estimate.basis == "sampled"
    assert estimate.longest_paragraph == pytest.approx(whole, rel=0.05), "ten pages read, standing for all eighty"


def _merged_before_it_was_made_linear(text: str) -> str:
    """The rule as it stood at e19527e: the reference for the differential test below."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n+", text) if b.strip()]
    if len(blocks) < 2:
        return text
    out: list[str] = []
    for b in blocks:
        if not out:
            out.append(b)
            continue
        prev = out[-1]
        if pdf_extractor._looks_like_heading_line(prev):
            out.append(b)
            continue
        prev_ends = bool(re.search(r'[.!?:)"\'—]\s*$', prev))
        looks_heading = pdf_extractor._looks_like_heading_line(b)
        if prev_ends or looks_heading:
            out.append(b)
        else:
            out[-1] = prev + " " + b
    return "\n\n".join(out)


def test_joining_across_pages_gives_exactly_what_it_always_gave():
    """The extraction every conversion speaks: making it linear must not change one character of it."""
    rng = random.Random(71)
    pieces = ["word", "Word Two", "ALL CAPS", "Chapter 12: Minefield", "ends here.", "asks?", "says!", 'quoted"', "(aside)",
              "colon:", "dash—", "it's'", "x" * 79, "y" * 80, "z" * 200, "hyphen-", "Title Case Line", "1", "IV", "ünï çødé",
              " nbsp ", "trailing \t", "\x0bvt\x0b"]
    separators = ["\n\n", "\n \n", "\n\n\n\n", "\n\t\n", "\n", " "]
    for _ in range(2000):
        text = "".join(rng.choice(pieces) + rng.choice(separators) for _ in range(rng.randrange(0, 14)))
        assert pdf_extractor._merge_blocks_across_page_gaps(text) == _merged_before_it_was_made_linear(text), repr(text)


def test_joining_a_whole_book_of_continuous_prose_stays_quick():
    """Sizing runs this on what it read: it was quadratic in the length of a block, which is the whole book here."""
    text = "\n\n".join(["no sentence ever ends " * 200] * 5000)  # 22 MB, every page continuing into the next
    started = time.monotonic()
    merged = pdf_extractor._merge_blocks_across_page_gaps(text)
    assert time.monotonic() - started < 5
    assert merged.count("\n\n") == 0


# --------------------------------------------------------------------------- #
# HIGH-002B: the gate
# --------------------------------------------------------------------------- #


def test_the_reviewed_case_the_first_assembly_with_nothing_free_is_not_admitted():
    """Zero reported free memory, nothing else reserved: admitted with a warning, at e19527e."""
    machine = Machine(0, 8)
    gate = wl.AssemblyGate(machine, poll_seconds=0.001, wait_seconds=0.05)
    notes: list[str] = []
    entered = False

    with pytest.raises(wl.AssemblyMemoryError, match="Retry Failed"):
        with gate.reserve(wl.peak_bytes_for_seconds(4 * 3600), note=notes.append):
            entered = True

    assert entered is False and machine.reads > 0
    assert gate._in_use == 0 and not gate._queue, "nothing is left held"
    assert "Waiting for memory" in notes[0]


def test_the_first_assembly_is_measured_like_any_other():
    machine = Machine(16)  # 8 GiB usable after the reserve
    gate = wl.AssemblyGate(machine)
    with gate.reserve(8 * GB) as in_memory:
        assert in_memory is True and machine.reads == 1
    with gate.reserve(8 * GB + 1) as in_memory:
        assert in_memory is False


def test_synthesis_already_using_the_memory_is_seen_by_the_first_assembly():
    """The review: an empty reservation counter says nothing about RAM that synthesis workers are using."""
    machine = Machine(20)
    gate = wl.AssemblyGate(machine)
    with gate.reserve(5 * GB) as in_memory:
        assert in_memory is True
    machine.available -= 10 * GB  # other files are synthesising, FFmpeg is running; the gate has reserved nothing for them
    assert gate._in_use == 0
    with gate.reserve(5 * GB) as in_memory:
        assert in_memory is False
    machine.available += 10 * GB  # they finished
    with gate.reserve(5 * GB) as in_memory:
        assert in_memory is True


def test_with_too_little_free_even_for_disk_it_waits_and_goes_as_soon_as_there_is_room():
    machine = Machine(0, 8)
    gate = wl.AssemblyGate(machine, poll_seconds=0.001)
    entered = threading.Event()
    routes: list[bool] = []

    def assemble():
        with gate.reserve(4 * GB) as in_memory:
            routes.append(in_memory)
            entered.set()

    worker = threading.Thread(target=assemble)
    worker.start()
    assert not entered.wait(0.1)
    machine.available = wl.DISK_ASSEMBLY_BYTES
    assert entered.wait(5)
    worker.join(5)
    assert routes == [False]


def test_with_too_little_free_cancel_ends_the_wait_of_a_file_with_more_to_synthesise():
    gate = wl.AssemblyGate(Machine(0, 8), poll_seconds=0.001)
    with pytest.raises(ConversionCancelled):
        with gate.reserve(4 * GB, cancel_check=lambda: True):
            pass
    assert gate._in_use == 0 and not gate._queue


def test_it_gives_up_only_after_the_whole_wait_by_its_clock():
    now = [0.0]
    limit = wl.ASSEMBLY_MEMORY_WAIT_SECONDS

    def clock():
        now[0] += limit / 10
        return now[0]

    gate = wl.AssemblyGate(Machine(0, 8), poll_seconds=0.001, clock=clock)
    with pytest.raises(wl.AssemblyMemoryError):
        with gate.reserve(4 * GB):
            pass
    assert now[0] >= limit


def test_while_another_file_assembles_in_memory_a_file_waits_for_it_however_long_and_never_gives_up():
    """Its memory is coming back, so this is an ordinary turn, not a shortage."""
    machine = Machine(16)
    gate = wl.AssemblyGate(machine, poll_seconds=0.001, wait_seconds=0.01)
    release, second_entered = threading.Event(), threading.Event()
    routes: list[bool] = []

    def second():
        with gate.reserve(100 * GB) as in_memory:
            routes.append(in_memory)
            second_entered.set()

    with gate.reserve(8 * GB) as in_memory:
        assert in_memory is True
        worker = threading.Thread(target=second)
        worker.start()
        assert not second_entered.wait(0.2), "well past its patience, and still waiting: not failed, not on disk yet"
        assert worker.is_alive()
    assert second_entered.wait(5)
    worker.join(5)
    assert routes == [False], "then it does not fit alone either, so it goes to disk"


def test_assemblies_on_disk_overlap_and_are_counted_at_what_they_need():
    gate = wl.AssemblyGate(Machine(2), poll_seconds=0.001)
    both, release = threading.Barrier(3), threading.Event()
    held: list[int] = []

    def assemble():
        with gate.reserve(100 * GB) as in_memory:
            assert in_memory is False
            both.wait(5)
            release.wait(5)

    workers = [threading.Thread(target=assemble) for _ in range(2)]
    for worker in workers:
        worker.start()
    both.wait(5)
    held.append(gate._in_use)
    release.set()
    for worker in workers:
        worker.join(5)
    assert held == [2 * wl.DISK_ASSEMBLY_BYTES]
    assert gate._in_use == 0


def test_a_failure_inside_either_route_gives_everything_back():
    gate = wl.AssemblyGate(Machine(16))
    for need in (1 * GB, 100 * GB):
        with pytest.raises(RuntimeError):
            with gate.reserve(need):
                raise RuntimeError("the assembly failed")
        assert gate._in_use == 0 and gate._in_memory == 0


def test_running_out_of_memory_to_assemble_is_a_local_failure_never_retried_by_synthesising_again():
    assert not edge_failures.is_retryable(wl.AssemblyMemoryError("no room"))
    assert edge_failures.classify(wl.AssemblyMemoryError("no room")) is edge_failures.EdgeFailureKind.LOCAL


def test_an_ordinary_join_takes_no_place_at_the_gate():
    with wl.assembly_slot(wl.ASSEMBLY_GATE_MIN_PCM_BYTES - 1) as in_memory:
        assert in_memory is True


def test_every_production_assembly_reads_the_gates_answer():
    """A caller that ignored the answer would hold a whole narration in memory after being told not to."""
    found = 0
    for path in application_python_files():  # the one definition of the shipped source
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.With):
                continue
            for item in node.items:
                call = item.context_expr
                name = getattr(getattr(call, "func", None), "attr", None) or getattr(getattr(call, "func", None), "id", None)
                if name not in ("assembly_slot", "_assembly_slot") or path.name == "worker_limits.py":
                    continue
                found += 1
                assert isinstance(item.optional_vars, ast.Name), f"{path.name}:{node.lineno} ignores the gate's answer"
                read = [n for stmt in node.body for n in ast.walk(stmt)
                        if isinstance(n, ast.Name) and n.id == item.optional_vars.id and isinstance(n.ctx, ast.Load)]
                assert read, f"{path.name}:{node.lineno} binds the gate's answer and never reads it"
    assert found == 3, "the chapter join, the direct route's final assembly and the folder route's"


# --------------------------------------------------------------------------- #
# The real routes, offline
# --------------------------------------------------------------------------- #


def clip_for(text: str, seconds: float | None = None) -> bytes:
    """A real-format Edge clip (24 kHz mono MP3) that depends on its text, with quiet at both ends to be trimmed: at the end
    far more than the final-tail policy keeps, so every narration's ending really is cut, on both routes."""
    key = f"{seconds}:{text}"
    if key not in _CLIPS:
        ffmpeg_utils.configure_pydub()
        seed = zlib.crc32(text.encode())
        length = seconds if seconds is not None else 0.25 + (seed % 7) / 20
        tone = Sine(180 + seed % 500, sample_rate=24000).to_audio_segment(duration=int(length * 1000), volume=-18)
        padded = AudioSegment.silent(90, frame_rate=24000) + tone + AudioSegment.silent(900, frame_rate=24000)
        buffer = io.BytesIO()
        padded.set_channels(1).export(buffer, format="mp3", bitrate="48k")
        _CLIPS[key] = buffer.getvalue()
    return _CLIPS[key]


@pytest.fixture()
def offline(monkeypatch):
    monkeypatch.setattr(engine, "_SENTENCE_TOKENIZER", None, raising=False)
    monkeypatch.setattr(engine, "run_edgespeak", lambda text, speaker, path: Path(path).write_bytes(clip_for(text)))
    monkeypatch.setattr(batch_convert, "synthesize_chunk_mp3",
                        lambda text, path, voice, rate: Path(path).write_bytes(clip_for(text)))
    monkeypatch.setattr(batch_convert, "INTER_CHUNK_DELAY_SEC", 0)


@pytest.fixture()
def no_room(monkeypatch):
    """No narration, however small, fits in memory here; there is room for the disk route."""
    gate = wl.AssemblyGate(lambda: wl.MemoryInfo(1 * GB, 8 * GB), poll_seconds=0.001)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", gate)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    return gate


BOOK = ("Title: T\nAuthor: A\n# First Chapter\n\n"
        + "\n".join(f"Paragraph {n} opens here, with a comma. It carries on -- with a dash... and an ellipsis! Then it ends?"
                    for n in range(6))
        + "\n# Second Chapter\n\n"
        + "\n".join(f"Second part {n}, once more. And the end of it." for n in range(4)) + "\n")


def write_book(folder: Path, text: str = BOOK) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "book.txt"
    path.write_text(text, encoding="utf-8")
    return path


def direct_mp3(source: Path, out: Path, **kwargs) -> bytes:
    return Path(runner.run_conversion_job(str(source), output_dir=str(out), audio_format="mp3", speaker="v",
                                          mp3_bitrate="192k", **kwargs)).read_bytes()


def folder_mp3(source: Path, out: Path) -> bytes:
    target = out / "book.mp3"
    status, _path, error = batch_convert.convert_single_pdf(source, out, "v", "+0%", lambda _m: None, out_mp3=target,
                                                            bitrate="192k")
    assert status == "success", error
    return target.read_bytes()


def forbid_memory_routes(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("a narration told to use the disk was assembled in memory")

    monkeypatch.setattr(runner, "make_mp3", forbidden)
    monkeypatch.setattr(batch_convert, "merge_mp3s", forbidden)


@needs_ffmpeg
def test_the_disk_route_gives_the_same_mp3_as_memory_to_the_byte_on_the_direct_route(tmp_path, offline, monkeypatch):
    source = write_book(tmp_path / "in")
    in_memory = direct_mp3(source, tmp_path / "memory")

    gate = wl.AssemblyGate(lambda: wl.MemoryInfo(1 * GB, 8 * GB), poll_seconds=0.001)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", gate)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    forbid_memory_routes(monkeypatch)

    assert direct_mp3(source, tmp_path / "disk") == in_memory


@needs_ffmpeg
def test_the_disk_route_gives_the_same_mp3_as_memory_to_the_byte_on_the_folder_route(tmp_path, offline, monkeypatch):
    # Long enough for several chunks, so the pause between chunks is in it, in pydub's own form.
    source = write_book(tmp_path / "in", "".join(f"Sentence number {n} of this long text, which is read in chunks. " for n in range(300)))
    in_memory = folder_mp3(source, tmp_path / "memory")

    gate = wl.AssemblyGate(lambda: wl.MemoryInfo(1 * GB, 8 * GB), poll_seconds=0.001)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", gate)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    forbid_memory_routes(monkeypatch)

    assert folder_mp3(source, tmp_path / "disk") == in_memory
    assert not any((tmp_path / "disk").rglob("*.wav")), "nothing of the assembly is left behind"


@needs_ffmpeg
def test_the_spool_is_the_file_pydub_would_have_written(tmp_path):
    ffmpeg_utils.configure_pydub()
    tone = Sine(330, sample_rate=24000).to_audio_segment(duration=700, volume=-12).set_channels(1)
    flac = tmp_path / "part.flac"
    tone.export(flac, format="flac")
    pause = AudioSegment.silent(duration=250)
    expected = AudioSegment.from_file(flac) + pause + AudioSegment.from_file(flac)
    expected.export(tmp_path / "pydub.wav", format="wav")

    with disk_assembly.WavSpool(tmp_path / "spool.wav") as spool:
        spool.append_file(flac)
        spool.append_segment(pause)
        spool.append_file(flac)
        spool.finish()
        assert (tmp_path / "spool.wav").read_bytes() == (tmp_path / "pydub.wav").read_bytes()
        assert spool.duration_ms == len(expected)
        assert spool.max_dBFS == expected.max_dBFS


@needs_ffmpeg
@pytest.mark.parametrize("ending", ["long quiet tail", "no tail", "all silent", "quiet decay"])
def test_the_final_tail_on_disk_is_the_policy_in_memory(tmp_path, ending):
    ffmpeg_utils.configure_pydub()
    rng = np.random.default_rng(7)
    speech = (rng.normal(0, 3000, 24000)).astype(np.int16)
    tail = {"long quiet tail": np.zeros(24000, dtype=np.int16), "no tail": np.zeros(0, dtype=np.int16),
            "all silent": np.zeros(24000, dtype=np.int16),
            "quiet decay": (rng.normal(0, 8, 24000)).astype(np.int16)}[ending]
    pcm = tail if ending == "all silent" else np.concatenate([speech, tail])
    segment = AudioSegment(data=pcm.tobytes(), sample_width=2, frame_rate=24000, channels=1)
    kept, policy = audio_tail.apply_final_tail_policy_to_segment(segment)

    with disk_assembly.WavSpool(tmp_path / "spool.wav") as spool:
        spool.append_segment(segment)
        spool.finish()
        summary = spool.apply_final_tail()
        assert summary == policy.summary()
        with wave.open(str(spool.path), "rb") as written:
            assert written.getnframes() == len(kept.raw_data) // 2
            assert written.readframes(written.getnframes()) == kept.raw_data
        assert spool.path.stat().st_size == disk_assembly.WAV_HEADER_BYTES + len(kept.raw_data), "the file too, not only its header"
        assert spool.duration_ms == len(kept)


@needs_ffmpeg
@pytest.mark.parametrize("keywords", [{"format": "mp3", "bitrate": "192k"},
                                      {"format": "mp3", "codec": "libmp3lame", "bitrate": "128k"}, {"format": "flac"}],
                         ids=["the direct route's mp3", "the folder route's mp3", "a chapter's flac"])
def test_the_encoder_is_called_exactly_as_pydub_calls_it(tmp_path, monkeypatch, keywords):
    """Not only what comes out on this FFmpeg: a build whose default MP3 encoder differs would show nothing in the bytes."""
    ffmpeg_utils.configure_pydub()
    segment = AudioSegment.silent(duration=50, frame_rate=24000)
    commands: list[list[str]] = []
    real_popen = subprocess.Popen

    def recording_popen(command, *args, **kwargs):
        commands.append(list(command))
        return real_popen(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", recording_popen)
    segment.export(tmp_path / "pydub.out", **keywords)
    assert len(commands) == 1
    with disk_assembly.WavSpool(tmp_path / "spool.wav") as spool:
        spool.append_segment(segment)
        spool.finish()
        spool.export(tmp_path / "disk.out", **keywords)
    assert len(commands) == 2

    def without_paths(command):
        # The input follows -i; the output is last. Those are the only differences there may be.
        at = command.index("-i")
        return [command[0], *command[1:at + 1], *command[at + 2:-1]]

    assert without_paths(commands[1]) == without_paths(commands[0])


@needs_ffmpeg
@pytest.mark.parametrize("keep_trailing", [False, True])
@pytest.mark.parametrize("frames, lead, end", [(24000, 3000, 3000), (24013, 0, 0), (24013, 2400, 7), (24007, 11, 2411), (240, 0, 0),
                                               (5, 0, 0), (0, 0, 0), (48000, 48000, 0)])
def test_trimming_on_disk_cuts_the_samples_it_cuts_in_memory(tmp_path, frames, lead, end, keep_trailing):
    """Includes lengths whose rounded end lies past the last frame, where pydub fills with silence, and a silent clip."""
    rng = np.random.default_rng(frames)
    pcm = rng.integers(2000, 9000, frames, dtype=np.int16)
    pcm[:lead] = 0
    if end:
        pcm[-end:] = 0
    segment = AudioSegment(data=pcm.tobytes(), sample_width=2, frame_rate=24000, channels=1)

    def trim(sound):
        return engine.trim_silence_segment(sound, silence_threshold=-50, chunk_size=10, keep_trailing=keep_trailing)

    expected = trim(segment).raw_data
    with disk_assembly.WavSpool(tmp_path / "clip.wav") as spool:
        spool.append_segment(segment)
        spool.finish()
        with open(spool.path, "rb") as handle:
            sound = disk_assembly.SoundOnDisk(handle, 24000, 1, 0, frames)
            assert len(sound) == len(segment)
            assert b"".join(trim(sound).blocks()) == expected


@needs_ffmpeg
def test_a_silent_narration_is_refused_on_disk_as_it_is_in_memory(tmp_path):
    ffmpeg_utils.configure_pydub()
    AudioSegment.silent(duration=500, frame_rate=24000).export(tmp_path / "part.flac", format="flac")
    with pytest.raises(publication.PublicationError, match="silent"):
        disk_assembly.encode_mp3([tmp_path / "part.flac"], tmp_path / "out.mp3", tmp_path / "spool.wav")
    assert not (tmp_path / "out.mp3").exists()
    assert not (tmp_path / "spool.wav").exists()


@needs_ffmpeg
def test_a_cut_short_encode_is_refused_on_disk_as_it_is_in_memory(tmp_path, long_parts, monkeypatch):
    real = disk_assembly.WavSpool.export

    def cuts_it_short(self, output, **kwargs):
        real(self, output, **kwargs)
        Path(output).write_bytes(Path(output).read_bytes()[: Path(output).stat().st_size // 2])

    monkeypatch.setattr(disk_assembly.WavSpool, "export", cuts_it_short)
    with pytest.raises(publication.PublicationError, match="cut short"):
        disk_assembly.encode_mp3(long_parts[:1], tmp_path / "out.mp3", tmp_path / "spool.wav", bitrate="192k")


@needs_ffmpeg
def test_an_encode_failure_is_noticed(tmp_path, long_parts):
    with disk_assembly.WavSpool(tmp_path / "spool.wav") as spool:
        spool.append_file(long_parts[0])
        spool.finish()
        with pytest.raises(CouldntEncodeError, match="ffmpeg returned error code"):
            spool.export(tmp_path / "out.mp3", format="mp3", bitrate="not-a-bitrate")


def test_a_narration_over_the_wav_limit_is_refused_before_it_fills_the_disk(tmp_path):
    with disk_assembly.WavSpool(tmp_path / "spool.wav") as spool:
        spool.append_segment(AudioSegment.silent(duration=10, frame_rate=24000))
        spool.pcm_bytes = 2 ** 32 - 1
        with pytest.raises(publication.PublicationError, match="over 24 hours"):
            spool.append_segment(AudioSegment.silent(duration=10, frame_rate=24000))
        spool.pcm_bytes = 0


@needs_ffmpeg
def test_a_damaged_part_fails_the_file_saying_what_ffmpeg_said_and_publishes_nothing(tmp_path, offline, no_room):
    ffmpeg_utils.configure_pydub()
    (tmp_path / "broken.flac").write_bytes(b"this is not audio at all")
    with pytest.raises(CouldntDecodeError, match="ffmpeg returned error code"):
        disk_assembly.join_to_flac([tmp_path / "broken.flac"], tmp_path / "out.flac", tmp_path / "spool.wav")
    assert not (tmp_path / "out.flac").exists()
    assert not (tmp_path / "spool.wav").exists()


@needs_ffmpeg
def test_a_full_disk_fails_the_file_stops_ffmpeg_and_leaves_nothing_behind(tmp_path, long_parts, monkeypatch):
    """The one thing this route needs that memory does not. It must fail as a local problem, not hang on a decoder that is
    still writing into a pipe nobody reads."""
    started = []
    real_popen = disk_assembly.subprocess_utils.popen

    def popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        started.append(process)
        return process

    def no_space(self, _data):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(disk_assembly.subprocess_utils, "popen", popen)
    monkeypatch.setattr(disk_assembly.WavSpool, "_write", no_space)
    with pytest.raises(OSError, match="No space left"):
        disk_assembly.join_to_flac(long_parts, tmp_path / "out.flac", tmp_path / "spool.wav")
    assert started and all(process.poll() is not None for process in started), "no FFmpeg is left running"
    assert not (tmp_path / "out.flac").exists() and not (tmp_path / "spool.wav").exists()
    assert not edge_failures.is_retryable(OSError(28, "No space left on device"))


@needs_ffmpeg
def test_a_failed_encode_fails_the_file_with_nothing_published_and_a_taken_name_untouched(tmp_path, offline, no_room, monkeypatch):
    source = write_book(tmp_path / "in")
    target = tmp_path / "out" / "book.mp3"
    target.parent.mkdir()
    target.write_bytes(b"someone's file")
    real_export = disk_assembly.WavSpool.export

    def failing_export(self, output, **kwargs):
        if kwargs.get("format") == "mp3":
            raise CouldntEncodeError("Encoding failed.")
        return real_export(self, output, **kwargs)

    monkeypatch.setattr(disk_assembly.WavSpool, "export", failing_export)
    status, _path, error = batch_convert.convert_single_pdf(source, tmp_path / "out", "v", "+0%", lambda _m: None, out_mp3=target,
                                                            bitrate="192k", overwrite=True)
    assert status == "failed" and "Encoding failed" in error
    assert target.read_bytes() == b"someone's file"
    assert not [p for p in target.parent.iterdir() if p.name != "book.mp3" and p.name != ".tmp_chunks"]


@needs_ffmpeg
def test_with_overwrite_off_the_disk_route_never_replaces_a_name_taken_during_the_run(tmp_path, offline, no_room, monkeypatch):
    """HIGH-001's contract holds on this route too: only the publication makes a final name."""
    source = write_book(tmp_path / "in")
    target = tmp_path / "out" / "book.mp3"
    real = disk_assembly.encode_mp3

    def takes_the_name_meanwhile(*args, **kwargs):
        result = real(*args, **kwargs)
        target.write_bytes(b"appeared during the run")
        return result

    monkeypatch.setattr(disk_assembly, "encode_mp3", takes_the_name_meanwhile)
    status, _path, error = batch_convert.convert_single_pdf(source, tmp_path / "out", "v", "+0%", lambda _m: None, out_mp3=target,
                                                            bitrate="192k", overwrite=False)
    assert status == "failed" and "already exists" in error
    assert target.read_bytes() == b"appeared during the run"


@needs_ffmpeg
@pytest.mark.parametrize("route", ["direct", "folder"])
def test_too_little_memory_even_for_the_disk_route_fails_the_file_and_is_not_synthesised_again(tmp_path, monkeypatch, route):
    gate = wl.AssemblyGate(lambda: wl.MemoryInfo(0, 8 * GB), poll_seconds=0.001, wait_seconds=0.01)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", gate)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    requests = []

    def request(text, path):
        requests.append(text)
        Path(path).write_bytes(clip_for(text))

    monkeypatch.setattr(engine, "_SENTENCE_TOKENIZER", None, raising=False)
    monkeypatch.setattr(engine, "run_edgespeak", lambda text, speaker, path: request(text, path))
    monkeypatch.setattr(batch_convert, "synthesize_chunk_mp3", lambda text, path, voice, rate: request(text, path))
    monkeypatch.setattr(batch_convert, "INTER_CHUNK_DELAY_SEC", 0)
    source = write_book(tmp_path / "in", "One sentence here.\n")
    out = tmp_path / "out"
    if route == "direct":
        with pytest.raises(wl.AssemblyMemoryError):
            direct_mp3(source, out)
    else:
        status, _path, error = batch_convert.convert_single_pdf(source, out, "v", "+0%", lambda _m: None, out_mp3=out / "book.mp3")
        assert status == "failed" and "Too little memory" in error
    assert len(requests) == 1, "the same machine in the same state would only fail again, hours of synthesis later"
    assert not list(out.glob("*.mp3")) if out.exists() else True


@needs_ffmpeg
def test_cancel_during_assembly_on_disk_keeps_the_finished_narration(tmp_path, offline, no_room, monkeypatch):
    """The owner's decision holds on this route: past the last checkpoint a narration is finished work."""
    source = write_book(tmp_path / "in")
    pressed = threading.Event()
    real = disk_assembly.encode_mp3

    def cancel_during(*args, **kwargs):
        pressed.set()
        return real(*args, **kwargs)

    monkeypatch.setattr(disk_assembly, "encode_mp3", cancel_during)
    produced = direct_mp3(source, tmp_path / "out", cancel_check=pressed.is_set)
    assert pressed.is_set() and len(produced) > 0


@needs_ffmpeg
def test_eight_files_with_memory_coming_and_going_all_finish_with_the_same_bytes(tmp_path, offline, monkeypatch):
    """Both routes at once, the gate's answer changing under them: every file finishes, each file's bytes are what a roomy
    machine gives whichever route it took, and nothing is left reserved or waiting."""
    def sources(root: Path) -> list[Path]:
        return [write_book(root / str(n), f"# Book {n}\n\n" + "\n".join(f"Book {n} says {m}, and stops." for m in range(5)) + "\n")
                for n in range(8)]

    def convert(index: int, source: Path, out: Path) -> bytes:
        return direct_mp3(source, out) if index % 2 else folder_mp3(source, out)

    expected = [convert(n, source, tmp_path / "roomy" / str(n)) for n, source in enumerate(sources(tmp_path / "a"))]

    routes = {"memory": 0, "disk": 0}
    reads = itertools.count()

    def reading():
        # Every third reading finds nothing free at all. Otherwise each admission in turn finds room, or finds none: so both
        # routes are certain to be used, overlapping, whatever order the files arrive in.
        if next(reads) % 3 == 0:
            return wl.MemoryInfo(0, 32 * GB)
        return wl.MemoryInfo((16 if (routes["memory"] + routes["disk"]) % 2 == 0 else 1) * GB, 32 * GB)

    gate = wl.AssemblyGate(reading, poll_seconds=0.001)
    real_reserve = gate.reserve

    @contextlib.contextmanager
    def counting(need, **kwargs):
        with real_reserve(need, **kwargs) as in_memory:
            routes["memory" if in_memory else "disk"] += 1
            yield in_memory

    monkeypatch.setattr(gate, "reserve", counting)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", gate)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(convert, n, source, tmp_path / "out" / str(n)) for n, source in enumerate(sources(tmp_path / "b"))]
        produced = [future.result(timeout=240) for future in futures]

    assert produced == expected
    assert routes["memory"] and routes["disk"], routes
    assert gate._in_use == 0 and gate._in_memory == 0 and not gate._queue


@needs_ffmpeg
def test_the_disk_route_says_so_in_the_log(tmp_path, offline, no_room, capsys):
    direct_mp3(write_book(tmp_path / "in"), tmp_path / "out")
    assert "assembled on disk" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# HIGH-002A, runtime: what one file holds while it is synthesised
# --------------------------------------------------------------------------- #


LONG_PARAGRAPH = ("Title: T\nAuthor: A\n# Only Chapter\n\n"
                  + " ".join(f"Sentence {n} of one paragraph that never breaks, not once." for n in range(60)) + "\n")
ONE_LONG_SENTENCE = ("Title: T\nAuthor: A\n# Only Chapter\n\n"
                     + ", ".join(f"clause {n} of one sentence" for n in range(60)) + ". And done.\n")


def watch_what_is_held(monkeypatch) -> list[int]:
    """Before each request: the audio the engine's own loop is holding, read from its frames, as the review did."""
    held: list[int] = []

    def request(text, speaker, path):
        frame = sys._getframe(1)
        while frame is not None and frame.f_code.co_name != "read_book":
            frame = frame.f_back
        if frame is not None:
            found = frame.f_locals
            held.append(sum(len(s.raw_data) for s in [*found.get("sentence_segments", []), *found.get("sub_segments", [])]))
        Path(path).write_bytes(clip_for(text))

    monkeypatch.setattr(engine, "run_edgespeak", request)
    monkeypatch.setattr(engine, "_SENTENCE_TOKENIZER", None, raising=False)
    return held


@needs_ffmpeg
@pytest.mark.parametrize("text", [LONG_PARAGRAPH, ONE_LONG_SENTENCE], ids=["sentences", "clauses of one sentence"])
def test_a_paragraph_too_long_to_hold_is_written_as_it_grows_with_the_same_audio_in_the_end(tmp_path, monkeypatch, text):
    source = write_book(tmp_path / "in", text)
    held = watch_what_is_held(monkeypatch)
    whole = direct_mp3(source, tmp_path / "held")
    assert max(held) > 400_000, "without a limit the paragraph builds up"

    held.clear()
    monkeypatch.setattr(wl, "SYNTHESIS_HELD_PCM_BYTES", 200_000)
    limited = direct_mp3(source, tmp_path / "limited")

    largest_clip = 100_000  # no clip here decodes to more than this
    assert 0 < max(held) < 200_000 + largest_clip
    assert limited == whole


@needs_ffmpeg
def test_a_paragraph_held_to_its_limit_never_waits_at_the_gate_holding_it(tmp_path, monkeypatch):
    """The review: a wait at the join kept the audio already built up. There is no such join now, and what a later join
    waits with is nothing: it holds file names."""
    source = write_book(tmp_path / "in", LONG_PARAGRAPH)
    watch_what_is_held(monkeypatch)
    monkeypatch.setattr(wl, "SYNTHESIS_HELD_PCM_BYTES", 200_000)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    seen: list[int] = []
    real = wl.AssemblyGate.reserve

    def reserve(self, need, **kwargs):
        frame = sys._getframe(1)
        while frame is not None and frame.f_code.co_name != "read_book":
            frame = frame.f_back
        if frame is not None:
            seen.append(sum(len(s.raw_data) for s in frame.f_locals.get("sentence_segments", [])))
        return real(self, need, **kwargs)

    monkeypatch.setattr(wl.AssemblyGate, "reserve", reserve)
    direct_mp3(source, tmp_path / "out")
    assert seen and max(seen) < 200_000


def one_long_clip(monkeypatch, *, long_text: str, seconds: float = 3.0) -> list:
    """The service answers one text with one long clip. Returns the paths ``AudioSegment.from_file`` was asked for."""
    decoded: list = []

    def request(text, speaker, path):
        Path(path).write_bytes(clip_for(text, seconds if long_text in text else None))

    monkeypatch.setattr(engine, "run_edgespeak", request)
    monkeypatch.setattr(engine, "_SENTENCE_TOKENIZER", None, raising=False)
    real = AudioSegment.from_file.__func__

    def from_file(cls, file, *args, **kwargs):
        decoded.append((str(file), wl.decoded_size([file])))
        return real(cls, file, *args, **kwargs)

    monkeypatch.setattr(AudioSegment, "from_file", classmethod(from_file))
    return decoded


@needs_ffmpeg
@pytest.mark.parametrize("text, long_text", [
    ("Title: T\nAuthor: A\n# One\n\nShort start. Longwinded sentence with no pause in it. Short end.\nAnother one.\n# Two\n\nLast.\n", "Longwinded"),
    ("Title: T\nAuthor: A\n# One\n\nFirst part.\nLongwinded sentence with no pause in it.\n", "Longwinded"),
    ("Title: T\nAuthor: A\n# One\n\nLongwinded first, then a comma, and more.\n# Two\n\nLast one.\n", "Longwinded"),
    ("Title: T\nAuthor: A\n# Longwinded Title\n\nThe text after it.\n# Two\n\nLast one.\n", "Longwinded"),
    # Only pauses are left after it, then the chapter's: they must keep the audio's rate, or the join would refuse them.
    ("Title: T\nAuthor: A\n# One\n\nLongwinded sentence with no pause in it.\n# Two\n\nLast one.\n", "Longwinded"),
], ids=["inside a paragraph", "the last words of the book", "before a comma", "a chapter title", "the last words of a chapter"])
def test_a_clip_too_long_to_hold_never_comes_into_memory_and_changes_nothing(tmp_path, monkeypatch, text, long_text):
    source = write_book(tmp_path / "in", text)
    decoded = one_long_clip(monkeypatch, long_text=long_text)
    whole = direct_mp3(source, tmp_path / "memory")
    largest_held = max(size for _name, size in decoded)
    assert largest_held > 3 * 48_000 * 0.9

    decoded.clear()
    limit = 3 * 48_000 // 2  # the long clip is over this; every other clip is under it
    monkeypatch.setattr(wl, "SYNTHESIS_HELD_PCM_BYTES", limit)
    # With a limit this low, assemblies are the only thing above it, and they have their own gate.
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    gate = wl.AssemblyGate(lambda: wl.MemoryInfo(1 * GB, 8 * GB), poll_seconds=0.001)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", gate)

    limited = direct_mp3(source, tmp_path / "limited")

    assert limited == whole
    assert [name for name, size in decoded if name.endswith(".mp3") and size >= limit] == []


@needs_ffmpeg
def test_with_no_paragraph_pause_a_long_last_clip_takes_its_chapter_pause_without_coming_into_memory(tmp_path, monkeypatch):
    source = write_book(tmp_path / "in", "Title: T\nAuthor: A\n# One\n\nLongwinded sentence.\n# Two\n\nLast one.\n")
    decoded = one_long_clip(monkeypatch, long_text="Longwinded")
    kwargs = dict(paragraphpause=0, sentencepause=0)

    def convert(out):
        return direct_mp3(source, out, **kwargs)

    whole = convert(tmp_path / "memory")
    decoded.clear()
    limit = 3 * 48_000 // 2
    monkeypatch.setattr(wl, "SYNTHESIS_HELD_PCM_BYTES", limit)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", wl.AssemblyGate(lambda: wl.MemoryInfo(1 * GB, 8 * GB), poll_seconds=0.001))
    assert convert(tmp_path / "limited") == whole
    assert [name for name, size in decoded if size >= limit] == []


@needs_ffmpeg
def test_nothing_is_left_in_the_work_folder_after_writing_a_long_paragraph(tmp_path, offline, monkeypatch):
    monkeypatch.setattr(wl, "SYNTHESIS_HELD_PCM_BYTES", 200_000)
    chapters = [{"title": "One", "narrate_title": True,
                 "paragraphs": [" ".join(f"Sentence {n} of it." for n in range(60))]}]
    work = tmp_path / "work"
    work.mkdir()
    parts = engine.read_book(chapters, "v", 850, 800, workdir=str(work))
    assert [Path(part).name for part in parts] == ["part1.flac"]
    assert sorted(p.name for p in work.iterdir()) == ["part1.flac"]


# --------------------------------------------------------------------------- #
# What the disk route really uses
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def long_parts(tmp_path_factory) -> list[Path]:
    """64 MiB of audible audio, in eight files of real FLAC, about 22 minutes."""
    ffmpeg_utils.configure_pydub()
    folder = tmp_path_factory.mktemp("parts")
    rng = np.random.default_rng(1)
    paths = []
    for index in range(8):
        pcm = rng.integers(-3000, 3000, 4 * MB, dtype=np.int16)
        path = folder / f"part{index}.flac"
        AudioSegment(data=pcm.tobytes(), sample_width=2, frame_rate=24000, channels=1).export(path, format="flac")
        paths.append(path)
    return paths


@needs_ffmpeg
def test_a_chapter_joined_on_disk_stays_small_in_memory(tmp_path, long_parts):
    tracemalloc.start()
    try:
        disk_assembly.join_to_flac(long_parts, tmp_path / "out.flac", tmp_path / "spool.wav")
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 4 * MB, f"{peak} bytes to join 64 MiB of audio"
    assert AudioSegment.from_file(tmp_path / "out.flac").duration_seconds == pytest.approx(64 * MB / 48_000, abs=0.1)


@needs_ffmpeg
def test_a_narration_encoded_on_disk_stays_small_in_memory(tmp_path, long_parts):
    tracemalloc.start()
    try:
        disk_assembly.encode_mp3(long_parts, tmp_path / "out.mp3", tmp_path / "spool.wav", bitrate="192k")
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < wl.DISK_ASSEMBLY_BYTES / 2, f"{peak} bytes to encode 64 MiB of audio"
    publication.verify_finished_mp3(tmp_path / "out.mp3", 64 * MB / 48)


@needs_ffmpeg
def test_a_part_in_another_format_is_refused_not_quietly_converted(tmp_path):
    ffmpeg_utils.configure_pydub()
    AudioSegment.silent(duration=100, frame_rate=24000).export(tmp_path / "a.flac", format="flac")
    AudioSegment.silent(duration=100, frame_rate=48000).export(tmp_path / "b.flac", format="flac")
    with pytest.raises(ValueError, match="48000 Hz"):
        disk_assembly.join_to_flac([tmp_path / "a.flac", tmp_path / "b.flac"], tmp_path / "out.flac", tmp_path / "spool.wav")
    assert not (tmp_path / "spool.wav").exists()


def test_the_spool_cleans_up_after_a_failure(tmp_path):
    with pytest.raises(RuntimeError):
        with disk_assembly.WavSpool(tmp_path / "spool.wav") as spool:
            spool.append_segment(AudioSegment.silent(duration=10, frame_rate=24000))
            raise RuntimeError("the assembly failed")
    assert not (tmp_path / "spool.wav").exists()
    shutil.rmtree(tmp_path)  # nothing still holds a file open
