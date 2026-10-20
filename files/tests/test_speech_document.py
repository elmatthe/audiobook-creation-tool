"""Plan 01B checkpoint A1: the shared structure loader is byte-identical to the per-engine loops it replaced.

``REFERENCE_*`` below are verbatim copies of the loops that lived inside ``kokoro_file_to_mp3``, ``chatterbox_file_to_mp3``
and ``qwen3_synth.prepare_text`` before A1. Equivalence is proven against them on the quality corpus, on hand-picked edge
cases and on a seeded randomized generator of headers, headings, blank lines and Unicode. The engine-specific differences
(Qwen3's heading-as-paragraph, Edge folder's untouched text) are pinned as differences, not unified.
"""

from __future__ import annotations

import ast
import random
from pathlib import Path

import pytest

from tts import qwen3_synth
from tts.speech import document
from tts.speech.document import (HEADING_PARAGRAPH_STRUCTURE, LOCAL_ENGINE_STRUCTURE, RAW_STRUCTURE, StructureOptions,
                                 load_speech_text, parse_structure, read_source_text)

SPEECH_DIR = Path(document.__file__).parent


def reference_local(raw_text: str) -> str:
    """Kokoro and Chatterbox, as they were."""
    content_lines: list[str] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Title:") or stripped.startswith("Author:"):
            continue
        if stripped.startswith("#"):
            content_lines.append(stripped.lstrip("#").strip())
        else:
            content_lines.append(line)
    return "\n".join(content_lines).strip()


def reference_qwen3(raw_text: str) -> str:
    """Qwen3 ``prepare_text``, as it was."""
    lines: list[str] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Title:") or stripped.startswith("Author:"):
            continue
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                lines.extend(["", heading, ""])
            continue
        lines.append(line)
    return "\n".join(lines).strip()


EDGE_CASES = [
    "",
    "\n\n\n",
    "   \n\t\n",
    "Title: T\nAuthor: A\n",
    "Title: T\nAuthor: A\n\n# Chapter One\n\nIt was a dark night.\n",
    "# \n\nbody",                       # an empty heading
    "#\n#\n# x\n",
    "### Deep heading ###\ntext",
    "  # indented heading\n    indented body\n",
    "Title:no space\nAuthor:none\nbody",
    "title: lower case is body\nTITLE: so is this",
    "Not a Title: header\nbody with # inside",
    "line one\r\nline two\r\n\r\nline three\r",
    "café “quoted” — 日本語 \U0001F600\n# Überschrift\nÜber",
    "one two\u000bthree\u000cfour\n# h\nfive",   # str.splitlines separators beyond \n
    "body\n\n\n\n# h\n\n\n\nbody",
    "# first\nbody\n# second\nbody\n",
]


def random_documents(count: int = 300, seed: int = 20260420) -> list[str]:
    rng = random.Random(seed)
    pieces = ["Title: A Book", "Author: Someone", "# Heading", "## Sub heading", "#", "# ", "Plain sentence one.",
              "  indented text", "", "", "   ", "café über", "日本語", "Title:x", "x # y", "Dr. Smith said: hi."]
    seps = ["\n", "\r\n", "\n\n", "\r"]
    docs = []
    for _ in range(count):
        parts = [rng.choice(pieces) for _ in range(rng.randint(0, 12))]
        text = "".join(p + rng.choice(seps) for p in parts)
        docs.append(text if rng.random() < 0.8 else text.rstrip("\r\n"))
    return docs


def quality_corpus_texts() -> list[str]:
    from tts import quality_corpus

    items = list(quality_corpus.ALL_ITEMS)
    texts = [item.text for item in items]
    return texts + [f"Title: Corpus\nAuthor: Test\n\n# {item.name}\n\n{item.text}" for item in items]


ALL_TEXTS = EDGE_CASES + random_documents() + quality_corpus_texts()


# --------------------------------------------------------------------------- #
# Equivalence with the loops the engines used to carry
# --------------------------------------------------------------------------- #
def test_the_corpus_is_not_trivially_small():
    assert len(ALL_TEXTS) > 300 and len(quality_corpus_texts()) >= 4


@pytest.mark.parametrize("index", range(len(ALL_TEXTS)))
def test_local_engine_structure_is_byte_identical_to_the_old_kokoro_and_chatterbox_loop(index):
    raw = ALL_TEXTS[index]
    assert parse_structure(raw, LOCAL_ENGINE_STRUCTURE).text == reference_local(raw)
    assert parse_structure(raw).text == reference_local(raw)  # it is the default


@pytest.mark.parametrize("index", range(len(ALL_TEXTS)))
def test_heading_paragraph_structure_is_byte_identical_to_the_old_qwen3_prepare_text(index):
    raw = ALL_TEXTS[index]
    assert parse_structure(raw, HEADING_PARAGRAPH_STRUCTURE).text == reference_qwen3(raw)
    assert qwen3_synth.prepare_text(raw) == reference_qwen3(raw)  # the engine's public function is unchanged


@pytest.mark.parametrize("index", range(len(ALL_TEXTS)))
def test_raw_structure_hands_the_text_over_untouched(index):
    raw = ALL_TEXTS[index]
    document_ = parse_structure(raw, RAW_STRUCTURE)
    assert document_.text == raw and [b.kind for b in document_.blocks] == [document.RAW]


# --------------------------------------------------------------------------- #
# Decoding
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_a_bom_is_a_signature_not_text(tmp_path, encoding):
    path = tmp_path / "s.txt"
    path.write_bytes("Title: T\n# Überschrift\n\nBody café.\n".encode(encoding))
    assert read_source_text(path) == "Title: T\n# Überschrift\n\nBody café.\n"
    loaded = load_speech_text(path)
    assert loaded.text == "Überschrift\n\nBody café." and "﻿" not in loaded.text
    assert [b.kind for b in loaded.blocks][0] == document.METADATA  # the BOM did not hide the Title: line


def test_an_empty_file_gives_an_empty_document(tmp_path):
    path = tmp_path / "e.txt"
    path.write_bytes(b"")
    loaded = load_speech_text(path)
    assert loaded.text == "" and loaded.blocks == ()


def test_a_missing_file_raises_rather_than_returning_empty(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_speech_text(tmp_path / "nope.txt")


# --------------------------------------------------------------------------- #
# Typed structure, and the differences that are preserved on purpose
# --------------------------------------------------------------------------- #
def test_blocks_keep_what_was_a_header_a_heading_and_body():
    doc = parse_structure("Title: T\nAuthor: A\n\n# Chapter\nIt rained.\n", LOCAL_ENGINE_STRUCTURE)
    assert [(b.kind, b.text) for b in doc.blocks] == [
        (document.METADATA, "Title: T"), (document.METADATA, "Author: A"), (document.LINE, ""),
        (document.HEADING, "Chapter"), (document.LINE, "It rained."),
    ]
    assert doc.text == "Chapter\nIt rained."


def test_only_qwen3_makes_a_heading_a_paragraph_of_its_own():
    raw = "# Chapter\nIt rained.\n"
    assert parse_structure(raw, LOCAL_ENGINE_STRUCTURE).text == "Chapter\nIt rained."
    assert parse_structure(raw, HEADING_PARAGRAPH_STRUCTURE).text == "Chapter\n\nIt rained."


def test_an_empty_heading_differs_by_engine_as_it_does_today():
    raw = "before\n#\nafter"
    assert parse_structure(raw, LOCAL_ENGINE_STRUCTURE).text == "before\n\nafter"      # an empty line stays
    assert parse_structure(raw, HEADING_PARAGRAPH_STRUCTURE).text == "before\nafter"   # the heading disappears


def test_edge_folder_still_speaks_marker_lines_as_written():
    raw = "Title: T\n# Chapter\nBody\n"
    assert parse_structure(raw, RAW_STRUCTURE).text == raw


def test_options_default_to_the_local_engine_behaviour():
    assert StructureOptions() == LOCAL_ENGINE_STRUCTURE
    assert LOCAL_ENGINE_STRUCTURE != HEADING_PARAGRAPH_STRUCTURE != RAW_STRUCTURE


def test_blank_lines_and_paragraph_spacing_are_preserved_inside_the_text():
    raw = "a\n\n\n\nb\n   \nc"
    assert parse_structure(raw).text == reference_local(raw) == "a\n\n\n\nb\n   \nc"


# --------------------------------------------------------------------------- #
# Call sites and boundary
# --------------------------------------------------------------------------- #
def test_the_engines_no_longer_carry_a_private_copy_of_the_marker_loop():
    tts_dir = SPEECH_DIR.parent
    for name in ("kokoro_synth.py", "chatterbox_synth.py", "qwen3_synth.py"):
        tree = ast.parse((tts_dir / name).read_text(encoding="utf-8"))
        offenders = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "startswith" and n.args and isinstance(n.args[0], ast.Constant)
                     and n.args[0].value in ("Title:", "Author:")]
        assert not offenders, f"{name} re-implements the Title:/Author: rule at {offenders}; use tts.speech.document"


def test_the_speech_package_is_standard_library_only_and_imports_no_engine_or_ui():
    for path in SPEECH_DIR.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = ([a.name for a in node.names] if isinstance(node, ast.Import)
                       else [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
            for module in modules:
                root = module.split(".")[0]
                assert root in {"__future__", "dataclasses", "pathlib", "typing"}, f"{path.name} imports {module}"


def test_edge_get_book_reads_the_same_lines_through_the_shared_decode(tmp_path):
    """``get_book`` iterates a StringIO of the shared decode where it used to iterate the open file."""
    import io

    from tts.epub2tts_edge import epub2tts_edge as edge

    for index, raw in enumerate(ALL_TEXTS[:120]):
        path = tmp_path / f"d{index}.txt"
        path.write_bytes(b"\xef\xbb\xbf" * (index % 2) + raw.encode("utf-8"))
        with open(path, "r", encoding="utf-8-sig") as handle:
            old_lines = list(handle)
        assert list(io.StringIO(read_source_text(path))) == old_lines, index
    path = tmp_path / "book.txt"
    path.write_bytes("\ufeffTitle: B\nAuthor: A\n\n# One\n\nFirst. Second.\n".encode("utf-8"))
    contents, title, author, chapter_titles = edge.get_book(str(path))
    assert (title, author, chapter_titles) == ("B", "A", ["One"])
    assert contents[0]["paragraphs"] == ["First. Second."]
