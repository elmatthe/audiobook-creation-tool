"""v0.7.1 — directly imported Edge files convert concurrently, each in its own working folder.

Until v0.7.1 ``runner.run_conversion_job`` ``os.chdir``'d into a private temp folder (the vendored engine wrote bare
relative scratch names), and because the working directory is process-wide a lock serialized every direct Edge
conversion. The engine now takes an explicit ``workdir`` and the runner never changes the working directory.

These tests run the **real** runner and engine — parsing, sentence splitting, PCM assembly, the final-tail policy and
the MP3 encode — and replace only the network request (``run_edgespeak``) with a function that writes a real,
decodable MP3. Overlap is proved with a ``threading.Barrier`` that every conversion must reach from *inside*
synthesis: if any one conversion could not start until another finished, the barrier would break.
"""

from __future__ import annotations

import ast
import contextlib
import io
import os
import threading
from pathlib import Path

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from shared import ffmpeg_utils
from shared.cancellation import ConversionCancelled
from shared import work_area
from tts.epub2tts_edge import epub2tts_edge as engine
from tts.epub2tts_edge import runner

WAIT = 30.0
ENGINE_DIR = Path(engine.__file__).resolve().parent

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_utils.have_ffmpeg(), reason="requires a real ffmpeg/ffprobe pair")


@pytest.fixture(autouse=True)
def _clean_tokenizer(monkeypatch):
    monkeypatch.setattr(engine, "_SENTENCE_TOKENIZER", None, raising=False)


_STUB: dict[str, bytes] = {}


def _clip() -> bytes:
    if "mp3" not in _STUB:
        ffmpeg_utils.configure_pydub()
        buf = io.BytesIO()
        Sine(440, sample_rate=24000).to_audio_segment(duration=90, volume=-20).export(buf, format="mp3")
        _STUB["mp3"] = buf.getvalue()
    return _STUB["mp3"]


class FakeEdge:
    """Stands in for the network request only. Records which working folder every request was written into."""

    def __init__(self, barrier: threading.Barrier | None = None, fail_dirs_of: str | None = None,
                 after_barrier=None):
        self.barrier = barrier
        self.fail_marker = fail_dirs_of
        self.after_barrier = after_barrier
        self.lock = threading.Lock()
        self.requests: list[tuple[str, str]] = []  # (folder, text)
        self.seen: set[str] = set()

    def __call__(self, sentence, speaker, filename):
        folder = os.path.dirname(os.path.abspath(filename))
        first = False
        with self.lock:
            self.requests.append((folder, sentence))
            if folder not in self.seen:
                self.seen.add(folder)
                first = True
        if first and self.barrier is not None:
            self.barrier.wait(WAIT)  # every conversion must be inside synthesis at the same time
            if self.after_barrier is not None:
                self.after_barrier()
        if self.fail_marker and self.fail_marker in sentence:
            raise RuntimeError("simulated synthesis failure")
        Path(filename).write_bytes(_clip())

    def by_folder(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for folder, text in self.requests:
            grouped.setdefault(folder, []).append(text)
        return grouped


def _source(folder: Path, name: str, word: str) -> Path:
    """A small book whose every spoken unit carries *word*, so a request can be traced to its source."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(f"Title: {word}\nAuthor: Nobody\n# {word} heading\n\n"
                    f"{word} begins the first paragraph. {word} ends it.\n\n"
                    f"{word} opens the second paragraph. {word} closes the book.\n", encoding="utf-8")
    return path


def _expected(word: str) -> list[str]:
    return [f"{word} heading", f"{word} begins the first paragraph.", f"{word} ends it.",
            f"{word} opens the second paragraph.", f"{word} closes the book."]


def _run_all(jobs, **kwargs):
    """Run every (source, out_dir) through the real runner on its own thread. Returns {source: result|exception}."""
    outcomes: dict[Path, object] = {}

    def work(source, out_dir):
        try:
            outcomes[source] = runner.run_conversion_job(str(source), output_dir=str(out_dir), audio_format="mp3",
                                                         **kwargs)
        except BaseException as exc:  # noqa: BLE001 - recorded for the assertion
            outcomes[source] = exc

    threads = [threading.Thread(target=work, args=job) for job in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT * 2)
    assert not any(thread.is_alive() for thread in threads), "a conversion never finished"
    return outcomes


def _track_workdirs(monkeypatch) -> list[str]:
    """The runner's own private folders, nobody else's: since v0.7.2 entries of the TTS work area of kind "edge"."""
    made: list[str] = []
    real = work_area.conversion_folder

    @contextlib.contextmanager
    def conversion_folder(kind):
        with real(kind) as folder:
            if kind == "edge":
                made.append(str(folder))
            yield folder

    monkeypatch.setattr(work_area, "conversion_folder", conversion_folder)
    return made


# --------------------------------------------------------------------------- #
# A. No process-wide working-directory change remains
# --------------------------------------------------------------------------- #


def _calls_chdir(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name))
            and (getattr(node.func, "attr", None) == "chdir" or getattr(node.func, "id", None) == "chdir")]


@pytest.mark.parametrize("module", ["runner.py", "epub2tts_edge.py"])
def test_the_edge_engine_never_changes_the_working_directory(module):
    assert _calls_chdir(ENGINE_DIR / module) == [], f"{module} calls chdir"


def test_the_cwd_isolation_lock_is_gone():
    assert not hasattr(runner, "_CWD_ISOLATION_LOCK"), "nothing is left for a process-wide lock to protect"


@needs_ffmpeg
def test_a_conversion_runs_with_chdir_forbidden(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("os.chdir was called during a conversion")

    monkeypatch.setattr(os, "chdir", forbidden)
    fake = FakeEdge()
    monkeypatch.setattr(engine, "run_edgespeak", fake)
    cwd = os.getcwd()
    source = _source(tmp_path / "in", "solo.txt", "Solo")
    result = runner.run_conversion_job(str(source), output_dir=str(tmp_path / "out"), audio_format="mp3")
    assert Path(result).is_file() and Path(result).parent == tmp_path / "out"
    assert os.getcwd() == cwd
    assert [text for _f, text in fake.requests] == _expected("Solo")


# --------------------------------------------------------------------------- #
# B. Real overlap, isolation and cleanup
# --------------------------------------------------------------------------- #


@needs_ffmpeg
@pytest.mark.parametrize("count", [2, 4, 8])
def test_direct_conversions_overlap_inside_synthesis(count, tmp_path, monkeypatch):
    words = [f"Word{chr(65 + i)}" for i in range(count)]
    fake = FakeEdge(barrier=threading.Barrier(count))
    monkeypatch.setattr(engine, "run_edgespeak", fake)
    workdirs = _track_workdirs(monkeypatch)
    jobs = [(_source(tmp_path / "in", f"{w}.txt", w), tmp_path / "out" / w) for w in words]

    outcomes = _run_all(jobs)

    for (source, out_dir), word in zip(jobs, words):
        result = outcomes[source]
        assert isinstance(result, str), f"{source.name}: {result!r}"
        assert Path(result).is_file() and Path(result).parent == out_dir
        assert len(AudioSegment.from_file(result)) > 0
    grouped = fake.by_folder()
    assert len(grouped) == count, "every conversion wrote its requests into its own working folder"
    assert sorted(grouped) == sorted(workdirs), "each folder is the runner's own private folder"
    for texts in grouped.values():
        word = texts[0].split()[0]
        assert texts == _expected(word), "a file's units are complete, in source order, and its own"
    for folder in workdirs:
        assert not os.path.exists(folder), "every private working folder is removed"


@needs_ffmpeg
def test_same_named_sources_from_different_folders_never_share_scratch(tmp_path, monkeypatch):
    fake = FakeEdge(barrier=threading.Barrier(2))
    monkeypatch.setattr(engine, "run_edgespeak", fake)
    first = _source(tmp_path / "Book A", "chapter.txt", "Amber")
    second = _source(tmp_path / "Book B", "chapter.txt", "Basalt")

    outcomes = _run_all([(first, tmp_path / "out-a"), (second, tmp_path / "out-b")])

    assert Path(outcomes[first]).parent == tmp_path / "out-a"
    assert Path(outcomes[second]).parent == tmp_path / "out-b"
    grouped = fake.by_folder()
    assert sorted(texts[0].split()[0] for texts in grouped.values()) == ["Amber", "Basalt"]
    for texts in grouped.values():
        assert texts == _expected(texts[0].split()[0])


@needs_ffmpeg
def test_cancelling_while_conversions_overlap_stops_all_and_leaves_nothing(tmp_path, monkeypatch):
    cancel = threading.Event()
    fake = FakeEdge(barrier=threading.Barrier(4), after_barrier=cancel.set)
    monkeypatch.setattr(engine, "run_edgespeak", fake)
    workdirs = _track_workdirs(monkeypatch)
    jobs = [(_source(tmp_path / "in", f"C{i}.txt", f"Cancel{i}"), tmp_path / "out" / str(i)) for i in range(4)]

    outcomes = _run_all(jobs, cancel_check=cancel.is_set)

    assert all(isinstance(result, ConversionCancelled) for result in outcomes.values()), outcomes
    for _source_path, out_dir in jobs:
        assert not out_dir.exists() or not any(out_dir.iterdir()), "a cancelled conversion publishes nothing"
    assert len(workdirs) == 4 and not any(os.path.exists(folder) for folder in workdirs)


@needs_ffmpeg
def test_one_failing_conversion_does_not_disturb_one_running_beside_it(tmp_path, monkeypatch):
    fake = FakeEdge(barrier=threading.Barrier(2), fail_dirs_of="Broken")
    monkeypatch.setattr(engine, "run_edgespeak", fake)
    workdirs = _track_workdirs(monkeypatch)
    good = _source(tmp_path / "in", "good.txt", "Steady")
    bad = _source(tmp_path / "in", "bad.txt", "Broken")

    outcomes = _run_all([(good, tmp_path / "out-good"), (bad, tmp_path / "out-bad")])

    assert Path(outcomes[good]).is_file()
    assert isinstance(outcomes[bad], RuntimeError)
    assert not (tmp_path / "out-bad").exists() or not any((tmp_path / "out-bad").iterdir())
    assert not any(os.path.exists(folder) for folder in workdirs)


def test_a_conversion_cancelled_before_it_starts_does_no_work(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(runner, "get_book", lambda *a, **k: calls.append("get_book"))
    source = _source(tmp_path / "in", "late.txt", "Late")
    with pytest.raises(ConversionCancelled):
        runner.run_conversion_job(str(source), output_dir=str(tmp_path / "out"), audio_format="mp3",
                                  cancel_check=lambda: True)
    assert calls == []


# --------------------------------------------------------------------------- #
# C. Shared state the concurrent conversions touch
# --------------------------------------------------------------------------- #


def test_the_sentence_tokenizer_is_built_once_under_concurrent_first_use(monkeypatch):
    builds: list[int] = []
    entered = threading.Barrier(8)
    real_ensure = engine.ensure_punkt

    def slow_ensure():
        builds.append(1)
        real_ensure()

    def racer(results):
        entered.wait(WAIT)
        results.append(engine._sentence_tokenizer())

    monkeypatch.setattr(engine, "ensure_punkt", slow_ensure)
    results: list[object] = []
    threads = [threading.Thread(target=racer, args=(results,)) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT)
    assert len(results) == 8 and len({id(r) for r in results}) == 1, "every thread gets the one tokenizer"
    assert len(builds) == 1, "the tokenizer is built exactly once"


class _CountingLock:
    """A lock substitute that announces a second acquire *attempt* before it may block (deterministic contention)."""

    def __init__(self) -> None:
        self._real = threading.Lock()
        self._attempts = 0
        self._guard = threading.Lock()
        self.contended = threading.Event()

    def __enter__(self):
        with self._guard:
            self._attempts += 1
            if self._attempts >= 2:
                self.contended.set()
        self._real.acquire()
        return self

    def __exit__(self, *exc) -> bool:
        self._real.release()
        return False


def test_pymupdf_is_never_used_by_two_threads_at_once(monkeypatch):
    """PyMuPDF documents that it does not support multithreaded use; extraction is serialized, synthesis is not."""
    from tts import pdf_extractor

    inside = {"now": 0, "max": 0}
    probe = threading.Lock()
    entered = threading.Event()
    release = threading.Event()
    counting = _CountingLock()
    monkeypatch.setattr(pdf_extractor, "_PYMUPDF_LOCK", counting)

    class Page:
        def get_text(self, _kind):
            return "A page of text.\n"

    class Doc:
        def __iter__(self):
            with probe:
                inside["now"] += 1
                inside["max"] = max(inside["max"], inside["now"])
            entered.set()
            assert release.wait(WAIT)
            with probe:
                inside["now"] -= 1
            return iter([Page()])

        def close(self):
            pass

    monkeypatch.setattr(pdf_extractor.fitz, "open", lambda path: Doc())
    texts: list[str] = []
    first = threading.Thread(target=lambda: texts.append(pdf_extractor.extract_text_from_pdf("a.pdf")))
    second = threading.Thread(target=lambda: texts.append(pdf_extractor.extract_text_from_pdf("b.pdf")))
    first.start()
    try:
        assert entered.wait(WAIT)
        second.start()
        assert counting.contended.wait(WAIT), "the second extraction never reached the PyMuPDF lock"
        assert inside["max"] == 1, "two threads were inside PyMuPDF at once"
    finally:
        release.set()
        first.join(WAIT)
        second.join(WAIT)
    assert inside["max"] == 1 and texts == ["A page of text.", "A page of text."]


@pytest.mark.skipif(not ffmpeg_utils.have_ffmpeg(), reason="kept beside the other real-engine tests")
def test_concurrent_real_pdf_extraction_returns_each_documents_own_text(tmp_path):
    from tts import pdf_extractor

    fitz = pdf_extractor.fitz
    paths = []
    for index in range(4):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), f"Document number {index} speaks only of itself.")
        path = tmp_path / f"doc{index}.pdf"
        doc.save(str(path))
        doc.close()
        paths.append(path)
    results: dict[int, str] = {}
    barrier = threading.Barrier(4)

    def extract(index):
        barrier.wait(WAIT)
        results[index] = pdf_extractor.extract_text_from_pdf(str(paths[index]))

    threads = [threading.Thread(target=extract, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT)
    assert results == {i: f"Document number {i} speaks only of itself." for i in range(4)}
