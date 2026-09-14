"""The M4B Metadata Editor per-Book engine — v0.6.4 Phase 9.

``mp3_tools/m4b_metadata_processing.py`` executes one frozen Editor ``BookPlan``:
copy the source to **private staging**, perform the frozen action there through
the shared ``metadata`` authorities (Save writes only the frozen intent; Clear
All clears everything, keeps chapters and reapplies only the frozen intent;
Remove Series Numbering strips numbering and keeps the Series Name), apply the
positional chapter edits and the explicit cover through ``m4b_artwork``,
validate the finished copy, and publish it atomically. A failure at any step
publishes nothing; the source is never written; the audio is never re-encoded.

Media are the Phase 7 fixtures: a six-second AAC container with two chapters
and a cover, tagged through the shared writer; vendor atoms via mutagen.
"""

from __future__ import annotations

import ast
import hashlib
import shutil
import subprocess
from pathlib import Path, PurePath

import pytest

from shared import ffmpeg_utils, metadata, output_paths
from shared.book_workspace import SharedMetadata, WorkspaceSnapshot, set_shared_metadata
from shared.cancellation import ConversionCancelled
from shared.importing import (
    IdFactory, ImportOptions, ImportedFile, ImportedFileSnapshot, ImportRoot, Revision,
)

from mp3_tools import m4b_artwork
from mp3_tools import m4b_metadata_plan as mp
from mp3_tools import m4b_metadata_processing as proc
from mp3_tools import m4b_metadata_workflow as wf
from mp3_tools.m4b_metadata_plan import EditorAction, EditorRunOptions
from mp3_tools.m4b_metadata_processing import BookOutcome, ProcessingError
from mp3_tools.m4b_metadata_workflow import ObservationStore

from test_importing import make_config
from test_m4b_metadata_workflow import _META, _ff, m4b, require_ffmpeg, vendor_series

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
MODULE = UNIVERSAL / "mp3_tools" / "m4b_metadata_processing.py"

_IDS = IdFactory("ex-")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def container(tmp_path_factory) -> Path:
    require_ffmpeg()
    work = tmp_path_factory.mktemp("editor-engine")
    meta = work / "meta.txt"
    meta.write_text(_META, encoding="utf-8")
    _ff("-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-c:a", "aac", "-b:a", "48k",
        str(work / "audio.m4a"))
    _ff("-f", "lavfi", "-i", "color=c=red:s=32x32:d=1", "-frames:v", "1", str(work / "c.jpg"))
    target = work / "base.m4b"
    _ff("-i", str(work / "audio.m4a"), "-i", str(work / "c.jpg"), "-i", str(meta),
        "-map", "0:a", "-map", "1:v", "-map_metadata", "2", "-map_chapters", "2",
        "-c:a", "copy", "-c:v", "copy", "-disposition:v:0", "attached_pic", str(target))
    return target


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
        directory = tmp_path / "Outputs" / "M4B-Metadata-Outputs" / f"M4B-Metadata-{counter['n']}"
        directory.mkdir(parents=True)
        return output_paths.RunReservation(
            tool_key="m4b_metadata", base_directory=tmp_path / "Outputs",
            tool_directory=directory.parent, run_directory=directory, run_number=counter["n"])

    return make


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def listing(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")} if root.exists() else set()


def audio_md5(path: Path) -> str:
    out = subprocess.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-v", "error", "-i", str(path),
                          "-map", "0:a", "-c", "copy", "-f", "md5", "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert out.returncode == 0, out.stdout[-400:]
    return out.stdout.decode("ascii", "replace").strip()


def raw_atoms(path: Path) -> dict:
    from mutagen.mp4 import MP4
    tags = MP4(str(path)).tags
    return dict(tags) if tags else {}


def covr_of(path: Path) -> list:
    return list(raw_atoms(path).get("covr", []))


def png(path: Path) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 12), (10, 200, 30)).save(path, format="PNG")
    return path


def imported(sources: Path, relative: str, path: Path) -> ImportedFile:
    occurrence = _IDS.next_id("occurrence")
    return ImportedFile(occurrence, path, ImportRoot("r", sources, 0), PurePath(relative),
                        wf.EDITOR_TYPE.type_id, f"id-{occurrence}-{relative.replace('/', '-')}")


def build(container, sources, *specs, unreadable=()):
    entries = []
    for relative, tags in specs:
        path = m4b(container, sources / relative, **tags)
        entries.append(imported(sources, relative, path))
    for relative in unreadable:
        path = sources / relative
        path.write_bytes(b"not an mp4")
        entries.append(imported(sources, relative, path))
    result = wf.import_folder(wf.new_workspace(id_factory=_IDS),
                              ImportedFileSnapshot(Revision(1), tuple(entries)),
                              id_factory=_IDS, store=ObservationStore())
    return result.mutation.workspace, result.store


def shared_with(space: WorkspaceSnapshot, **values) -> WorkspaceSnapshot:
    return set_shared_metadata(
        space, SharedMetadata(fields=wf.SHARED_FIELDS, values=values)).workspace


def plan(space, store, reserve, action=EditorAction.SAVE_TAGS, options=None) -> mp.RunPlan:
    return mp.plan_run(space, store, action=action, options=options or EditorRunOptions(),
                       reservation=reserve(), catalog=wf.EDITOR_CATALOG,
                       import_options=ImportOptions.for_catalog(wf.EDITOR_CATALOG),
                       effective_config=make_config(), id_factory=_IDS)


def run(made: mp.RunPlan, entry: mp.BookPlan, **kwargs) -> BookOutcome:
    return proc.build_book(entry, work_root=made.work_root, **kwargs)


def collect():
    seen = []
    return seen, seen.append


# --------------------------------------------------------------------------- #
# Save Tags
# --------------------------------------------------------------------------- #


def test_save_writes_only_the_frozen_intent_and_preserves_the_rest(container, sources, reserve):
    path = m4b(container, sources / "a.m4b", title="Source T", artist="Source A", album="Alb",
               year="2020", genre="G", comment="C", series="Saga", series_part="2")
    entry_file = imported(sources, "a.m4b", path)
    result = wf.import_folder(wf.new_workspace(id_factory=_IDS),
                              ImportedFileSnapshot(Revision(1), (entry_file,)),
                              id_factory=_IDS, store=ObservationStore())
    space, store = result.mutation.workspace, result.store
    space = wf.set_book_field(space, "title", "New Title").workspace
    before_hash, before_audio = sha(path), audio_md5(path)
    before_atoms = raw_atoms(path)
    made = plan(space, store, reserve)
    entry = made.books[0]
    events, listener = collect()
    outcome = run(made, entry, on_event=listener)
    assert isinstance(outcome, BookOutcome) and outcome.succeeded
    assert outcome.published == entry.published and entry.published.is_file()
    tags = metadata.read_m4b_tags(entry.published)
    assert tags["title"] == "New Title"
    for key in ("artist", "album", "year", "genre", "comment", "series", "series_part"):
        assert tags[key] == metadata.read_m4b_tags(path)[key], key
    assert tags["has_cover"] is True
    assert metadata.read_chapter_titles(entry.published) == ["Opening", "Closing"]
    after = raw_atoms(entry.published)
    assert {k: v for k, v in before_atoms.items() if k != "\xa9nam"} == {
        k: v for k, v in after.items() if k != "\xa9nam"}, "unrelated atoms untouched"
    assert sha(path) == before_hash and audio_md5(entry.published) == before_audio
    assert not entry.staging_dir.exists()
    assert [e.stage for e in events][-1] == "completed"


def test_save_with_nothing_frozen_copies_the_source_byte_for_byte(container, sources, reserve):
    space, store = build(container, sources, ("a.m4b", dict(title="T")))
    made = plan(space, store, reserve)
    assert run(made, made.books[0]).succeeded
    assert sha(made.books[0].published) == sha(made.books[0].source)


def test_save_never_migrates_an_observed_vendor_series_but_writes_an_explicit_one(
        container, sources, reserve):
    path = vendor_series(m4b(container, sources / "v.m4b", album="Alb"), name="Tone Saga", part="3")
    entry_file = imported(sources, "v.m4b", path)
    result = wf.import_folder(wf.new_workspace(id_factory=_IDS),
                              ImportedFileSnapshot(Revision(1), (entry_file,)),
                              id_factory=_IDS, store=ObservationStore())
    space, store = result.mutation.workspace, result.store
    space = wf.set_book_field(space, "title", "Only Title").workspace
    made = plan(space, store, reserve)
    assert run(made, made.books[0]).succeeded
    atoms = raw_atoms(made.books[0].published)
    assert "----:com.pilabor.tone:SERIES" in atoms and "----:com.apple.iTunes:SERIES" not in atoms
    edited = wf.set_book_field(space, "series", "Canon Saga").workspace
    made2 = plan(edited, store, reserve)
    assert run(made2, made2.books[0]).succeeded
    tags = metadata.read_m4b_tags(made2.books[0].published)
    assert tags["series"] == "Canon Saga" and tags["series_source"] == "freeform:com.apple.iTunes"
    assert "----:com.pilabor.tone:SERIES" not in raw_atoms(made2.books[0].published), (
        "the shared writer's conflict handling applies to an explicit write")


def test_save_replaces_artwork_only_when_frozen(container, sources, reserve, tmp_path):
    art = png(tmp_path / "new.png")
    space, store = build(container, sources, ("a.m4b", {}), ("b.m4b", {}))
    space = wf.set_book_field(space, "artwork", str(art)).workspace   # Book 1 only
    made = plan(space, store, reserve)
    for entry in made.books:
        assert run(made, entry).succeeded
    replaced, kept = made.books
    assert bytes(covr_of(replaced.published)[0]) == art.read_bytes()
    assert covr_of(kept.published) == covr_of(kept.source), "no replacement → preserved"
    assert audio_md5(replaced.published) == audio_md5(replaced.source), "cover embed: no re-encode"


def test_save_applies_positional_chapter_edits_without_touching_the_audio(container, sources,
                                                                          reserve):
    space, store = build(container, sources, ("a.m4b", dict(series="Saga")))
    space = wf.set_book_field(space, "chapter_titles", "\nThe End").workspace
    made = plan(space, store, reserve)
    entry = made.books[0]
    before_audio = audio_md5(entry.source)
    assert entry.chapter_edits == (None, "The End")
    assert run(made, entry).succeeded
    assert metadata.read_chapter_titles(entry.published) == ["Opening", "The End"]
    assert audio_md5(entry.published) == before_audio
    assert metadata.read_m4b_tags(entry.published)["series"] == "Saga", "freeform atoms survive"
    assert covr_of(entry.published), "the cover survives the chapter remux"


# --------------------------------------------------------------------------- #
# Clear All Tags (keep chapters)
# --------------------------------------------------------------------------- #


def test_clear_all_removes_metadata_and_artwork_but_keeps_chapters(container, sources, reserve):
    space, store = build(container, sources, ("a.m4b", dict(title="T", artist="A", series="Saga",
                                                             series_part="2", year="2020")))
    made = plan(space, store, reserve, EditorAction.CLEAR_ALL_TAGS)
    entry = made.books[0]
    before_audio = audio_md5(entry.source)
    assert run(made, entry).succeeded
    tags = metadata.read_m4b_tags(entry.published)
    for key in ("title", "artist", "year", "series", "series_part"):
        assert not tags.get(key), key
    assert tags["has_cover"] is False
    assert metadata.read_chapter_titles(entry.published) == ["Opening", "Closing"]
    assert audio_md5(entry.published) == before_audio
    assert sha(entry.source) != sha(entry.published)
    assert metadata.read_m4b_tags(entry.source)["title"] == "T", "source untouched"


def test_clear_all_reapplies_only_explicit_values_and_artwork(container, sources, reserve,
                                                             tmp_path):
    art = png(tmp_path / "again.png")
    space, store = build(container, sources, ("a.m4b", dict(title="Source T", artist="A",
                                                             genre="Old")))
    space = wf.set_book_field(space, "title", "Kept").workspace
    space = wf.set_book_field(space, "artist", "A").workspace      # equal → not reapplied
    space = wf.set_book_field(space, "chapter_titles", "First\n").workspace
    space = shared_with(space, comment="Shared C", artwork=str(art))
    made = plan(space, store, reserve, EditorAction.CLEAR_ALL_TAGS)
    entry = made.books[0]
    assert run(made, entry).succeeded
    tags = metadata.read_m4b_tags(entry.published)
    assert tags["title"] == "Kept" and tags["comment"] == "Shared C"
    assert not tags.get("artist") and not tags.get("genre"), "prefilled-but-unchanged stays cleared"
    assert bytes(covr_of(entry.published)[0]) == art.read_bytes()
    assert metadata.read_chapter_titles(entry.published) == ["First", "Closing"]


# --------------------------------------------------------------------------- #
# Remove Series Numbering
# --------------------------------------------------------------------------- #


def test_remove_series_numbering_strips_numbering_and_keeps_the_name(container, sources, reserve):
    path = m4b(container, sources / "a.m4b", title="T", series="Saga", series_part="4",
               comment="keep me")
    entry_file = imported(sources, "a.m4b", path)
    result = wf.import_folder(wf.new_workspace(id_factory=_IDS),
                              ImportedFileSnapshot(Revision(1), (entry_file,)),
                              id_factory=_IDS, store=ObservationStore())
    space, store = result.mutation.workspace, result.store
    assert "trkn" in raw_atoms(path) and "\xa9mvi" in raw_atoms(path)
    space = wf.set_book_field(space, "title", "Pending").workspace   # must NOT be applied
    made = plan(space, store, reserve, EditorAction.REMOVE_SERIES_NUMBERING)
    entry = made.books[0]
    before_audio = audio_md5(entry.source)
    assert run(made, entry).succeeded
    tags = metadata.read_m4b_tags(entry.published)
    assert tags["series"] == "Saga" and tags["series_source"] == "freeform:com.apple.iTunes"
    assert not tags.get("series_part")
    atoms = raw_atoms(entry.published)
    assert "trkn" not in atoms and "\xa9mvi" not in atoms and "\xa9mvc" not in atoms
    assert "----:com.apple.iTunes:SERIES-PART" not in atoms
    assert tags["title"] == "T" and tags["comment"] == "keep me"
    assert tags["has_cover"] is True
    assert metadata.read_chapter_titles(entry.published) == ["Opening", "Closing"]
    assert audio_md5(entry.published) == before_audio


def test_remove_series_numbering_keeps_a_vendor_or_movement_series_name(container, sources,
                                                                        reserve):
    vendor = vendor_series(m4b(container, sources / "v.m4b"), name="Tone Saga", part="3")
    moved = vendor_series(m4b(container, sources / "m.m4b"), movement=("Moves", 4))
    entries = (imported(sources, "v.m4b", vendor), imported(sources, "m.m4b", moved))
    result = wf.import_folder(wf.new_workspace(id_factory=_IDS),
                              ImportedFileSnapshot(Revision(1), entries),
                              id_factory=_IDS, store=ObservationStore())
    made = plan(result.mutation.workspace, result.store, reserve,
                EditorAction.REMOVE_SERIES_NUMBERING)
    for entry in made.books:
        assert run(made, entry).succeeded
    v_tags = metadata.read_m4b_tags(made.books[0].published)
    assert v_tags["series"] == "Tone Saga" and not v_tags.get("series_part")
    assert "----:com.pilabor.tone:PART" not in raw_atoms(made.books[0].published)
    m_tags = metadata.read_m4b_tags(made.books[1].published)
    assert m_tags["series"] == "Moves" and m_tags["series_source"] == "movement"
    assert not m_tags.get("series_part")


def test_the_shared_authority_gained_a_keep_series_name_option_with_the_old_default(
        container, sources):
    path = m4b(container, sources / "a.m4b", series="Saga", series_part="4")
    kept = sources / "kept.m4b"
    shutil.copy2(path, kept)
    metadata.clear_series_numbering(path)
    assert not metadata.read_m4b_tags(path).get("series"), "the default still strips the name"
    metadata.clear_series_numbering(kept, keep_series_name=True)
    tags = metadata.read_m4b_tags(kept)
    assert tags["series"] == "Saga" and not tags.get("series_part")


# --------------------------------------------------------------------------- #
# Staging, atomic publication and failure safety
# --------------------------------------------------------------------------- #


def test_the_copy_lands_in_staging_and_never_directly_at_the_destination(container, sources,
                                                                          reserve, monkeypatch):
    space, store = build(container, sources, ("a.m4b", dict(title="T")))
    space = wf.set_book_field(space, "title", "X").workspace
    made = plan(space, store, reserve)
    entry = made.books[0]
    copies: list[Path] = []
    real = shutil.copy2

    def spy(src, dst, *a, **k):
        copies.append(Path(dst))
        return real(src, dst, *a, **k)

    monkeypatch.setattr(proc.shutil, "copy2", spy)
    staged = proc.stage_book(entry, work_root=made.work_root)
    assert staged.succeeded and copies == [entry.staged]
    assert entry.staged.is_file() and not entry.published.exists()
    assert output_paths.assert_contained(made.work_root, entry.staged)
    proc.discard_staging(entry, work_root=made.work_root)


def test_a_tag_write_failure_after_the_copy_publishes_nothing(container, sources, reserve,
                                                             monkeypatch):
    space, store = build(container, sources, ("a.m4b", dict(title="T")))
    space = wf.set_book_field(space, "title", "X").workspace
    made = plan(space, store, reserve)
    entry = made.books[0]

    def explode(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(metadata, "write_m4b_tags", explode)
    outcome = run(made, entry)
    assert not outcome.succeeded and outcome.failure_stage == "tags"
    assert "boom" in outcome.failure_detail
    assert not entry.published.exists() and not entry.staging_dir.exists()
    assert listing(made.run_directory) == set(), "no visible copy merely because copy2 succeeded"


def test_a_chapter_write_failure_after_the_tags_publishes_nothing(container, sources, reserve,
                                                                 monkeypatch):
    space, store = build(container, sources, ("a.m4b", {}))
    space = wf.set_book_field(space, "chapter_titles", "New\n").workspace
    made = plan(space, store, reserve)
    entry = made.books[0]
    monkeypatch.setattr(metadata, "apply_chapter_titles",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("chap")))
    outcome = run(made, entry)
    assert not outcome.succeeded and outcome.failure_stage == "chapters"
    assert not entry.published.exists() and not entry.staging_dir.exists()


def test_a_cover_embed_failure_after_the_tags_publishes_nothing(container, sources, reserve,
                                                               tmp_path, monkeypatch):
    art = png(tmp_path / "ok.png")
    space, store = build(container, sources, ("a.m4b", {}))
    space = wf.set_book_field(space, "title", "X").workspace
    space = wf.set_book_field(space, "artwork", str(art)).workspace
    made = plan(space, store, reserve)
    entry = made.books[0]
    monkeypatch.setattr(m4b_artwork, "embed_cover",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("covr")))
    outcome = run(made, entry)
    assert not outcome.succeeded and outcome.failure_stage == "cover"
    assert not entry.published.exists() and not entry.staging_dir.exists()
    assert listing(made.run_directory) == set()


def test_an_unusable_cover_fails_before_the_copy_and_publishes_nothing(container, sources,
                                                                       reserve, tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"nope")
    space, store = build(container, sources, ("a.m4b", {}))
    space = wf.set_book_field(space, "artwork", str(bad)).workspace
    made = plan(space, store, reserve)
    entry = made.books[0]
    outcome = run(made, entry)
    assert not outcome.succeeded and outcome.failure_stage == "artwork"
    assert not entry.published.exists() and not entry.staging_dir.exists()


def test_a_validation_failure_publishes_nothing(container, sources, reserve, monkeypatch):
    space, store = build(container, sources, ("a.m4b", {}))
    made = plan(space, store, reserve, EditorAction.CLEAR_ALL_TAGS)
    entry = made.books[0]

    def refuse(*a, **k):
        raise ProcessingError("not usable", stage="validate", detail="x")

    monkeypatch.setattr(proc, "validate_staged", refuse)
    outcome = run(made, entry)
    assert not outcome.succeeded and outcome.failure_stage == "validate"
    assert not entry.published.exists() and not entry.staging_dir.exists()


def test_validation_catches_a_clear_that_left_metadata_behind(container, sources, reserve,
                                                             monkeypatch):
    space, store = build(container, sources, ("a.m4b", dict(title="T")))
    made = plan(space, store, reserve, EditorAction.CLEAR_ALL_TAGS)
    entry = made.books[0]
    monkeypatch.setattr(metadata, "clear_metadata_keep_chapters", lambda path: None)
    outcome = run(made, entry)
    assert not outcome.succeeded and outcome.failure_stage == "validate"
    assert not entry.published.exists()


def test_a_source_that_vanished_after_planning_fails_safely(container, sources, reserve):
    space, store = build(container, sources, ("a.m4b", {}), ("b.m4b", {}))
    made = plan(space, store, reserve)
    made.books[0].source.unlink()
    first = run(made, made.books[0])
    assert not first.succeeded and first.failure_stage == "source"
    assert run(made, made.books[1]).succeeded
    assert not made.books[0].published.exists() and made.books[1].published.is_file()


def test_publication_refuses_an_existing_destination_and_keeps_the_candidate(container, sources,
                                                                             reserve):
    space, store = build(container, sources, ("a.m4b", {}))
    made = plan(space, store, reserve)
    entry = made.books[0]
    assert proc.stage_book(entry, work_root=made.work_root).succeeded
    entry.published.write_bytes(b"someone else's")
    with pytest.raises(ProcessingError):
        proc.publish_book(entry, work_root=made.work_root)
    assert entry.published.read_bytes() == b"someone else's" and entry.staged.is_file()
    proc.discard_staging(entry, work_root=made.work_root)


def test_cancellation_at_a_checkpoint_removes_only_operation_owned_state(container, sources,
                                                                        reserve):
    space, store = build(container, sources, ("a.m4b", dict(title="T")))
    space = wf.set_book_field(space, "title", "X").workspace
    made = plan(space, store, reserve)
    entry = made.books[0]
    before = sha(entry.source)
    calls = {"n": 0}

    def checkpoint():
        calls["n"] += 1
        if calls["n"] >= 2:
            raise ConversionCancelled()

    outcome = run(made, entry, checkpoint=checkpoint)
    assert outcome.cancelled and not outcome.succeeded
    assert not entry.published.exists() and not entry.staging_dir.exists()
    assert made.run_directory.is_dir() and listing(made.run_directory) == set()
    assert sha(entry.source) == before


def test_build_refuses_anything_but_an_editor_book_plan(container, sources, reserve):
    space, store = build(container, sources, ("a.m4b", {}))
    made = plan(space, store, reserve)
    with pytest.raises(ProcessingError):
        proc.build_book("nope", work_root=made.work_root)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------------- #


def test_the_engine_uses_the_shared_authorities_and_re_encodes_nothing():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            modules |= {f"{node.module}.{alias.name}" for alias in node.names}
    for banned in ("tkinter", "threading", "queue", "subprocess", "shared.book_workspace",
                   "shared.job_ui", "shared.job_control", "shared.importing",
                   "shared.import_coordination", "shared.numbering", "shared.subprocess_utils",
                   "mutagen", "PIL", "mp3_tools.m4b_metadata_editor",
                   "mp3_tools.m4b_metadata_workflow", "mp3_tools.m4b_maker_processing",
                   "mp3_tools.mp3_processing", "wave", "json"):
        assert banned not in modules, banned
    for required in ("shared.metadata", "shared.ffmpeg_utils", "shared.cancellation",
                     "mp3_tools.m4b_artwork", "mp3_tools.m4b_staging",
                     "mp3_tools.m4b_metadata_plan"):
        assert required in modules, required
    calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    # The authorities are handed to one guarded step runner, so they appear as
    # attribute references rather than direct call heads.
    references = {ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for authority in ("metadata.write_m4b_tags", "metadata.clear_metadata_keep_chapters",
                      "metadata.clear_series_numbering", "metadata.apply_chapter_titles",
                      "m4b_artwork.embed_cover", "m4b_artwork.load_cover",
                      "shutil.copy2"):
        assert authority in references, authority
    for never in ("sp.run", "subprocess.run", "ffmpeg_cmd", "run_ffmpeg"):
        assert not any(c.endswith(never) for c in calls), never
    declared = {node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    for owned_elsewhere in ("JobController", "SuccessNumbers", "publish_staged",
                            "require_owned", "RunResult"):
        assert owned_elsewhere not in declared, owned_elsewhere


def test_the_editor_panel_is_still_byte_identical():
    from test_plan6_boundaries import PHASE0_PANEL_HASHES, sha256_as_checked_out_on_windows

    panel = UNIVERSAL / "mp3_tools" / "m4b_metadata_editor.py"
    assert sha256_as_checked_out_on_windows(panel) == PHASE0_PANEL_HASHES[
        "mp3_tools/m4b_metadata_editor.py"]
    assert "m4b_metadata_processing" not in panel.read_text(encoding="utf-8")
