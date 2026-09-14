"""The M4B Maker single-Book engine — v0.6.4 Phase 4.

``mp3_tools/m4b_maker_processing.py`` runs **one frozen ``BookPlan``** from
start to atomic publication and reads nothing else: no widget, no live
workspace. The proven Maker algorithms (FFmpeg concat, WAV normalisation,
inserted silence, chapter timing, the FAST → Safe fallback) moved here from
the panel; artwork is the Phase 1 ``m4b_artwork`` service applied to the
**staged** file without re-encoding; series metadata is the shared
``metadata.write_m4b_tags``.

Every Book builds in its private staging directory, is validated there, and
is published only when everything succeeded. A failed or cancelled Book leaves
no visible partial M4B. Cleanup touches only operation-owned state.

Media are one-second FFmpeg tones built under ``tmp_path``; FFmpeg is a
required tool here, so an unresolvable binary fails rather than skips.
"""

from __future__ import annotations

import ast
import errno
import hashlib
import io
import json
import os
import subprocess
from pathlib import Path, PurePath

import pytest
from PIL import Image

from shared import book_workspace, ffmpeg_utils, image_capabilities, metadata, output_paths
from shared import subprocess_utils as sp
from shared.book_workspace import BookJob, SharedMetadata, WorkspaceSnapshot
from shared.cancellation import ConversionCancelled
from shared.importing import (
    IdFactory, ImportOptions, ImportedFile, ImportedFileSnapshot, ImportRoot, Revision,
)

from mp3_tools import m4b_artwork
from mp3_tools import m4b_maker_plan as mp
from mp3_tools import m4b_maker_processing as proc
from mp3_tools import m4b_maker_workflow as wf
from mp3_tools.m4b_maker_processing import BookOutcome, ProcessingError, ProcessingEvent

from test_importing import make_config

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
MODULE = UNIVERSAL / "mp3_tools" / "m4b_maker_processing.py"

_IDS = IdFactory("mk-")


# --------------------------------------------------------------------------- #
# Fixtures: real one-second tones, never repository media
# --------------------------------------------------------------------------- #


def require_ffmpeg() -> None:
    if not ffmpeg_utils.have_ffmpeg():
        pytest.fail("ffmpeg/ffprobe could not be resolved; the Maker engine cannot be proved: "
                    f"ffmpeg_path()={ffmpeg_utils.ffmpeg_path()!r}")


@pytest.fixture(autouse=True)
def _ffmpeg():
    require_ffmpeg()


def tone(path: Path, seconds: float = 1.0, freq: int = 440) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sp.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
            "-ac", "2", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "64k", str(path)],
           check=True)
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png(path: Path, size=(24, 16)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 30, 30)).save(path, format="PNG")
    return path


def jpg(path: Path, size=(32, 20)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (30, 200, 30)).save(path, format="JPEG", quality=90)
    return path


def heic(path: Path, size=(40, 28)) -> Path:
    capability = image_capabilities.heif_capability()
    if not capability.decode or not capability.encode:
        pytest.skip(f"this machine cannot round-trip HEIC/HEIF: {capability.detail}")
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (30, 30, 200)).save(path, format=image_capabilities.HEIF_FORMAT)
    return path


def listing(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")} if root.exists() else set()


def probe(path: Path, *args) -> dict:
    out = subprocess.run([ffmpeg_utils.ffprobe_cmd(), "-v", "error", *args, "-of", "json",
                          str(path)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert out.returncode == 0, out.stdout.decode("utf-8", "replace")[-600:]
    return json.loads(out.stdout.decode("utf-8", "replace"))


def duration(path: Path) -> float:
    return float(probe(path, "-show_format")["format"]["duration"])


def chapters(path: Path) -> list[tuple[str, float, float]]:
    blocks = probe(path, "-show_chapters")["chapters"]
    return [(b.get("tags", {}).get("title", ""), float(b["start_time"]), float(b["end_time"]))
            for b in blocks]


def audio_md5(path: Path) -> str:
    out = subprocess.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-v", "error",
                          "-i", str(path), "-map", "0:a", "-c", "copy", "-f", "md5", "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert out.returncode == 0, out.stdout[-400:]
    return out.stdout.decode("ascii", "replace").strip()


def covr_of(path: Path) -> list:
    from mutagen.mp4 import MP4
    tags = MP4(str(path)).tags
    return list(tags.get("covr", [])) if tags else []


@pytest.fixture
def sources(tmp_path: Path) -> Path:
    root = tmp_path / "Sources"
    root.mkdir()
    return root


@pytest.fixture
def reserve(tmp_path: Path):
    counter = {"n": 0}

    def make(**_kw):
        counter["n"] += 1
        directory = tmp_path / "Outputs" / "M4B-Maker-Outputs" / f"M4B-Maker-{counter['n']}"
        directory.mkdir(parents=True)
        return output_paths.RunReservation(
            tool_key="m4b_maker", base_directory=tmp_path / "Outputs",
            tool_directory=directory.parent, run_directory=directory, run_number=counter["n"])

    return make


def imported(sources: Path, folder: str, name: str, *, seconds=1.0, freq=440) -> ImportedFile:
    path = tone(sources / folder / name, seconds=seconds, freq=freq)
    occurrence = _IDS.next_id("occurrence")
    return ImportedFile(occurrence, path, ImportRoot("r", sources, 0),
                        PurePath(folder) / name, "mp3", f"id-{occurrence}")


def book(files, **configuration) -> BookJob:
    return BookJob(book_id=book_workspace.new_book_id(_IDS), configuration=configuration,
                   files=ImportedFileSnapshot(Revision(1), tuple(files)))


def workspace(*books: BookJob, shared: SharedMetadata | None = None) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(books=books, current_book_id=books[0].book_id,
                             shared=wf.new_shared_metadata() if shared is None else shared)


def plan(space, destination, options: mp.MakerRunOptions | None = None) -> mp.RunPlan:
    return mp.plan_run(space, options=options or mp.MakerRunOptions(), destination=destination,
                       catalog=wf.MAKER_CATALOG,
                       import_options=ImportOptions.for_catalog(wf.MAKER_CATALOG),
                       effective_config=make_config(), id_factory=_IDS)


def one_book(sources, reserve, names=("01 One.mp3", "02 Two.mp3"), *, options=None,
             **configuration):
    entry = book([imported(sources, "Book", name) for name in names], **configuration)
    made = plan(workspace(entry), mp.standard_destination(reserve()), options)
    return made, made.books[0], entry


def collect():
    seen: list[ProcessingEvent] = []
    return seen, seen.append


def stages(events, stage):
    return [e for e in events if e.stage == stage]


def build(made: mp.RunPlan, entry: mp.BookPlan, **kwargs) -> BookOutcome:
    return proc.build_book(entry, work_root=made.work_root, fast_first=made.fast_first, **kwargs)


# --------------------------------------------------------------------------- #
# One Book, one M4B: FAST when eligible, Safe when required, fallback on failure
# --------------------------------------------------------------------------- #


def test_an_eligible_book_uses_fast_and_publishes_one_chaptered_m4b(sources, reserve):
    made, entry, job = one_book(sources, reserve, names=("01 One.mp3", "02 Two.mp3", "03 Three.mp3"),
                                title="Tone Book")
    events, listener = collect()
    outcome = build(made, entry, on_event=listener)
    assert isinstance(outcome, BookOutcome) and outcome.succeeded
    assert outcome.published == entry.published and entry.published.is_file()
    assert outcome.path_used == "fast"
    assert stages(events, "fast") and not stages(events, "safe") and not stages(events, "fallback")
    assert [c[0] for c in chapters(entry.published)] == ["One", "Two", "Three"]
    assert abs(duration(entry.published) - 3.0) < 0.6
    assert not entry.staged.exists() and not entry.staging_dir.exists()
    assert sorted(p.name for p in made.root.iterdir() if p.is_file()) == ["Tone Book.m4b"]


def test_a_fast_failure_falls_back_to_safe_with_the_reason(sources, reserve, monkeypatch):
    made, entry, _ = one_book(sources, reserve, title="T")
    real = proc.fast_concat_args

    def broken(listfile, ffmeta, out_path, bitrate):
        args = real(listfile, ffmeta, out_path, bitrate)
        return args[:-1] + ["-no_such_option_for_ffmpeg", args[-1]]

    monkeypatch.setattr(proc, "fast_concat_args", broken)
    events, listener = collect()
    outcome = build(made, entry, on_event=listener)
    assert outcome.succeeded and outcome.path_used == "safe"
    fallback = stages(events, "fallback")
    assert fallback and "FAST" in fallback[0].message
    assert "no_such_option" in fallback[0].detail
    assert stages(events, "safe")
    assert [c[0] for c in chapters(entry.published)] == ["One", "Two"]
    assert abs(duration(entry.published) - 2.0) < 0.6


def test_fast_first_off_uses_safe_without_trying_fast(sources, reserve):
    made, entry, _ = one_book(sources, reserve, title="T",
                              options=mp.MakerRunOptions(fast_first=False))
    events, listener = collect()
    outcome = build(made, entry, on_event=listener)
    assert outcome.succeeded and outcome.path_used == "safe"
    assert not stages(events, "fast") and stages(events, "safe")


def test_nonzero_silence_forces_safe_and_inserts_gaps_only_between_tracks(sources, reserve):
    made, entry, _ = one_book(sources, reserve, names=("01 A.mp3", "02 B.mp3", "03 C.mp3"),
                              title="Gaps", silence="0.5")
    assert entry.silence == 0.5
    events, listener = collect()
    outcome = build(made, entry, on_event=listener)
    assert outcome.succeeded and outcome.path_used == "safe"
    assert not stages(events, "fast")
    assert stages(events, "normalize") and stages(events, "silence")
    assert abs(duration(entry.published) - (3.0 + 2 * 0.5)) < 0.6, "two gaps, not three"
    found = chapters(entry.published)
    assert [c[0] for c in found] == ["A", "B", "C"]
    assert abs(found[1][1] - (1.5 - 0.25)) < 0.2, "chapter 2 starts one track + one gap in, less lead-in"
    assert abs(found[2][1] - (3.0 - 0.25)) < 0.2


# --------------------------------------------------------------------------- #
# Chapters, metadata, series and artwork on the staged file
# --------------------------------------------------------------------------- #


def test_chapter_timing_and_frozen_titles_are_written(sources, reserve):
    made, entry, _ = one_book(sources, reserve, names=("01 x.mp3", "02 y.mp3"), title="T",
                              chapter_titles="Opening\nClosing")
    assert entry.chapter_titles == ("Opening", "Closing")
    assert build(made, entry).succeeded
    found = chapters(entry.published)
    assert [c[0] for c in found] == ["Opening", "Closing"]
    assert found[0][1] == 0.0
    assert abs(found[0][2] - (1.0 - 0.25)) < 0.2
    assert abs(found[1][1] - (1.0 - 0.25)) < 0.2
    assert found[1][2] <= duration(entry.published) + 0.01
    assert found[0][2] > found[0][1] and found[1][2] > found[1][1]
    assert metadata.read_chapter_titles(entry.published) == ["Opening", "Closing"]


def test_core_metadata_is_written_from_the_frozen_plan(sources, reserve):
    made, entry, _ = one_book(sources, reserve, title="The Title", artist="An Author",
                              album_artist="Narrator", album="The Album")
    assert build(made, entry).succeeded
    tags = metadata.read_m4b_tags(entry.published)
    assert (tags["title"], tags["artist"], tags["album_artist"], tags["album"]) == (
        "The Title", "An Author", "Narrator", "The Album")
    assert tags["has_cover"] is False


def test_a_blank_title_falls_back_to_the_plans_resolved_name(sources, reserve):
    made, entry, _ = one_book(sources, reserve, album="Only Album")
    assert entry.title == "Only Album"
    assert build(made, entry).succeeded
    assert metadata.read_m4b_tags(entry.published)["title"] == "Only Album"


def test_manual_series_name_and_part_are_written(sources, reserve):
    made, entry, _ = one_book(sources, reserve, title="T", series="Saga", series_part="3")
    assert entry.series_part == "3"
    assert build(made, entry).succeeded
    tags = metadata.read_m4b_tags(entry.published)
    assert tags["series"] == "Saga"
    assert tags["series_part"] == "3"


def test_with_auto_number_the_series_name_is_written_but_no_part_is_invented(sources, reserve):
    made, entry, _ = one_book(sources, reserve, title="T", series="Saga", series_part="3",
                              options=mp.MakerRunOptions(auto_number=True, start_part_text="5"))
    assert entry.series_part is None
    assert build(made, entry).succeeded
    tags = metadata.read_m4b_tags(entry.published)
    assert tags["series"] == "Saga"
    assert not tags.get("series_part"), tags


def test_no_series_leaves_no_series_atoms(sources, reserve):
    made, entry, _ = one_book(sources, reserve, title="T")
    assert build(made, entry).succeeded
    tags = metadata.read_m4b_tags(entry.published)
    assert not tags.get("series") and not tags.get("series_part")


@pytest.mark.parametrize("maker", [jpg, png])
def test_a_jpeg_or_png_cover_is_carried_as_its_own_bytes(sources, reserve, maker):
    from mutagen.mp4 import MP4Cover

    art = maker(sources / "art" / f"cover{'.jpg' if maker is jpg else '.png'}")
    before = sha(art)
    made, entry, _ = one_book(sources, reserve, title="T", artwork=str(art))
    assert build(made, entry).succeeded
    found = covr_of(entry.published)
    assert len(found) == 1 and bytes(found[0]) == art.read_bytes()
    expected = MP4Cover.FORMAT_JPEG if maker is jpg else MP4Cover.FORMAT_PNG
    assert found[0].imageformat == expected
    assert metadata.read_m4b_tags(entry.published)["has_cover"] is True
    assert sha(art) == before


def test_a_heic_cover_is_converted_in_memory_only(sources, reserve):
    from mutagen.mp4 import MP4Cover

    art = heic(sources / "art" / "cover.heic", size=(40, 28))
    before = sha(art)
    snapshot = listing(sources / "art")
    made, entry, _ = one_book(sources, reserve, title="T", artwork=str(art))
    assert build(made, entry).succeeded
    found = covr_of(entry.published)
    assert len(found) == 1 and found[0].imageformat == MP4Cover.FORMAT_PNG
    with Image.open(io.BytesIO(bytes(found[0]))) as decoded:
        assert decoded.size == (40, 28)
    assert sha(art) == before
    assert listing(sources / "art") == snapshot, "no converted sidecar"


def test_applying_artwork_leaves_the_packed_audio_unchanged(sources, reserve):
    art = jpg(sources / "art" / "cover.jpg")
    made, entry, _ = one_book(sources, reserve, title="T")
    staged = proc.stage_book(entry, work_root=made.work_root, fast_first=True)
    assert staged.succeeded and entry.staged.is_file() and not entry.published.exists()
    before = audio_md5(entry.staged)
    m4b_artwork.embed_cover(entry.staged, m4b_artwork.load_cover(art))
    assert audio_md5(entry.staged) == before
    assert len(covr_of(entry.staged)) == 1
    proc.discard_staging(entry, work_root=made.work_root)


def test_an_undecodable_cover_fails_before_any_encoding_and_publishes_nothing(sources, reserve,
                                                                               monkeypatch):
    bad = sources / "art" / "cover.jpg"
    bad.parent.mkdir()
    bad.write_bytes(b"not an image")
    made, entry, _ = one_book(sources, reserve, title="T", artwork=str(bad))
    ran: list[list[str]] = []
    monkeypatch.setattr(proc, "run_ffmpeg", lambda args: ran.append(list(args)))
    outcome = build(made, entry)
    assert not outcome.succeeded and outcome.failure_stage == "artwork"
    assert ran == [], "no FFmpeg was launched for a Book whose cover cannot be used"
    assert not entry.published.exists() and not entry.staging_dir.exists()


# --------------------------------------------------------------------------- #
# Staging, atomic publication, failure and cancellation
# --------------------------------------------------------------------------- #


def test_ffmpeg_writes_the_staged_path_never_the_published_one(sources, reserve, monkeypatch):
    made, entry, _ = one_book(sources, reserve, title="T")
    seen: list[Path] = []
    real = proc.run_ffmpeg

    def spy(args):
        seen.append(Path(args[-1]))
        return real(args)

    monkeypatch.setattr(proc, "run_ffmpeg", spy)
    assert build(made, entry).succeeded
    outputs = [p for p in seen if p.suffix.lower() == ".m4b"]
    assert outputs and all(p == entry.staged for p in outputs)
    assert entry.published not in seen
    assert output_paths.assert_contained(made.work_root, entry.staged)


def test_a_failed_encode_publishes_nothing_and_leaves_no_staging(sources, reserve, monkeypatch):
    made, entry, _ = one_book(sources, reserve, title="T")

    def bad(listfile, ffmeta, out_path, bitrate):
        return [ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-y", "-i", str(listfile),
                "-no_such_option_for_ffmpeg", str(out_path)]

    monkeypatch.setattr(proc, "fast_concat_args", bad)
    monkeypatch.setattr(proc, "safe_concat_args", bad)
    events, listener = collect()
    outcome = build(made, entry, on_event=listener)
    assert not outcome.succeeded and outcome.failure_stage in ("safe", "encode")
    assert "no_such_option" in outcome.failure_detail
    assert not entry.published.exists()
    assert listing(made.root) == set(), "the run directory holds no partial file"
    assert not entry.staging_dir.exists()
    assert stages(events, "failed")


def test_a_metadata_failure_after_the_encode_publishes_nothing(sources, reserve, monkeypatch):
    made, entry, _ = one_book(sources, reserve, title="T", series="Saga", series_part="1")

    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(metadata, "write_m4b_tags", explode)
    outcome = build(made, entry)
    assert not outcome.succeeded and outcome.failure_stage == "series"
    assert "boom" in outcome.failure_detail
    assert not entry.published.exists() and not entry.staging_dir.exists()


def test_a_validation_failure_publishes_nothing(sources, reserve, monkeypatch):
    made, entry, _ = one_book(sources, reserve, title="T")

    def refuse(book, staged):
        raise ProcessingError("the staged file is not usable", stage="validate", detail="x")

    monkeypatch.setattr(proc, "validate_staged_m4b", refuse)
    outcome = build(made, entry)
    assert not outcome.succeeded and outcome.failure_stage == "validate"
    assert not entry.published.exists() and not entry.staging_dir.exists()


def test_validation_catches_a_staged_file_without_the_planned_chapters(sources, reserve,
                                                                        monkeypatch):
    made, entry, _ = one_book(sources, reserve, title="T", chapter_titles="A\nB")
    staged = proc.stage_book(entry, work_root=made.work_root, fast_first=True)
    assert staged.succeeded
    # A plan that expects a third chapter the file does not have.
    import dataclasses
    tampered = dataclasses.replace(entry, chapter_titles=("A", "B", "C"))
    with pytest.raises(ProcessingError) as refused:
        proc.validate_staged_m4b(tampered, entry.staged)
    assert refused.value.stage == "validate"
    proc.discard_staging(entry, work_root=made.work_root)


def test_publication_refuses_an_already_present_destination(sources, reserve):
    made, entry, _ = one_book(sources, reserve, title="T")
    staged = proc.stage_book(entry, work_root=made.work_root, fast_first=True)
    assert staged.succeeded
    entry.published.write_bytes(b"someone else's file")
    with pytest.raises(ProcessingError):
        proc.publish_book(entry, work_root=made.work_root)
    assert entry.published.read_bytes() == b"someone else's file"
    assert entry.staged.is_file(), "the staged candidate is retained, not lost"
    proc.discard_staging(entry, work_root=made.work_root)


def test_publication_refuses_a_book_that_was_never_staged(sources, reserve):
    made, entry, _ = one_book(sources, reserve, title="T")
    with pytest.raises(ProcessingError):
        proc.publish_book(entry, work_root=made.work_root)
    assert not entry.published.exists()


def test_publication_refuses_a_staging_area_outside_the_work_root(sources, reserve, tmp_path):
    made, entry, _ = one_book(sources, reserve, title="T")
    with pytest.raises(ProcessingError):
        proc.prepare_staging(entry, work_root=tmp_path / "elsewhere")
    with pytest.raises(ProcessingError):
        proc.publish_book(entry, work_root=tmp_path / "elsewhere")
    with pytest.raises(ProcessingError):
        proc.discard_staging(entry, work_root=tmp_path / "elsewhere")


def test_publication_survives_a_cross_device_work_root(sources, reserve, monkeypatch):
    """A custom folder on another drive: the same-filesystem sibling route is used."""
    made, entry, _ = one_book(sources, reserve, title="T")
    assert proc.stage_book(entry, work_root=made.work_root, fast_first=True).succeeded
    staged_bytes = entry.staged.read_bytes()
    real_replace = os.replace
    refused = {"n": 0}

    def cross_device(src, dst):
        if Path(src) == entry.staged and refused["n"] == 0:
            refused["n"] += 1
            raise OSError(errno.EXDEV, "cross-device link")
        return real_replace(src, dst)

    monkeypatch.setattr(proc.os, "replace", cross_device)
    published = proc.publish_book(entry, work_root=made.work_root)
    assert published == entry.published and entry.published.read_bytes() == staged_bytes
    assert not entry.staged.exists()
    assert refused["n"] == 1
    assert [p.name for p in made.root.iterdir() if p.is_file()] == [entry.published.name], (
        "no temporary sibling is left behind")


def test_custom_destination_publishes_beside_unrelated_files_and_stages_elsewhere(
        sources, tmp_path):
    chosen = tmp_path / "Chosen"
    chosen.mkdir()
    (chosen / "unrelated.txt").write_text("keep me", encoding="utf-8")
    work_root = tmp_path / "op-work"
    entry_job = book([imported(sources, "Book", "01.mp3")], title="Custom")
    made = plan(workspace(entry_job), mp.custom_destination(chosen, work_root=work_root))
    entry = made.books[0]
    outcome = build(made, entry)
    assert outcome.succeeded
    assert entry.published == chosen / "Custom.m4b" and entry.published.is_file()
    assert (chosen / "unrelated.txt").read_text(encoding="utf-8") == "keep me"
    assert sorted(p.name for p in chosen.iterdir()) == ["Custom.m4b", "unrelated.txt"]
    assert not entry.staging_dir.exists()


def test_cancellation_at_a_checkpoint_removes_only_operation_owned_state(sources, reserve):
    made, entry, job = one_book(sources, reserve, names=("01.mp3", "02.mp3"), title="T",
                                silence="0.5")
    hashes = {f.path: sha(f.path) for f in job.files.files}
    calls = {"n": 0}

    def checkpoint():
        calls["n"] += 1
        if calls["n"] >= 3:
            raise ConversionCancelled()

    events, listener = collect()
    outcome = build(made, entry, checkpoint=checkpoint, on_event=listener)
    assert outcome.cancelled and not outcome.succeeded
    assert not entry.published.exists()
    assert not entry.staging_dir.exists(), "its own staging is gone"
    assert made.root.is_dir(), "the reserved run itself is the caller's"
    assert listing(made.root) == set()
    assert {f.path: sha(f.path) for f in job.files.files} == hashes
    assert stages(events, "cancelled")


def test_a_full_build_never_changes_the_sources(sources, reserve):
    made, entry, job = one_book(sources, reserve, names=("01.mp3", "02.mp3"), title="T",
                                silence="0.25")
    hashes = {f.path: sha(f.path) for f in job.files.files}
    before = listing(sources)
    assert build(made, entry).succeeded
    assert {f.path: sha(f.path) for f in job.files.files} == hashes
    assert listing(sources) == before


def test_an_unverified_ffmpeg_fails_before_anything_is_created(sources, reserve, monkeypatch):
    made, entry, _ = one_book(sources, reserve, title="T")
    monkeypatch.setattr(ffmpeg_utils, "verified_ffmpeg", lambda: False)
    outcome = build(made, entry)
    assert not outcome.succeeded and outcome.failure_stage == "ffmpeg"
    assert not made.work_root.exists() and not entry.published.exists()


def test_build_refuses_anything_but_a_book_plan(sources, reserve):
    made, entry, _ = one_book(sources, reserve, title="T")
    with pytest.raises(ProcessingError):
        proc.build_book("not a plan", work_root=made.work_root, fast_first=True)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Structure: the moved algorithms are the panel's, and nothing live is read
# --------------------------------------------------------------------------- #


def test_the_engine_reads_no_tk_workspace_or_panel_and_discovers_ffmpeg_only_once():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            modules |= {f"{node.module}.{alias.name}" for alias in node.names}
    for banned in ("tkinter", "threading", "queue", "shared.book_workspace", "shared.job_ui",
                   "shared.job_control", "shared.importing", "shared.import_coordination",
                   "shared.ui_theme", "shared.settings", "mp3_tools.m4b_maker",
                   "mp3_tools.mp3_processing", "mp3_tools.mp3_tool", "mp3_tools.mp3_plan",
                   "mp3_tools.m4b_maker_workflow", "shared.numbering", "PIL", "pillow_heif"):
        assert banned not in modules, banned
    for required in ("shared.ffmpeg_utils", "shared.subprocess_utils", "shared.metadata",
                     "shared.output_paths", "shared.cancellation", "mp3_tools.m4b_artwork",
                     "mp3_tools.m4b_maker_plan"):
        assert required in modules, required
    # No command list is headed by a bare executable name: every FFmpeg or
    # ffprobe launch starts with the shared authority's resolved command.
    for node in ast.walk(tree):
        if isinstance(node, ast.List) and node.elts:
            head = node.elts[0]
            assert not (isinstance(head, ast.Constant) and head.value in ("ffmpeg", "ffprobe")), (
                f"line {node.lineno}: a command is headed by a bare executable name")
    heads = {ast.unparse(node.elts[0]) for node in ast.walk(tree)
             if isinstance(node, ast.List) and node.elts
             and isinstance(node.elts[0], ast.Call)}
    assert heads <= {"ffmpeg_utils.ffmpeg_cmd()", "ffmpeg_utils.ffprobe_cmd()"}, heads
    assert heads, "the engine runs FFmpeg through the authority"
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for live in ("WorkspaceSnapshot", "BookJob", "StringVar", "BooleanVar", "get_workspace",
                 "current_book", "chapters_txt", "var_title", "var_artist", "cover_path"):
        assert live not in names, live


def test_the_moved_algorithms_left_the_panel_whole():
    """Phase 4 proved the helpers verbatim against the hash-pinned panel by AST
    body equality (recorded in Handoff.md). Phase 6 converted the panel, which
    now defines none of them: the engine is the one place they live."""
    panel = ast.parse((UNIVERSAL / "mp3_tools" / "m4b_maker.py").read_text(encoding="utf-8"))
    engine = ast.parse(MODULE.read_text(encoding="utf-8"))
    in_panel = {n.name for n in ast.walk(panel) if isinstance(n, ast.FunctionDef)}
    in_engine = {n.name for n in ast.walk(engine) if isinstance(n, ast.FunctionDef)}
    for name in ("build_ffmetadata_from_starts", "write_concat_list", "wav_duration_ms",
                 "compute_starts_total_fast", "compute_audio_starts_with_silence",
                 "ffprobe_duration_ms", "normalize_to_wav", "create_silence_wav"):
        assert name not in in_panel, name
        assert name in in_engine, name
    assert proc.LEADIN_MS == 250 and proc.WAV_SR == 44100 and proc.WAV_CH == 2
    assert proc.WAV_FMT == "s16"


def test_the_maker_panel_runs_nothing_itself():
    """Phase 6 converted the panel; it reaches the engine only through the
    Phase 5 runner and never imports the engine or FFmpeg directly."""
    from test_plan6_boundaries import MAKER_PHASE0_HASH, sha256_as_checked_out_on_windows

    panel = UNIVERSAL / "mp3_tools" / "m4b_maker.py"
    assert sha256_as_checked_out_on_windows(panel) != MAKER_PHASE0_HASH
    tree = ast.parse(panel.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            modules |= {f"{node.module}.{alias.name}" for alias in node.names}
    assert "mp3_tools.m4b_maker_processing" not in modules
    assert "shared.ffmpeg_utils" not in modules
    assert "mp3_tools.m4b_maker_batch" in modules
