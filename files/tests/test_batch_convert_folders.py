"""Batch convert: nested-folder mirroring, same-stem collision safety, .txt inputs.

No network: synthesize_chunk_mp3 is monkeypatched to copy a locally generated
silent MP3, so Edge TTS is never touched. Needs a local ffmpeg (pydub encode/
decode) — the whole module skips cleanly if none is resolvable.
"""

from __future__ import annotations

import shutil

import pytest

from shared import ffmpeg_utils

if not ffmpeg_utils.have_ffmpeg():  # pragma: no cover - environment guard
    pytest.skip("ffmpeg not available for pydub", allow_module_level=True)

ffmpeg_utils.configure_pydub()

from pydub import AudioSegment  # noqa: E402

import tts.batch_convert as bc  # noqa: E402


@pytest.fixture(scope="module")
def silent_mp3(tmp_path_factory) -> str:
    """One tiny silent MP3 the fake synthesizer copies for every chunk."""
    p = tmp_path_factory.mktemp("clip") / "silent.mp3"
    AudioSegment.silent(duration=120).export(str(p), format="mp3")
    return str(p)


@pytest.fixture
def fake_synth(monkeypatch, silent_mp3):
    """No-network synthesis: record the texts, copy the silent clip into place.

    Also zeroes the polite inter-chunk delay so the suite stays fast.
    """
    texts: list[str] = []

    def _fake(text: str, path: str, voice: str, rate: str) -> None:
        texts.append(text)
        shutil.copyfile(silent_mp3, path)

    monkeypatch.setattr(bc, "synthesize_chunk_mp3", _fake)
    monkeypatch.setattr(bc, "INTER_CHUNK_DELAY_SEC", 0)
    return texts


def _run(input_dir, output_dir, **kw):
    return bc.run_batch_convert(
        input_dir,
        output_dir,
        workers=1,
        use_tqdm=False,
        log=lambda s: None,
        **kw,
    )


def test_nested_folders_mirror_output_tree(tmp_path, fake_synth):
    inp = tmp_path / "in"
    out = tmp_path / "out"
    (inp / "Book 1" / "deep").mkdir(parents=True)
    (inp / "root chapter.txt").write_text("Root text.", encoding="utf-8")
    (inp / "Book 1" / "chapter 1.txt").write_text("Book one text.", encoding="utf-8")
    (inp / "Book 1" / "deep" / "chapter 2.txt").write_text("Deep text.", encoding="utf-8")

    ok, fail, _ = _run(inp, out)

    assert (ok, fail) == (3, 0)
    assert (out / "root chapter.mp3").exists()
    assert (out / "Book 1" / "chapter 1.mp3").exists()
    assert (out / "Book 1" / "deep" / "chapter 2.mp3").exists()


def test_same_stem_in_different_subfolders_do_not_collide(tmp_path, fake_synth):
    fitz = pytest.importorskip("fitz")
    inp = tmp_path / "in"
    out = tmp_path / "out"
    for book, line in (("Book A", "Alpha body text."), ("Book B", "Beta body text.")):
        (inp / book).mkdir(parents=True)
        doc = fitz.open()
        doc.new_page().insert_text((72, 100), line, fontsize=12)
        doc.save(str(inp / book / "Chapter 1.pdf"))
        doc.close()

    ok, fail, _ = _run(inp, out)

    assert (ok, fail) == (2, 0)
    assert (out / "Book A" / "Chapter 1.mp3").exists()
    assert (out / "Book B" / "Chapter 1.mp3").exists()
    assert not (out / "Chapter 1.mp3").exists(), "flat write would have collided"


def test_txt_inputs_bypass_pdf_extractor(tmp_path, fake_synth, monkeypatch):
    def _boom(path):  # the PDF extractor must never see a .txt
        raise AssertionError(f"extract_text_from_pdf called for {path}")

    monkeypatch.setattr(bc, "extract_text_from_pdf", _boom)
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    (inp / "notes.txt").write_text("Plain text chapter body.", encoding="utf-8")

    ok, fail, _ = _run(inp, out)

    assert (ok, fail) == (1, 0)
    assert (out / "notes.mp3").exists()
    assert fake_synth and "Plain text chapter body." in fake_synth[0]


def test_flat_input_keeps_flat_output(tmp_path, fake_synth):
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    (inp / "one.txt").write_text("First.", encoding="utf-8")
    (inp / "two.txt").write_text("Second.", encoding="utf-8")

    ok, fail, _ = _run(inp, out)

    assert (ok, fail) == (2, 0)
    assert (out / "one.mp3").exists() and (out / "two.mp3").exists()
    assert not any(p.is_dir() and p.name != ".tmp_chunks" for p in out.iterdir())


def test_resume_skips_existing_mirrored_target(tmp_path, fake_synth):
    inp = tmp_path / "in"
    out = tmp_path / "out"
    (inp / "Book 1").mkdir(parents=True)
    (inp / "Book 1" / "done.txt").write_text("Already converted.", encoding="utf-8")
    (inp / "Book 1" / "todo.txt").write_text("Still pending.", encoding="utf-8")
    (out / "Book 1").mkdir(parents=True)
    (out / "Book 1" / "done.mp3").write_bytes(b"existing")

    ok, fail, _ = _run(inp, out, resume=True)

    assert (ok, fail) == (1, 0)
    assert (out / "Book 1" / "done.mp3").read_bytes() == b"existing"
    assert (out / "Book 1" / "todo.mp3").exists()
    assert len(fake_synth) == 1 and "Still pending." in fake_synth[0]
