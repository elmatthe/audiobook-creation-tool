"""Batch convert: nested-folder mirroring, same-stem collision safety, .txt inputs.

No network: synthesize_chunk_mp3 is monkeypatched to copy a locally generated
silent MP3, so Edge TTS is never touched. Needs a local ffmpeg (pydub encode/
decode) — the whole module skips cleanly if none is resolvable.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from shared import ffmpeg_utils

if not ffmpeg_utils.have_ffmpeg():  # pragma: no cover - environment guard
    pytest.skip("ffmpeg not available for pydub", allow_module_level=True)

ffmpeg_utils.configure_pydub()

from pydub import AudioSegment  # noqa: E402

import tts.batch_convert as bc  # noqa: E402

#: v0.7.0 P02B: the helper names each file ``<source-stem>-<display label>.mp3``; the default speaker is Steffan, and
#: its registered label is written here as a literal so the test states the contract.
S = "Edge Male - Steffan (en-US)"


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
    assert (out / f"root chapter-{S}.mp3").exists()
    assert (out / "Book 1" / f"chapter 1-{S}.mp3").exists()
    assert (out / "Book 1" / "deep" / f"chapter 2-{S}.mp3").exists()


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
    assert (out / "Book A" / f"Chapter 1-{S}.mp3").exists()
    assert (out / "Book B" / f"Chapter 1-{S}.mp3").exists()
    assert not (out / f"Chapter 1-{S}.mp3").exists(), "flat write would have collided"


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
    assert (out / f"notes-{S}.mp3").exists()
    assert fake_synth and "Plain text chapter body." in fake_synth[0]


def test_flat_input_keeps_flat_output(tmp_path, fake_synth):
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    (inp / "one.txt").write_text("First.", encoding="utf-8")
    (inp / "two.txt").write_text("Second.", encoding="utf-8")

    ok, fail, _ = _run(inp, out)

    assert (ok, fail) == (2, 0)
    assert (out / f"one-{S}.mp3").exists() and (out / f"two-{S}.mp3").exists()
    assert not any(p.is_dir() and p.name != ".tmp_chunks" for p in out.iterdir())


def test_resume_skips_existing_mirrored_target(tmp_path, fake_synth):
    inp = tmp_path / "in"
    out = tmp_path / "out"
    (inp / "Book 1").mkdir(parents=True)
    (inp / "Book 1" / "done.txt").write_text("Already converted.", encoding="utf-8")
    (inp / "Book 1" / "todo.txt").write_text("Still pending.", encoding="utf-8")
    (out / "Book 1").mkdir(parents=True)
    (out / "Book 1" / f"done-{S}.mp3").write_bytes(b"existing")

    ok, fail, _ = _run(inp, out, resume=True)

    assert (ok, fail) == (1, 0)
    assert (out / "Book 1" / f"done-{S}.mp3").read_bytes() == b"existing"
    assert (out / "Book 1" / f"todo-{S}.mp3").exists()
    assert not (out / "Book 1" / f"done-{S}-1.mp3").exists(), "resume found the earlier file under its own name"
    assert len(fake_synth) == 1 and "Still pending." in fake_synth[0]


# --------------------------------------------------------------------------- #
# v0.7.0 P02B: one naming policy, collision planning, no overwrite
# --------------------------------------------------------------------------- #


def test_a_pdf_and_a_txt_with_one_stem_stay_two_files(tmp_path, fake_synth, monkeypatch):
    monkeypatch.setattr(bc, "extract_text_from_pdf", lambda path: "Pdf body text.")
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    (inp / "Book.pdf").write_bytes(b"%PDF placeholder")
    (inp / "Book.txt").write_text("Txt body text.", encoding="utf-8")

    ok, fail, _ = _run(inp, out)

    assert (ok, fail) == (2, 0)
    produced = sorted(p.name for p in out.iterdir() if p.is_file() and p.suffix == ".mp3")
    assert produced == [f"Book-{S}-1.mp3", f"Book-{S}.mp3"]
    # Negative control: the pre-P02B helper wrote both to "Book.mp3", the second over the first.
    assert not (out / "Book.mp3").exists()


def test_an_earlier_output_is_never_overwritten_without_resume(tmp_path, fake_synth):
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir()
    (inp / "done.txt").write_text("Converted again.", encoding="utf-8")
    out.mkdir()
    (out / f"done-{S}.mp3").write_bytes(b"earlier")

    ok, fail, _ = _run(inp, out)

    assert (ok, fail) == (1, 0)
    assert (out / f"done-{S}.mp3").read_bytes() == b"earlier"
    assert (out / f"done-{S}-1.mp3").is_file()


def test_the_label_follows_the_speaker_and_can_be_given(tmp_path, fake_synth):
    inp = tmp_path / "in"
    inp.mkdir()
    (inp / "ch.txt").write_text("Body.", encoding="utf-8")

    assert _run(inp, tmp_path / "aria", speaker="en-US-AriaNeural")[:2] == (1, 0)
    assert (tmp_path / "aria" / "ch-Edge Female - Aria (en-US).mp3").is_file()
    assert _run(inp, tmp_path / "given", label="My Narrator")[:2] == (1, 0)
    assert (tmp_path / "given" / "ch-My Narrator.mp3").is_file()


def test_an_unregistered_speaker_needs_a_label_and_nothing_is_synthesised(tmp_path, fake_synth):
    inp = tmp_path / "in"
    inp.mkdir()
    (inp / "ch.txt").write_text("Body.", encoding="utf-8")

    with pytest.raises(ValueError, match="not a registered Edge voice"):
        _run(inp, tmp_path / "out", speaker="en-GB-RyanNeural")
    assert fake_synth == []


def test_an_impossible_name_is_refused_before_any_synthesis(tmp_path, fake_synth):
    from shared import output_paths

    inp = tmp_path / "in"
    inp.mkdir()
    (inp / "ch.txt").write_text("Body.", encoding="utf-8")

    with pytest.raises(output_paths.OutputPathError, match="too long"):
        _run(inp, tmp_path / "out", label="L" * 300)
    assert fake_synth == []
    assert not [p for p in (tmp_path / "out").rglob("*.mp3")]


def test_the_temp_chunk_folder_name_is_short_for_a_deep_long_destination(tmp_path, monkeypatch):
    seen: list = []

    def _fake_merge(chunk_paths, output_mp3_path, bitrate=None):
        seen.extend(chunk_paths)  # the destination itself is not written: only the scratch folder is under test

    monkeypatch.setattr(bc, "synthesize_chunk_mp3", lambda text, path, voice, rate: open(path, "wb").close())
    monkeypatch.setattr(bc, "merge_mp3s", _fake_merge)
    monkeypatch.setattr(bc, "INTER_CHUNK_DELAY_SEC", 0)
    source = tmp_path / "ch.txt"
    source.write_text("Body text.", encoding="utf-8")
    out = tmp_path / "out"
    target = out / ("D" * 60) / ("E" * 60) / f"{'C' * 120}-{S}.mp3"
    old_key = "__".join(target.relative_to(out).with_suffix("").parts)
    assert len(old_key) > 255  # what the pre-P02B key would have asked the filesystem to create

    status, _path, message = bc.convert_single_pdf(source, out, "v", "+0%", lambda s: None, None, None, target)

    assert status == "success", message
    key = hashlib.sha256(target.relative_to(out).as_posix().encode()).hexdigest()[:16]
    assert seen and {Path(p).parent for p in seen} == {out / ".tmp_chunks" / key}
    assert not (out / ".tmp_chunks" / key).exists(), "this source's scratch folder is still removed afterwards"
