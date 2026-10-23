"""A0 characterization of the five TTS text routes (dev-only; never shipped, never imported by the app).

Plan 01B (``files/plans/ACT-v0.6.7-Plan-01B-Text-Pipeline-and-Script-Layout.md``, correction 3) requires the
text-processing behaviour of the ORIGINAL implementation to be recorded before any directory moves, so that the
mechanical relocation (B1) and every later pure-refactor checkpoint can prove they changed no text path.

What is recorded, per route, for a fixed set of inputs: the decoded and structured text, paragraphs, sentence and
sub-chunk splits, chunks and their boundaries, the exact strings handed to the engine entry point, the text the pinned
Chatterbox wheel would receive after ACT's structural-colon ``punc_norm``, the pause arithmetic that surrounds each
chunk, and Qwen3's ordered source spans and per-chunk seeds.

These are text/chunk/seed baselines, **not audio**. Every engine call is replaced by a recording fake: nothing is
synthesised, no model is loaded and no network connection is opened (the tool refuses to run if one is attempted).

    python files/dev-tools/speech_characterization.py write     # regenerate the goldens (only on purpose)
    python files/dev-tools/speech_characterization.py check     # compare against the stored goldens (exit 1 on a diff)

The goldens live in ``files/tests/golden/speech/`` (``files/test-files/`` is gitignored local-fixture space) and are checked by ``files/tests/test_speech_characterization.py``.
The import root is discovered, so the same tool runs before and after the ``scripts/Universal`` -> ``scripts`` move.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import socket
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPO_ROOT / "files" / "tests" / "golden" / "speech"
ROUTES = ("extraction", "edge_direct", "edge_folder", "kokoro", "chatterbox", "qwen3")
SCHEMA = 1

#: A list of strings longer than this (total characters) is stored as per-item length + SHA-256 instead of verbatim.
VERBATIM_LIMIT = 6000


def import_root() -> Path:
    """The folder that holds the ``shared`` and ``tts`` packages (``scripts/Universal`` before checkpoint B1)."""
    for candidate in (REPO_ROOT / "scripts", REPO_ROOT / "scripts" / "Universal"):
        if (candidate / "shared" / "paths.py").is_file():
            return candidate
    raise RuntimeError("could not find the application's import root")


def _ensure_importable() -> None:
    root = str(import_root())
    if root not in sys.path:
        sys.path.insert(0, root)


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
STRUCTURE = (
    "Title: The Lighthouse Log\n"
    "Author: A. Writer\n"
    "\n"
    "# Chapter One\n"
    "\n"
    "It was 6:45 when the ferry arrived. Mr. Okafor waved.\n"
    "\n"
    "Second paragraph here; it has a semicolon, a comma, and a dash — like this.\n"
    "Title: this line is not a header once the body has started\n"
    "Author: neither is this one\n"
    "\n"
    "# \n"
    "\n"
    "# Chapter Two: The Return\n"
    "\n"
    "   Indented paragraph with trailing spaces.   \n"
    "\n"
    "...\n"
    "---\n"
    "Final line without terminal punctuation"
)

PUNCTUATION = (
    "“I still don’t believe it,” she said... “Are you coming up, or not?” Dr. Marsh checked the log "
    "(found beneath the door) again!! Really?? Yes.\n"
    "\n"
    "The ratio was 3:1 at 6:45 and 7:15, i.e. late; e.g. very late. See https://example.com/lighthouse-log for "
    "details. Note: the beam slowed by 2.5 degrees. It cost $12.50, or 1,250 pennies, up 15% since March 5, 2024. "
    "J. R. Alvarez vs. Prof. Whitfield: no.\n"
    "\n"
    "Em—dash and double--hyphen and en–dash. ‘Single’ quotes, an ellipsis… and 10 km "
    "with a non-breaking space. Is 12:30 p.m. late? Version 1.2.3 shipped; the 2nd of May; page 12-15."
)

#: Deterministic filler (no randomness) for ceiling behaviour.
_SENTENCE = "The keeper climbed the spiral stairs and counted every single step aloud"
OVERSIZED = (
    "\n".join(f"{_SENTENCE}, number {n}." for n in range(1, 41))
    + "\n\n"
    + ("a long clause that keeps going, and going; and then, once more: " * 12).strip() + " It ends here.\n\n"
    + "Short closing paragraph."
)

#: A single token longer than the largest engine ceiling in play (Qwen3 600) to record each engine's failure mode.
UNBROKEN_TOKEN = "Before " + "x" * 700 + " after."

#: A PDF-page-shaped string for the extraction helpers.
PDF_PAGE = (
    "Chapter 3\n\n"
    "The harbour was quiet that morn-\ning, and the lamp-room door stood\n"
    "open. 12\n\n"
    "IV\n\n"
    "She counted the steps again\nand wrote them down.\n\n"
    "A second block that does not end a sentence\n\n"
    "and continues after a page gap.\n"
)


def corpus() -> dict[str, str]:
    """Name -> text for every characterization input (decoded text; files add a BOM where noted)."""
    _ensure_importable()
    from tts import quality_corpus as qc

    inputs = {
        "structure": STRUCTURE,
        "punctuation": PUNCTUATION,
        "oversized": OVERSIZED,
        "unbroken_token": UNBROKEN_TOKEN,
    }
    for item in qc.ALL_ITEMS:
        inputs[f"qc_{item.name}"] = item.text
    return inputs


#: Inputs written to disk with a UTF-8 BOM (the documented UTF-8-with-BOM TXT contract).
BOM_INPUTS = frozenset({"structure"})


def input_manifest() -> dict:
    return {name: {"chars": len(text), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                   "bom_on_disk": name in BOM_INPUTS}
            for name, text in sorted(corpus().items())}


def write_input(directory: Path, name: str, text: str) -> Path:
    path = directory / f"{name}.txt"
    path.write_bytes((b"\xef\xbb\xbf" if name in BOM_INPUTS else b"") + text.encode("utf-8"))
    return path


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def pack(items: list[str]) -> dict:
    """A list of strings, verbatim when short, otherwise as lengths and digests (plus the first and last item)."""
    total = sum(len(i) for i in items)
    if total <= VERBATIM_LIMIT:
        return {"n": len(items), "items": list(items)}
    return {"n": len(items), "chars": total, "lens": [len(i) for i in items],
            "sha256": [hashlib.sha256(i.encode("utf-8")).hexdigest() for i in items],
            "first": items[0], "last": items[-1]}


def attempt(fn, *args, **kwargs):
    """The function's result, or a record of the failure (a failure mode is part of the behaviour)."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return {"error": type(exc).__name__, "message": str(exc)[:300]}


@contextlib.contextmanager
def no_network():
    """Refuse every network attempt for the duration of a collection."""
    def refuse(*args, **kwargs):
        raise AssertionError("the characterization tool must not open a network connection")

    # Not ``socket.connect``: on Windows asyncio builds its self-pipe with a loopback ``connect``, and the Edge route
    # runs the production ``parallel_edgespeak`` (asyncio) around a recording fake.
    import urllib.request

    import edge_tts

    with mock.patch.object(socket, "create_connection", refuse), mock.patch.object(socket, "getaddrinfo", refuse), \
            mock.patch.object(urllib.request, "urlopen", refuse), mock.patch.object(edge_tts, "Communicate", refuse):
        yield


@contextlib.contextmanager
def quiet():
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


@contextlib.contextmanager
def working_directory(path: Path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


# --------------------------------------------------------------------------- #
# Route: extraction helpers shared by the PDF paths
# --------------------------------------------------------------------------- #
def collect_extraction() -> dict:
    _ensure_importable()
    from tts import pdf_extractor as pdf
    from tts.epub2tts_edge import runner

    out = {
        "clean_page_text": pdf._clean_page_text(PDF_PAGE),
        "dehyphenate": pdf._dehyphenate(PDF_PAGE),
        "rejoin_soft_wrapped": pdf._rejoin_soft_wrapped_lines(PDF_PAGE),
        "strip_noise_lines": pdf._strip_noise_lines(PDF_PAGE),
        "merge_blocks_across_page_gaps": pdf._merge_blocks_across_page_gaps(PDF_PAGE),
    }
    with tempfile.TemporaryDirectory(prefix="speech_char_") as tmp:
        for label, body in (("no_heading", "Opening Title Line\n\nThe first paragraph is here.\n\nAnother follows.\n"),
                            ("has_heading", "# Existing Heading\n\nBody text.\n"),
                            ("empty", "")):
            path = Path(tmp) / f"{label}.txt"
            path.write_text(body, encoding="utf-8")
            runner._ensure_pdf_txt_has_chapter_heading(str(path))
            out[f"ensure_chapter_heading_{label}"] = path.read_text(encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# Route: Edge direct/rich (get_book + read_book with a recording fake for the network and the audio layer)
# --------------------------------------------------------------------------- #
def _edge_read_book(engine, book_contents: list[dict]) -> dict:
    from pydub import AudioSegment
    from pydub.generators import Sine

    spoken: list[dict] = []
    durations: dict[str, int] = {}
    exports: list[dict] = []

    def fake_run_edgespeak(sentence, speaker, filename):
        spoken.append({"file": os.path.basename(filename), "speaker": speaker, "text": sentence})
        Path(filename).write_bytes(b"")  # read_book tests for sntnc0.mp3 and removes the sub-chunk files

    def fake_from_file(cls, file, *args, **kwargs):
        name = os.path.basename(str(file))
        return Sine(440).to_audio_segment(duration=durations.get(name, 100), volume=-12)

    def fake_export(self, out_f=None, format=None, **kwargs):
        name = os.path.basename(str(out_f))
        durations[name] = len(self)
        exports.append({"file": name, "format": format, "ms": len(self)})
        Path(str(out_f)).write_bytes(b"")
        return None

    with tempfile.TemporaryDirectory(prefix="speech_char_edge_") as tmp, working_directory(Path(tmp)), quiet():
        with mock.patch.object(engine, "run_edgespeak", fake_run_edgespeak), \
                mock.patch.object(AudioSegment, "from_file", classmethod(fake_from_file)), \
                mock.patch.object(AudioSegment, "export", fake_export):
            files = engine.read_book(book_contents, "en-US-SteffanNeural", 850, 800,
                                     title_trailing_pause=engine.DEFAULT_TITLE_PAUSE_MS,
                                     chapter_trailing_pause=engine.DEFAULT_CHAPTER_PAUSE_MS,
                                     end_of_book_pause=engine.DEFAULT_END_OF_BOOK_PAUSE_MS)
    return {"files": files, "spoken": spoken, "exports": exports}


def collect_edge_direct() -> dict:
    _ensure_importable()
    from tts.epub2tts_edge import epub2tts_edge as engine

    engine._SENTENCE_TOKENIZER = None  # the cached tokenizer must be rebuilt from NLTK's own model, as in a fresh process
    out: dict = {
        "constants": {
            "sentence_pause_ms": engine.DEFAULT_SENTENCE_PAUSE_MS, "paragraph_pause_ms": engine.DEFAULT_PARAGRAPH_PAUSE_MS,
            "title_pause_ms": engine.DEFAULT_TITLE_PAUSE_MS, "chapter_pause_ms": engine.DEFAULT_CHAPTER_PAUSE_MS,
            "end_of_book_pause_ms": engine.DEFAULT_END_OF_BOOK_PAUSE_MS, "comma_pause_ms": engine.COMMA_PAUSE_MS,
            "ellipsis_pause_ms": engine.ELLIPSIS_PAUSE_MS, "em_dash_pause_ms": engine.EM_DASH_PAUSE_MS,
        },
        "inputs": {},
    }
    with tempfile.TemporaryDirectory(prefix="speech_char_in_") as tmp:
        for name, text in sorted(corpus().items()):
            path = write_input(Path(tmp), name, text)
            book_contents, title, author, chapter_titles = engine.get_book(str(path))
            record = {
                "title": title if title != str(path) else "<source file path>", "author": author,
                "chapter_titles": chapter_titles,
                "chapters": [{"title": c["title"], "paragraphs": pack(c["paragraphs"])} for c in book_contents],
            }
            sentences, subs = [], []
            for chapter in book_contents:
                for paragraph in chapter["paragraphs"]:
                    for sentence in engine.sent_tokenize(paragraph):
                        sentences.append(sentence)
                        subs.append([[t, p] for t, p in engine.intra_sentence_chunks(sentence)])
            record["sentences"] = pack(sentences)
            record["intra_sentence_chunks"] = {"n": len(subs), "digest": hashlib.sha256(
                json.dumps(subs, ensure_ascii=False).encode("utf-8")).hexdigest(),
                "items": subs if sum(len(s) for s in sentences) <= VERBATIM_LIMIT else None}
            if name not in ("qc_longer_stress", "qc_sustained_narration"):
                book = _edge_read_book(engine, book_contents)
                record["read_book"] = {
                    "files": book["files"],
                    "spoken": pack([f"{s['file']}|{s['text']}" for s in book["spoken"]]),
                    "exports": book["exports"],
                }
            out["inputs"][name] = record
    return out


# --------------------------------------------------------------------------- #
# Route: Edge folder/batch
# --------------------------------------------------------------------------- #
def collect_edge_folder() -> dict:
    _ensure_importable()
    from tts import batch_convert as bc

    out: dict = {"constants": {"chunk_target": bc.CHUNK_TARGET, "chunk_pause_ms": bc.CHUNK_PAUSE_MS,
                               "end_silence_ms": bc.END_RECORDING_SILENCE_MS}, "inputs": {}}
    with tempfile.TemporaryDirectory(prefix="speech_char_in_") as tmp:
        for name, text in sorted(corpus().items()):
            source = write_input(Path(tmp), name, text)
            record = {"split_default": pack(bc.split_into_chunks(text)),
                      "split_400": pack(bc.split_into_chunks(text, 400))}
            sent: list[str] = []
            merged: list[int] = []

            def fake_synth(chunk, path, voice, rate, _sent=sent):
                _sent.append(chunk)
                Path(path).write_bytes(b"")

            def fake_merge(chunk_paths, output_path, bitrate=None, _merged=merged):
                _merged.append(len(chunk_paths))

            output_dir = Path(tmp) / f"out_{name}"
            output_dir.mkdir()
            with quiet(), mock.patch.object(bc, "synthesize_chunk_mp3", fake_synth), \
                    mock.patch.object(bc, "merge_mp3s", fake_merge), mock.patch.object(bc.time, "sleep", lambda s: None):
                status = bc.convert_single_pdf(source, output_dir, "en-US-SteffanNeural", "+0%",
                                               log=lambda m: None, out_mp3=output_dir / "x.mp3")
            record["convert_single_pdf"] = {"status": status[0], "engine_chunks": pack(sent), "merged_files": merged}
            out["inputs"][name] = record
    return out


# --------------------------------------------------------------------------- #
# Route: Kokoro
# --------------------------------------------------------------------------- #
def collect_kokoro() -> dict:
    import numpy as np

    _ensure_importable()
    from tts import kokoro_synth as ks

    out: dict = {"constants": {"sample_rate": ks.SAMPLE_RATE}, "inputs": {}}
    with tempfile.TemporaryDirectory(prefix="speech_char_in_") as tmp:
        for name, text in sorted(corpus().items()):
            source = write_input(Path(tmp), name, text)
            calls: list[dict] = []
            exported: list[dict] = []

            def fake_pipeline(chunk, voice=None, speed=None, split_pattern=None, _calls=calls):
                import re

                _calls.append({"text": chunk, "voice": voice, "speed": speed, "split_pattern": split_pattern})
                for piece in re.split(split_pattern, chunk) if split_pattern else [chunk]:
                    if piece.strip():
                        yield None, None, np.zeros(1200, dtype="float32")  # 50 ms at 24 kHz

            def fake_export(arr, sample_rate, output_path, bitrate=None, log=None, _exported=exported):
                _exported.append({"samples": int(len(arr)), "sample_rate": sample_rate})

            with quiet(), mock.patch.object(ks, "_get_pipeline", lambda lang_code: fake_pipeline), \
                    mock.patch.object(ks, "_export_mp3", fake_export):
                result = attempt(ks.kokoro_file_to_mp3, str(source), str(Path(tmp) / f"{name}.mp3"), "af_heart",
                                 1.0, 3000, 50)
            out["inputs"][name] = {
                "split_default": pack(ks.split_into_chunks(text)),
                "split_400": pack(ks.split_into_chunks(text, 400)),
                "engine_calls": {"n": len(calls), "voice_speed_split": sorted({(c["voice"], c["speed"], c["split_pattern"])
                                                                               for c in calls}),
                                 "texts": pack([c["text"] for c in calls])},
                "assembled": exported, "result": result,
            }
    return out


# --------------------------------------------------------------------------- #
# Route: Chatterbox Turbo
# --------------------------------------------------------------------------- #
def collect_chatterbox() -> dict:
    import numpy as np

    _ensure_importable()
    from tts import chatterbox_synth as cb

    out: dict = {"constants": {"max_chunk_chars": cb.CHATTERBOX_MAX_CHUNK_CHARS, "colon_pause_ms": cb.COLON_PAUSE_MS},
                 "inputs": {}}
    with tempfile.TemporaryDirectory(prefix="speech_char_in_") as tmp:
        for name, text in sorted(corpus().items()):
            source = write_input(Path(tmp), name, text)
            generated: list[str] = []
            exported: list[dict] = []

            class FakeModel:
                sr = 24000

                def generate(self, chunk, **kwargs):
                    generated.append(chunk)
                    return np.full(2400, 0.02, dtype="float32")  # 100 ms

            def fake_export(arr, sample_rate, output_path, bitrate=None, log=None, _exported=exported):
                _exported.append({"samples": int(len(arr)), "sample_rate": sample_rate})

            model = FakeModel()
            with quiet(), mock.patch.object(cb, "get_reference_voice", lambda voice_id: types.SimpleNamespace(label="Test voice")), \
                    mock.patch.object(cb, "_get_model", lambda device=None: model), \
                    mock.patch.object(cb, "load_conditionals", lambda *a, **k: None), \
                    mock.patch.object(cb, "_export_mp3", fake_export):
                result = attempt(cb.chatterbox_file_to_mp3, str(source), str(Path(tmp) / f"{name}.mp3"),
                                 "chatterbox-female-1", 3000, 50)
            planned = attempt(cb.split_for_chatterbox, text)
            out["inputs"][name] = {
                "split_default": pack(planned) if isinstance(planned, list) else planned,
                "split_120": (lambda r: pack(r) if isinstance(r, list) else r)(attempt(cb.split_for_chatterbox, text, 120)),
                "prose_colon_segments": pack([seg for chunk in (planned if isinstance(planned, list) else [])
                                              for seg in cb.split_at_prose_colon(chunk)]),
                "generate_calls": pack(generated),
                "after_structural_colon_punc_norm": pack([cb._structural_colon_punc_norm(g) for g in generated]),
                "assembled": exported, "result": result,
            }
    return out


# --------------------------------------------------------------------------- #
# Route: Qwen3
# --------------------------------------------------------------------------- #
QWEN3_VOICES_CHARACTERIZED = ("qwen3-aiden", "qwen3-ryan", "qwen3-female-1")


def collect_qwen3() -> dict:
    import numpy as np

    _ensure_importable()
    from tts import qwen3_synth as qs

    out: dict = {"constants": {"max_chunk_chars": qs.QWEN3_MAX_CHUNK_CHARS if hasattr(qs, "QWEN3_MAX_CHUNK_CHARS") else None,
                               "pipeline_revision": qs.PIPELINE_REVISION, "seed_base": qs.SEED_BASE}, "inputs": {}}
    for name, text in sorted(corpus().items()):
        prepared = qs.prepare_text(text)
        record: dict = {"prepared": pack([prepared])}
        for label, max_chars in (("default", qs.QWEN3_MAX_CHUNK_CHARS), ("200", 200)):
            planned = attempt(qs.plan_chunks, prepared, max_chars)
            if isinstance(planned, dict):
                record[f"plan_{label}"] = planned
                continue
            record[f"plan_{label}"] = {
                "n": len(planned), "boundaries": [c.boundary for c in planned],
                "paragraphs": [c.paragraph for c in planned], "spans": [[c.start, c.end] for c in planned],
                "texts": pack([c.text for c in planned]),
            }
            if label == "default":
                record["seeds"] = {voice: [qs.derive_seed(voice, c) for c in planned] for voice in QWEN3_VOICES_CHARACTERIZED}
                if sum(len(c.text) for c in planned) <= VERBATIM_LIMIT:
                    record["chunks"] = [c.to_dict() for c in planned]
        out["inputs"][name] = record
    arrays = [np.ones(100, dtype="float32"), np.ones(250, dtype="float32")]
    pcm, report = qs.assemble(arrays, 24000, chunk_pause_ms=50, end_silence_ms=3000)
    out["assembly_policy"] = {"report": report, "total_samples": int(pcm.size)}
    return out


# --------------------------------------------------------------------------- #
# Whole collection
# --------------------------------------------------------------------------- #
COLLECTORS = {
    "extraction": collect_extraction, "edge_direct": collect_edge_direct, "edge_folder": collect_edge_folder,
    "kokoro": collect_kokoro, "chatterbox": collect_chatterbox, "qwen3": collect_qwen3,
}


def collect(route: str) -> dict:
    with no_network():
        return {"schema": SCHEMA, "route": route, "data": COLLECTORS[route]()}


def collect_manifest() -> dict:
    return {"schema": SCHEMA, "inputs": input_manifest(), "routes": list(ROUTES),
            "note": "Text/chunk/seed baselines captured from the original implementation; no audio, no synthesis, no network."}


def to_json(data: dict) -> str:
    return json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def golden_path(route: str) -> Path:
    return GOLDEN_DIR / f"{route}.json"


def write_all() -> list[Path]:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for route in ROUTES:
        path = golden_path(route)
        path.write_text(to_json(collect(route)), encoding="utf-8", newline="\n")
        written.append(path)
    manifest = GOLDEN_DIR / "MANIFEST.json"
    manifest.write_text(to_json(collect_manifest()), encoding="utf-8", newline="\n")
    return written + [manifest]


def check_all() -> list[str]:
    problems = []
    for route in ROUTES:
        path = golden_path(route)
        if not path.is_file():
            problems.append(f"{route}: golden file missing")
        elif json.loads(path.read_text(encoding="utf-8")) != json.loads(to_json(collect(route))):
            problems.append(f"{route}: output differs from the stored golden")
    return problems


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "check"
    if command == "write":
        for path in write_all():
            print("wrote", path.relative_to(REPO_ROOT).as_posix())
        return 0
    problems = check_all()
    for problem in problems:
        print("PROBLEM:", problem)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
