"""v0.6.1 Plan 4 Phase 5 — EPUB is retired from production, and archived for reference.

The maintainer's 2026-08-11 decision (drop §1.2) removes EPUB as an application
input. PDF and TXT are the only TTS input types, for direct selection, folder
traversal, dialog filters, dispatch and retry alike.

**These guards are deliberately narrow about *where* they look.** The word "epub"
survives legitimately in three places and a bare repository-wide substring
prohibition would fail on every one of them:

* ``files/archived-code/epub-tts/`` — the permanent reference archive, whose whole
  purpose is to still contain the retired code;
* the historical record (``Changelog.md``, ``Decisions.md``, ``don't-delete/``,
  ``files/release-history/``) — append-only documents that must never be rewritten;
* the surviving package **names** ``epub2tts_edge`` / ``epub2tts_gui``, which are the
  upstream project's names and carry this project's GPL-3.0 lineage. Phase 5 chose
  not to rename them (drop §4.4, "On renaming"), so a path containing ``epub2tts``
  proves nothing about whether the code behind it is EPUB-specific.

So the production guards work by **AST** over an explicit allow-list of production
files, and by extension/dialog inspection — never by scanning the repository for a
string.
"""

from __future__ import annotations

import ast
import importlib.metadata as importlib_metadata
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
TTS = UNIVERSAL / "tts"
SHARED = UNIVERSAL / "shared"
FILES = REPO_ROOT / "files"
ARCHIVE = FILES / "archived-code" / "epub-tts"
REQUIREMENTS = REPO_ROOT / "scripts" / "requirements.txt"
README = REPO_ROOT / "README.md"

#: The final active commit the archive was taken from — Phase 4's remediation.
ARCHIVE_SOURCE_SHA = "3d9de97e7befc27fa22210bdcc27f174aa594883"

#: Every production file Phase 5 touched or had to reason about. The guards below
#: run over exactly these; nothing outside ``scripts/`` is ever scanned for the word.
PRODUCTION_TTS_SOURCES = (
    "tts/epub2tts_gui.py",
    "tts/epub2tts_edge/epub2tts_edge.py",
    "tts/epub2tts_edge/runner.py",
    "tts/epub2tts_edge/__init__.py",
    "tts/__init__.py",
    "tts/batch_convert.py",
    "tts/pdf_extractor.py",
    "tts/kokoro_synth.py",
    "tts/voice_registry.py",
    "tts/generate_voice_samples.py",
    # Added by v0.6.1 Plan 4 Phase 8. Listing it here puts the new engine module
    # in scope for every EPUB-retirement guard below, which is the point: a new
    # production TTS module must not be a place EPUB can quietly come back.
    "tts/chatterbox_synth.py",
)

#: The EPUB-exclusive functions Phase 5 removed from production. Every one of them
#: is preserved in the archive instead.
RETIRED_FUNCTIONS = (
    "chap2text_epub",
    "get_epub_cover",
    "export",
    "check_for_file",
)

#: Dependencies whose only consumers were the retired functions.
REMOVED_DEPENDENCIES = ("ebooklib", "beautifulsoup4", "lxml")
REMOVED_IMPORT_NAMES = ("ebooklib", "bs4", "lxml")

#: Retained pins that must not drift while the three above are removed.
RETAINED_PINS = {
    "edge-tts": "7.2.8",
    "mutagen": "1.47.0",
    "nltk": "3.9.4",
    "pillow": "12.2.0",
    "pillow-heif": "1.5.0",
    "pydub": "0.25.1",
    "pymupdf": "1.27.2.3",
    "pytest": "9.1.1",
    "scipy": "1.17.1",
    # Stepped back from 82.0.1 by v0.6.1 Plan 4 Phase 8 (maintainer-authorized):
    # 82 removed `pkg_resources`, which Chatterbox's watermark dependency still
    # imports. Unrelated to the EPUB retirement — the pin is tracked here only so
    # it cannot drift silently. See the note in scripts/requirements.txt.
    "setuptools": "80.9.0",
    "soundfile": "0.13.1",
    "tqdm": "4.67.3",
}


def source(relative: str) -> str:
    return (UNIVERSAL / relative).read_text(encoding="utf-8")


def parse(relative: str) -> ast.Module:
    return ast.parse(source(relative), filename=relative)


def defined_functions(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def imported_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def string_constants(tree: ast.AST) -> list[str]:
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def requirement_lines() -> list[str]:
    lines = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        stripped = raw.split("#", 1)[0].strip()
        if stripped:
            lines.append(stripped)
    return lines


def requirement_names() -> dict[str, str]:
    """``{normalized distribution name: pinned version}`` from requirements.txt."""
    pins: dict[str, str] = {}
    for line in requirement_lines():
        spec = line.split(";", 1)[0].strip()
        name, _, version = spec.partition("==")
        pins[name.strip().lower().replace("_", "-")] = version.strip()
    return pins


# --------------------------------------------------------------------------- #
# 1. PDF and TXT are the only active TTS input types
# --------------------------------------------------------------------------- #


def test_the_runner_accepts_exactly_pdf_and_txt():
    """``run_conversion_job``'s own suffix gate is the single dispatch authority."""
    from tts.epub2tts_edge.runner import run_conversion_job  # noqa: F401

    tree = parse("tts/epub2tts_edge/runner.py")
    job = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "run_conversion_job"
    )
    suffixes = {
        value
        for value in string_constants(job)
        if value.startswith(".") and len(value) <= 6
    }
    assert suffixes == {".pdf", ".txt"}, suffixes


def test_the_runner_refuses_an_epub_by_direct_internal_call(tmp_path):
    """Not through the UI, and not by reaching past it either."""
    from tts.epub2tts_edge.runner import run_conversion_job

    book = tmp_path / "novel.epub"
    book.write_bytes(b"PK\x03\x04not-really-an-epub")
    with pytest.raises(ValueError) as excinfo:
        run_conversion_job(str(book), output_dir=str(tmp_path / "out"))
    assert ".epub" in str(excinfo.value)


def test_the_runner_grew_no_epub_parameter():
    import inspect

    from tts.epub2tts_edge.runner import run_conversion_job

    parameters = inspect.signature(run_conversion_job).parameters
    assert not [name for name in parameters if "epub" in name.lower()], parameters


def test_the_batch_traversal_still_yields_pdf_and_txt_occurrences_only():
    """52B's folder-batching clause is untouched by retirement."""
    tree = parse("tts/batch_convert.py")
    suffixes = {
        value
        for value in string_constants(tree)
        if value.startswith(".") and len(value) <= 6
    }
    assert ".epub" not in suffixes
    assert {".pdf", ".txt"} <= suffixes


def test_the_kokoro_folder_loop_filters_to_pdf_and_txt_only():
    """The panel's inline Kokoro traversal mirrors ``run_batch_convert`` exactly."""
    tree = parse("tts/epub2tts_gui.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Tuple):
            values = string_constants(node)
            if ".pdf" in values or ".txt" in values:
                assert ".epub" not in values, values


# --------------------------------------------------------------------------- #
# 2. ``.epub`` cannot enter production by any route
# --------------------------------------------------------------------------- #


#: ``.epub`` as a *file extension*, not as the middle of a dotted module path.
#: ``tts.epub2tts_edge`` must not trip this; ``"*.epub *.pdf"`` must.
EPUB_EXTENSION = re.compile(r"\.epub(?![A-Za-z0-9_])", re.IGNORECASE)


@pytest.mark.parametrize("relative", PRODUCTION_TTS_SOURCES)
def test_no_production_tts_module_names_the_epub_extension(relative):
    """Every executable string literal, in every production TTS module, by AST.

    A comment cannot pass this and cannot fail it either — only real string
    constants are read, which is what makes it a dispatch guard rather than a
    spell-check. Docstrings are excluded on purpose: the panel's header documents
    the retirement, and describing it is not offering it.
    """
    tree = parse(relative)
    prose = docstring_node_ids(tree)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in prose:
            continue
        assert not EPUB_EXTENSION.search(node.value), (relative, node.value)


@pytest.mark.parametrize("relative", PRODUCTION_TTS_SOURCES)
def test_no_production_tts_module_imports_an_epub_parser(relative):
    assert not (imported_roots(parse(relative)) & set(REMOVED_IMPORT_NAMES)), relative


@pytest.mark.parametrize("name", RETIRED_FUNCTIONS)
def test_the_retired_functions_are_gone_from_the_engine(name):
    assert name not in defined_functions(parse("tts/epub2tts_edge/epub2tts_edge.py"))


@pytest.mark.parametrize("name", RETIRED_FUNCTIONS)
def test_nothing_in_production_still_imports_a_retired_function(name):
    for relative in PRODUCTION_TTS_SOURCES:
        tree = parse(relative)
        imported = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert name not in imported, (relative, name)


def test_the_engine_module_can_still_be_imported_without_the_removed_packages():
    """Import-blocking seam: PDF/TXT synthesis must not need the EPUB stack.

    ``sys.modules`` is poisoned with a sentinel that raises on attribute access, so
    a lingering ``from ebooklib import epub`` fails loudly instead of silently
    succeeding because the package happens to still be installed in this venv.
    """
    import sys

    class Poisoned:
        def __getattr__(self, item):  # pragma: no cover - only on a regression
            raise AssertionError(f"production imported a retired dependency: {item}")

    saved = {name: sys.modules.get(name) for name in REMOVED_IMPORT_NAMES}
    for name in list(sys.modules):
        if name.split(".")[0] in REMOVED_IMPORT_NAMES:
            saved.setdefault(name, sys.modules[name])
    try:
        for name in REMOVED_IMPORT_NAMES:
            for loaded in [k for k in sys.modules if k.split(".")[0] == name]:
                del sys.modules[loaded]
            sys.modules[name] = Poisoned()  # type: ignore[assignment]
        for loaded in [
            k for k in sys.modules if k.startswith("tts.epub2tts_edge") or k == "tts"
        ]:
            del sys.modules[loaded]
        import tts.epub2tts_edge.epub2tts_edge as engine
        import tts.epub2tts_edge.runner as runner

        assert callable(engine.read_book)
        assert callable(runner.run_conversion_job)
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def test_the_panel_keeps_no_epub_mode_variable():
    tree = parse("tts/epub2tts_gui.py")
    names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }
    assert not [name for name in names if "epub" in name.lower()], names


def test_the_file_dialog_offers_pdf_and_txt_only():
    """The ``filetypes`` list a user actually sees, read off the AST."""
    tree = parse("tts/epub2tts_gui.py")
    patterns = [
        value
        for value in string_constants(tree)
        if "*." in value and "All files" not in value
    ]
    assert patterns, "the source-file dialog filter went missing"
    for value in patterns:
        assert "epub" not in value.lower(), value
    assert any("*.pdf" in value and "*.txt" in value for value in patterns), patterns


def test_a_stale_persisted_input_path_cannot_revive_epub_dispatch(tmp_path):
    """Even handed an ``.epub`` path directly, the dispatch layer refuses it."""
    from tts.epub2tts_edge.runner import run_conversion_job

    stale = tmp_path / "from-last-version.EPUB"
    stale.write_text("stale", encoding="utf-8")
    with pytest.raises(ValueError):
        run_conversion_job(str(stale), output_dir=str(tmp_path / "out"))


def test_a_retry_of_an_epub_path_is_refused_the_same_way(tmp_path):
    from tts.epub2tts_edge.runner import run_conversion_job

    book = tmp_path / "retry.epub"
    book.write_text("x", encoding="utf-8")
    for _attempt in range(3):
        with pytest.raises(ValueError):
            run_conversion_job(str(book), output_dir=str(tmp_path / "out"))


# --------------------------------------------------------------------------- #
# 3. No production UI, launcher description or help text offers EPUB
# --------------------------------------------------------------------------- #


def test_the_launcher_description_no_longer_advertises_epub():
    from importlib import reload

    import launcher

    reload(launcher)
    spec = next(tool for tool in launcher.TOOLS if tool.key == "tts")
    assert "epub" not in spec.description.lower(), spec.description
    assert "PDF" in spec.description and "TXT" in spec.description


def test_the_launcher_still_registers_exactly_six_tools():
    from importlib import reload

    import launcher

    reload(launcher)
    assert len(launcher.TOOLS) == 6
    assert [tool.key for tool in launcher.TOOLS] == [
        "tts", "m4b_converter", "mp3_tool", "m4b_maker", "cover", "m4b_metadata",
    ]


def test_no_visible_panel_label_mentions_epub():
    """Every user-visible ``text=`` keyword in the panel, by AST."""
    tree = parse("tts/epub2tts_gui.py")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg in {"text", "title", "help", "label"} and isinstance(
                keyword.value, ast.Constant
            ):
                assert "epub" not in str(keyword.value.value).lower(), keyword.value.value


def test_the_command_line_help_no_longer_offers_an_epub_flag():
    tree = parse("tts/epub2tts_edge/epub2tts_edge.py")
    main = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    for value in string_constants(main):
        assert "epub" not in value.lower() or value == "epub2tts-edge", value


# --------------------------------------------------------------------------- #
# 4/5. Edge and Kokoro PDF/TXT conversion is behaviourally unchanged
# --------------------------------------------------------------------------- #


def test_a_txt_source_still_reaches_the_edge_engine_unchanged(tmp_path, monkeypatch):
    """The `.txt` path: copied verbatim into the work directory, then synthesised."""
    from tts.epub2tts_edge import runner

    seen: dict[str, object] = {}

    def fake_get_book(work_txt):
        seen["work_txt"] = Path(work_txt).read_text(encoding="utf-8")
        return ([{"title": "One", "paragraphs": ["Hello."]}], "T", "A", ["One"])

    def fake_read_book(*args, **kwargs):
        seen["read_book_kwargs"] = kwargs
        out = Path("chapter.mp3")
        out.write_bytes(b"audio")
        return [str(out)]

    def fake_make_mp3(files, sourcefile, speaker, bitrate="192k"):
        produced = Path(sourcefile).with_suffix("") .with_name(
            Path(sourcefile).stem + f" ({speaker}).mp3"
        )
        produced.write_bytes(b"final")
        return str(produced)

    monkeypatch.setattr(runner, "get_book", fake_get_book)
    monkeypatch.setattr(runner, "read_book", fake_read_book)
    monkeypatch.setattr(runner, "make_mp3", fake_make_mp3)

    src = tmp_path / "chapter.txt"
    src.write_text("Title: T\nAuthor: A\n\n# One\n\nHello.\n", encoding="utf-8")
    out_dir = tmp_path / "run"
    result = runner.run_conversion_job(
        str(src), output_dir=str(out_dir), audio_format="mp3"
    )

    assert Path(result).parent == out_dir
    assert "Hello." in str(seen["work_txt"])


def test_a_pdf_source_still_goes_through_the_extractor_and_heading_injection(
    tmp_path, monkeypatch
):
    """PyMuPDF extraction, then ``_ensure_pdf_txt_has_chapter_heading``, unchanged."""
    import sys
    import types

    from tts.epub2tts_edge import runner

    extracted: list[str] = []
    handed_to_get_book: list[str] = []

    def fake_pdf_to_txt(source_path, target):
        extracted.append(source_path)
        Path(target).write_text("Chapter One\n\nBody text.\n", encoding="utf-8")
        return target

    stub = types.ModuleType("tts.pdf_extractor")
    stub.pdf_to_txt = fake_pdf_to_txt  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tts.pdf_extractor", stub)

    def fake_get_book(work_txt):
        handed_to_get_book.append(Path(work_txt).read_text(encoding="utf-8"))
        return ([{"title": "Chapter One", "paragraphs": ["Body text."]}], "T", "A",
                ["Chapter One"])

    def fake_read_book(*args, **kwargs):
        chunk = Path("chapter.mp3")
        chunk.write_bytes(b"audio")
        return [str(chunk)]

    def fake_make_mp3(files, sourcefile, speaker, bitrate="192k"):
        produced = Path(f"{Path(sourcefile).stem} ({speaker}).mp3")
        produced.write_bytes(b"final")
        return str(produced)

    monkeypatch.setattr(runner, "get_book", fake_get_book)
    monkeypatch.setattr(runner, "read_book", fake_read_book)
    monkeypatch.setattr(runner, "make_mp3", fake_make_mp3)

    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    result = runner.run_conversion_job(
        str(src), output_dir=str(tmp_path / "run"), audio_format="mp3"
    )

    assert Path(result).parent == tmp_path / "run"
    assert extracted == [str(src)]
    injected = handed_to_get_book[0]
    assert injected.startswith("Title: Unknown")
    assert "# Chapter One" in injected


def test_the_kokoro_engine_module_is_untouched_by_retirement():
    """`kokoro_synth.py` is shared, not EPUB code — it must be byte-stable here."""
    tree = parse("tts/kokoro_synth.py")
    assert not (imported_roots(tree) & set(REMOVED_IMPORT_NAMES))
    for value in string_constants(tree):
        assert ".epub" not in value.lower(), value


# --------------------------------------------------------------------------- #
# 6. Timing constants, retry constants, chunk delays and defaults are unchanged
# --------------------------------------------------------------------------- #


def test_every_edge_timing_constant_keeps_its_approved_value():
    from tts.epub2tts_edge import epub2tts_edge as engine

    assert engine.DEFAULT_SPEAKER == "en-US-SteffanNeural"
    assert engine.DEFAULT_SENTENCE_PAUSE_MS == 800
    assert engine.DEFAULT_PARAGRAPH_PAUSE_MS == 850
    assert engine.DEFAULT_TITLE_PAUSE_MS == 1200
    assert engine.DEFAULT_CHAPTER_PAUSE_MS == 2000
    assert engine.DEFAULT_END_OF_BOOK_PAUSE_MS == 3000
    assert engine.COMMA_PAUSE_MS == 300
    assert engine.ELLIPSIS_PAUSE_MS == 600
    assert engine.EM_DASH_PAUSE_MS == 400
    assert engine.DEFAULT_TRIM_SILENCE_DB == -58.0
    assert engine.DEFAULT_TRIM_CHUNK_MS == 10


def test_every_batch_retry_constant_keeps_its_approved_value():
    from tts import batch_convert

    assert batch_convert.PDF_MAX_RETRIES == 2
    assert batch_convert.CHUNK_MAX_RETRIES == 5
    assert batch_convert.INTER_CHUNK_DELAY_SEC == 0.8


def test_the_edge_and_kokoro_voices_and_the_default_label_are_unchanged():
    """EPUB retirement did not touch the registry, and neither did adding a backend.

    The Edge and Kokoro counts are what this test is about; the four approved
    Chatterbox rows Phase 10 appended are counted here only to prove nothing else
    appeared beside them.
    """
    from tts import voice_registry as vr

    assert len(vr.VOICES) == 16
    assert vr.DEFAULT_VOICE_LABEL == vr.display_labels()[0]
    assert len([v for v in vr.VOICES if v.backend == "edge"]) == 7
    assert len([v for v in vr.VOICES if v.backend == "kokoro"]) == 5
    assert len([v for v in vr.VOICES if v.backend == "chatterbox"]) == 4
    for voice in vr.VOICES:
        assert isinstance(voice.timing_preset, dict) and voice.timing_preset


def test_the_shared_edge_synthesis_surface_survived_intact():
    from tts.epub2tts_edge import epub2tts_edge as engine

    for name in (
        "read_book", "run_edgespeak", "intra_sentence_chunks", "trim_silence_segment",
        "trim_tts_chunk_file", "append_silence", "make_mp3", "make_m4b", "add_cover",
        "generate_metadata", "get_duration", "get_book", "ensure_punkt",
        "parallel_edgespeak", "run_save",
    ):
        assert callable(getattr(engine, name)), name


# --------------------------------------------------------------------------- #
# 7. The run directory is reserved only after input validation
# --------------------------------------------------------------------------- #


def test_the_panel_still_validates_before_it_reserves_a_run_directory():
    body = source("tts/epub2tts_gui.py").split("def run_job", 1)[1]
    assert body.index('messagebox.showwarning("Missing input"') < body.index(
        "reserve_run_directory(TOOL_KEY)"
    )


def test_building_the_panel_reserves_nothing():
    """No reservation call sits outside ``run_job``."""
    before = source("tts/epub2tts_gui.py").split("def run_job", 1)[0]
    assert "reserve_run_directory(" not in before


# --------------------------------------------------------------------------- #
# 8. The archive is tracked, inert, unimportable, uncollected and unpackaged
# --------------------------------------------------------------------------- #


def test_the_archive_exists_at_its_contracted_location():
    assert ARCHIVE.is_dir(), ARCHIVE
    assert (ARCHIVE / "README.md").is_file()


def test_the_archive_lives_outside_the_production_scripts_tree():
    assert REPO_ROOT / "scripts" not in ARCHIVE.parents
    assert ARCHIVE.is_relative_to(FILES)


def docstring_node_ids(tree: ast.Module) -> set[int]:
    """Identity of every node that is a docstring, so prose can be excluded."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def test_no_production_module_puts_the_archive_on_sys_path():
    """A docstring may *point* at the archive; no executable string may name it.

    Docstrings are excluded deliberately — the panel's own header documents the
    naming compatibility boundary and cites the manifest, which is prose, not a
    path the interpreter ever resolves.
    """
    for path in sorted(UNIVERSAL.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        prose = docstring_node_ids(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in prose:
                    continue
                assert "archived-code" not in node.value, (path, node.value)
                assert "archived_code" not in node.value, (path, node.value)
        assert not [root for root in imported_roots(tree) if "archived" in root], path


def test_the_archive_is_not_importable_through_production():
    import sys

    assert not any("archived-code" in entry for entry in sys.path), sys.path
    assert not any(
        getattr(module, "__file__", None) and "archived-code" in str(module.__file__)
        for module in list(sys.modules.values())
    )


def test_the_archive_contributes_no_pytest_collection_nodes():
    """No archived file matches pytest's default collection patterns.

    The suite is invoked as ``pytest files/tests`` (``verify.check_pytest``), so
    ``files/archived-code/`` is already out of scope by path. This proves the
    stronger property as well: even a whole-repository invocation would collect
    nothing from the archive.
    """
    assert not list(ARCHIVE.rglob("test_*.py"))
    assert not list(ARCHIVE.rglob("*_test.py"))
    assert not list(ARCHIVE.rglob("conftest.py"))


def test_the_archive_carries_no_runtime_entry_point_or_import_hook():
    for path in sorted(ARCHIVE.rglob("*")):
        if path.is_dir():
            continue
        assert path.suffix in {".py", ".md"}, path
        assert path.name not in {
            "__init__.py", "conftest.py", "sitecustomize.py", "usercustomize.py",
            "pytest.ini", "setup.py", "pyproject.toml", "tox.ini",
        }, path


def test_no_archived_python_file_executes_on_import():
    """Every archived module is a reference text: no ``__main__`` block, no top-level call."""
    for path in sorted(ARCHIVE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            assert not isinstance(node, ast.If), path
            assert not isinstance(node, ast.Expr) or isinstance(
                node.value, ast.Constant
            ), path


def test_the_release_packager_can_never_reach_the_archive():
    from shared import release

    assert release.ROOT_FILES == ("README.md", "config.toml")
    assert release.SCRIPTS_DIR.name == "scripts"
    assert not str(ARCHIVE).startswith(str(release.SCRIPTS_DIR))
    text = (SHARED / "release.py").read_text(encoding="utf-8")
    assert "archived-code" not in text
    assert "FILES_DIR" not in text


def test_no_archived_path_appears_in_the_built_release_file_list(tmp_path):
    """Proved by walking the packager's own scope, without building a release."""
    from shared import release

    members = [
        path.relative_to(release.SCRIPTS_DIR)
        for path in sorted(release.SCRIPTS_DIR.rglob("*"))
        if path.is_file() and not release._is_excluded(path.relative_to(release.SCRIPTS_DIR))
    ]
    assert members
    assert not [member for member in members if "archived-code" in member.parts]


# --------------------------------------------------------------------------- #
# The archive manifest is accurate
# --------------------------------------------------------------------------- #


def test_the_manifest_names_every_archived_file():
    manifest = (ARCHIVE / "README.md").read_text(encoding="utf-8")
    for path in sorted(ARCHIVE.rglob("*.py")):
        assert path.name in manifest, path


def test_the_manifest_records_the_source_commit_and_the_retirement_reason():
    manifest = (ARCHIVE / "README.md").read_text(encoding="utf-8")
    assert ARCHIVE_SOURCE_SHA[:7] in manifest
    assert "GPL-3.0" in manifest
    assert "aedocw/epub2tts-edge" in manifest
    assert "Christopher Aedo" in manifest


def test_the_manifest_records_an_original_path_for_every_archived_module():
    manifest = (ARCHIVE / "README.md").read_text(encoding="utf-8")
    assert "scripts/Universal/tts/epub2tts_edge/epub2tts_edge.py" in manifest
    assert "scripts/Universal/tts/epub2tts_edge/runner.py" in manifest
    assert "scripts/Universal/tts/epub2tts_gui.py" in manifest


def test_the_archive_preserves_the_retired_engine_functions():
    archived = (ARCHIVE / "epub2tts_edge_epub_functions.py").read_text(encoding="utf-8")
    tree = ast.parse(archived)
    assert {"chap2text_epub", "get_epub_cover", "export", "check_for_file"} <= (
        defined_functions(tree)
    )


def test_the_archive_holds_no_media_or_book_fixture():
    for path in sorted(ARCHIVE.rglob("*")):
        if path.is_dir():
            continue
        assert path.suffix.lower() not in {
            ".epub", ".mp3", ".m4b", ".m4a", ".wav", ".flac", ".pdf",
            ".png", ".jpg", ".jpeg", ".heic", ".heif", ".bin", ".zip",
        }, path


# --------------------------------------------------------------------------- #
# 10. Licence and upstream attribution survive, in production as well as archive
# --------------------------------------------------------------------------- #


def test_the_readme_licence_section_is_untouched():
    text = README.read_text(encoding="utf-8")
    assert "GNU General Public License v3.0 (GPL‑3.0)" in text
    assert "inherited from the upstream" in text
    assert "derivative works must also be licensed under GPL‑3.0" in text


def test_the_readme_upstream_credit_is_untouched():
    text = README.read_text(encoding="utf-8")
    assert "https://github.com/aedocw/epub2tts-edge" in text
    assert "Christopher Aedo" in text
    assert "the basis of the TTS engine. Licensed **GPL‑3.0**" in text


def test_the_readme_capability_text_is_pdf_and_txt_only():
    """Only the *capability* prose changes; credits and licence keep their words."""
    text = README.read_text(encoding="utf-8")
    head, _, credits = text.partition("## Credits")
    #: Every surviving mention above the Credits section must be a retirement or
    #: provenance note, never an offer of EPUB as an input.
    for line in head.splitlines():
        if "EPUB" in line:
            assert "retired" in line, line
    assert "PDF / TXT" in head
    assert "a **PDF or TXT**" in head
    assert "epub2tts" in credits


def test_the_engine_module_still_credits_upstream_in_its_generated_metadata():
    from tts.epub2tts_edge import epub2tts_edge as engine
    import inspect

    body = inspect.getsource(engine.generate_metadata)
    assert "https://github.com/aedocw/epub2tts-edge" in body


# --------------------------------------------------------------------------- #
# 11/12. Dependencies: removed ones have no consumer, retained ones keep their pins
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("package", REMOVED_DEPENDENCIES)
def test_a_removed_dependency_is_no_longer_pinned(package):
    assert package not in requirement_names()


@pytest.mark.parametrize("import_name", REMOVED_IMPORT_NAMES)
def test_a_removed_dependency_has_no_active_production_consumer(import_name):
    for path in sorted(UNIVERSAL.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert import_name not in imported_roots(tree), path


@pytest.mark.parametrize("import_name", REMOVED_IMPORT_NAMES)
def test_a_removed_dependency_has_no_active_test_consumer(import_name):
    for path in sorted((FILES / "tests").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = imported_roots(tree)
        if path.name == "test_epub_retirement.py":
            continue
        assert import_name not in imported, path


@pytest.mark.parametrize("import_name", REMOVED_IMPORT_NAMES)
def test_bootstrap_no_longer_requires_a_removed_dependency(import_name):
    from shared import bootstrap

    assert import_name not in bootstrap.REQUIRED_IMPORTS
    assert import_name not in bootstrap._PIP_NAME


def test_bootstrap_still_requires_every_surviving_package():
    from shared import bootstrap

    # "chatterbox" joined the list in v0.6.1 Plan 4 Phase 8; the six EPUB-era
    # survivors are unchanged and still in their original order.
    assert bootstrap.REQUIRED_IMPORTS == [
        "edge_tts", "pydub", "fitz", "mutagen", "PIL", "nltk", "chatterbox"
    ]


def test_no_retained_direct_dependency_needs_a_removed_one():
    """Only *optional extras* may still name them — a bare requirement would not do.

    Read from the installed distribution metadata, not from memory: this is the
    §4.7 evidence step that stops a package being removed because a comment called
    it an EPUB dependency.
    """
    retained = set(requirement_names())
    for distribution in importlib_metadata.distributions():
        name = (distribution.metadata["Name"] or "").lower().replace("_", "-")
        if name not in retained:
            continue
        for requirement in distribution.requires or []:
            base = re.split(r"[\s\[<>=!~;]", requirement, maxsplit=1)[0].lower()
            base = base.replace("_", "-")
            if base in REMOVED_DEPENDENCIES:
                assert "extra ==" in requirement, (name, requirement)


@pytest.mark.parametrize("package,version", sorted(RETAINED_PINS.items()))
def test_a_retained_dependency_keeps_its_exact_pin(package, version):
    assert requirement_names().get(package) == version


def test_every_requirement_is_still_exactly_pinned():
    for line in requirement_lines():
        spec = line.split(";", 1)[0].strip()
        assert "==" in spec, line
        assert not re.search(r"(>=|<=|~=|!=|(?<!=)>|(?<!=)<)", spec), line


def test_the_kokoro_and_heic_pins_did_not_drift():
    text = REQUIREMENTS.read_text(encoding="utf-8")
    assert 'kokoro==0.9.4 ; python_version < "3.13"' in text
    assert "pillow-heif==1.5.0" in text
    assert 'audioop-lts==0.2.2 ; python_version >= "3.13"' in text


# --------------------------------------------------------------------------- #
# 13. The guards exclude the archive, preserved history and manifest references
# --------------------------------------------------------------------------- #


def test_the_production_guard_list_covers_every_production_tts_module():
    """The allow-list can neither go stale nor be padded to hide a module."""
    on_disk = {
        str(path.relative_to(UNIVERSAL)).replace("\\", "/")
        for path in sorted(TTS.rglob("*.py"))
        if "__pycache__" not in path.parts
    }
    assert on_disk == set(PRODUCTION_TTS_SOURCES), on_disk ^ set(PRODUCTION_TTS_SOURCES)


def test_every_guarded_path_is_production_source_and_nothing_else():
    """The guards' scope, stated as data: only ``scripts/`` files are ever scanned.

    This is what stops a bare repository-wide substring prohibition creeping in.
    The archive, the append-only history and the release-history notes all still
    contain the word, legitimately, and none of them is in scope for any guard
    above.
    """
    for relative in PRODUCTION_TTS_SOURCES:
        target = UNIVERSAL / relative
        assert target.is_file(), relative
        assert target.is_relative_to(REPO_ROOT / "scripts"), relative
        assert not target.is_relative_to(FILES), relative
    for excluded in (
        ARCHIVE,
        REPO_ROOT / "md-instructions" / "Changelog.md",
        REPO_ROOT / "md-instructions" / "Decisions.md",
        REPO_ROOT / "md-instructions" / "don't-delete",
        FILES / "release-history",
    ):
        assert excluded.exists(), excluded
        assert not str(excluded).startswith(str(REPO_ROOT / "scripts")), excluded


def test_the_historical_record_still_contains_the_retired_word():
    """Proof the retirement did not rewrite append-only history."""
    changelog = (REPO_ROOT / "md-instructions" / "Changelog.md").read_text(
        encoding="utf-8"
    )
    assert "epub" in changelog.lower()


def test_the_surviving_package_names_are_a_documented_compatibility_boundary():
    """Phase 5 chose not to rename (drop §4.4). The choice must be written down."""
    assert (TTS / "epub2tts_edge" / "epub2tts_edge.py").is_file()
    assert (TTS / "epub2tts_gui.py").is_file()
    manifest = (ARCHIVE / "README.md").read_text(encoding="utf-8")
    assert "compatibility boundary" in manifest.lower()
    header = source("tts/epub2tts_gui.py")[:2000]
    assert "PDF" in header and "TXT" in header
