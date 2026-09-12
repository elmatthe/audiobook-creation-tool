"""The integrated MP3 Tool under attack — v0.6.3 focused MP3 plan, Phase 10.

Phases 3–9 each proved their own contract in isolation. This module crosses
them: a few compact end-to-end scenarios through the real panel, the real
engines and short real media, plus the matrix cases the focused plan's Phase
10 names that no earlier module already pins. Nothing here is a second copy of
an existing unit test; where media content is irrelevant the case is a pure
planning one over placeholder files.

Scenarios:

- **A — many Books**: nested import, repeated Albums, a duplicate, a
  manually mixed-parent Book, an empty Book, an invalid Book refused up
  front, one failing Book, Unicode and Windows-invalid characters; exact
  dispositions and no cross-Book contamination.
- **B — numbering / titles**: 120 tracks from a Start # of 7, width and
  ``TRCK`` on real media, partial Chapter Titles, no doubled prefix.
- **C — frozen retry**: A / B / C with Time and artwork, every live value
  changed, Retry Failed re-runs B's failed occurrence only and publishes B
  whole with the frozen values.
- **D — Combine fallback**: FAST success, FAST-ineligible → Safe, forced FAST
  failure → Safe, with the reasons in Detailed and the final constituent
  carrying the signed Time — through paths with apostrophes, spaces and
  Unicode.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402
from mutagen.id3 import ID3  # noqa: E402

from shared import ffmpeg_utils, image_capabilities, output_paths  # noqa: E402
from shared import subprocess_utils as sp  # noqa: E402
from shared.book_workspace import BookDisposition  # noqa: E402
from shared.importing import ImportOptions  # noqa: E402
from shared.job_control import JobEventKind, JobState  # noqa: E402

from mp3_tools import mp3_artwork, mp3_plan, mp3_processing as proc, mp3_tool  # noqa: E402
from mp3_tools import mp3_workflow as wf  # noqa: E402

from test_import_coordination import RealThreads  # noqa: E402
from test_import_traversal import touch  # noqa: E402
from test_importing import make_config  # noqa: E402
from test_mp3_artwork import heic  # noqa: E402
from test_mp3_orchestration import events_of, settle, statuses, wait_for  # noqa: E402
from test_mp3_tool_ui import (  # noqa: E402,F401  (fixtures are collected by name)
    add_files,
    import_folder,
    make_panel,
    reservations_under,
    tk_root,
    windows_theme,
)
from test_mp3_write_id3 import duration, junk_tag, png, sha, texts, tone  # noqa: E402

pytestmark = pytest.mark.skipif(
    not ffmpeg_utils.have_ffmpeg(), reason="ffmpeg/ffprobe not available in this environment")

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def tone_at(path: Path, *, rate: int = 44100, channels: int = 2, seconds: float = 1.0,
            freq: int = 440) -> Path:
    """A real tone at a chosen sample rate / channel count (FAST eligibility)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sp.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
            "-ac", str(channels), "-ar", str(rate), "-c:a", "libmp3lame", "-b:a", "64k",
            str(path)], check=True)
    return path


def corrupt(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"this is not an mp3 at all")
    return path


def hashes(root: Path) -> dict[Path, str]:
    return {p: sha(p) for p in root.rglob("*") if p.is_file()}


def choose(panel, book_id: str) -> None:
    assert panel.navigator.choose(book_id)


def book_named(panel, folder: str):
    """The Book whose tracks come from *folder* (by its first source's parent)."""
    for book in panel.workspace.books:
        files = book.files.files
        if files and files[0].path.parent.name == folder:
            return book
    raise AssertionError(f"no Book from {folder!r}")


# --------------------------------------------------------------------------- #
# Scenario A — many Books
# --------------------------------------------------------------------------- #


def test_scenario_a_many_books_one_operation(make_panel, tmp_path, monkeypatch):
    made = reservations_under(tmp_path, monkeypatch)
    lib = tmp_path / "Library"
    # Nested: one Book per directory that directly holds MP3s, however deep.
    junk_tag(tone(lib / "Series" / "One" / "01 One.mp3"), album="Dune", artist="Herbert",
             title="")
    junk_tag(tone(lib / "Series" / "One" / "02 Two.mp3", freq=500), album="Dune",
             artist="Herbert", title="")
    # The same Album again, in another folder: collision-safe destinations.
    junk_tag(tone(lib / "Series" / "Two" / "01 One.mp3", freq=550), album="Dune",
             artist="Herbert", title="")
    # Unicode tags and a Windows-invalid character in the Album.
    junk_tag(tone(lib / "Frank's Café" / "01 Ünïcode.mp3", freq=600),
             album="Дюна: часть?", artist="Фрэнк", title="")
    # One Book whose second track is broken: a real, retryable failure.
    junk_tag(tone(lib / "Broken" / "01 One.mp3", freq=650), album="Broken", artist="X")
    corrupt(lib / "Broken" / "02 Two.mp3")
    junk_tag(tone(lib / "Broken" / "03 Three.mp3", freq=700), album="Broken", artist="X")
    # Files for a manually mixed-parent Book, added by hand from two folders.
    junk_tag(tone(tmp_path / "Loose A" / "a.mp3", freq=750), album="", artist="", title="")
    junk_tag(tone(tmp_path / "Loose B" / "b.mp3", freq=800), album="", artist="", title="")
    before = hashes(tmp_path)

    panel = make_panel()
    import_folder(panel, lib)
    assert panel.workspace.count == 4, "one Book per containing directory, nested included"
    folders = {book_named(panel, name).book_id: name
               for name in ("One", "Two", "Frank's Café", "Broken")}
    # A duplicate copies configuration and no files: an empty Book.
    choose(panel, book_named(panel, "One").book_id)
    panel.navigator.invoke(panel.navigator.DUPLICATE)
    empty = panel.workspace.current
    assert empty.files.is_empty and empty.configuration == book_named(
        panel, "One").configuration
    # A mixed-parent Book: Add Files from two directories into one Book.
    panel.navigator.invoke(panel.navigator.ADD)
    mixed = panel.workspace.current
    add_files(panel, tmp_path / "Loose A" / "a.mp3", tmp_path / "Loose B" / "b.mp3")
    assert panel.workspace.current.book_id == mixed.book_id
    assert panel.workspace.current.file_count == 2
    assert wf.source_folder_name(panel.workspace.current) is None, "no trustworthy folder"
    assert panel.workspace.count == 6

    # An invalid Book refuses the whole operation before anything is reserved.
    panel.type_start_number("seven?")
    assert panel.write_id3_tags() is False
    assert made == [] and make_panel.dialogs[-1][0] == "error"
    panel.type_start_number("")

    assert panel.write_id3_tags() is True
    settle(panel)
    assert len(made) == 1, "one reservation for six Books"
    plan = panel.last_plan
    result = panel.last_result
    assert result.state is JobState.COMPLETED_WITH_FAILURES
    dispositions = {folders.get(b.book_id, b.book_id): result.disposition_for(b.book_id)
                    for b in panel.workspace.books}
    assert dispositions["One"] is BookDisposition.SUCCEEDED
    assert dispositions["Two"] is BookDisposition.SUCCEEDED
    assert dispositions["Frank's Café"] is BookDisposition.SUCCEEDED
    assert dispositions["Broken"] is BookDisposition.FAILED
    assert dispositions[empty.book_id] is BookDisposition.SKIPPED_EMPTY
    assert dispositions[mixed.book_id] is BookDisposition.SUCCEEDED, "later Books continue"
    assert result.retryable_book_ids == (book_named(panel, "Broken").book_id,)
    shown = {folders.get(b.book_id, b.book_id): panel.book_status_for(b.book_id)
             for b in panel.workspace.books}
    assert shown == {"One": "Completed", "Two": "Completed", "Frank's Café": "Completed",
                     "Broken": "Failed", empty.book_id: "Skipped",
                     mixed.book_id: "Completed"}

    # Destinations: repeated Albums are collision-safe, invalid characters are
    # sanitised through the one shared authority, and every folder is its own.
    plans = {folders.get(b.book_id, b.book_id): plan.book_for(b.book_id)
             for b in panel.workspace.books if plan.book_for(b.book_id) is not None}
    assert plans["One"].folder_name == "Dune"
    assert plans["Two"].folder_name != "Dune" and plans["Two"].folder_name.startswith("Dune")
    cafe = plans["Frank's Café"].folder_name
    assert cafe == output_paths.sanitize_component("Дюна: часть?")
    assert ":" not in cafe and "?" not in cafe and "Дюна" in cafe
    assert plans[mixed.book_id].folder_name.startswith("Book "), "no folder to borrow from"
    assert len({entry.published_dir for entry in plan.books}) == len(plan.books)
    assert sorted(p.name for p in plan.run_directory.iterdir()) == sorted(
        [plans[k].folder_name for k in ("One", "Two", "Frank's Café", mixed.book_id)]
        + [mp3_plan.WORK_DIRNAME])
    assert not plans["Broken"].published_dir.exists(), "a failed Book publishes nothing"

    # No cross-Book contamination: each published track carries its own Book's
    # frozen metadata and nothing of a neighbour's.
    for key in ("One", "Two"):
        for track in plans[key].tracks:
            frames = texts(track.published)
            assert frames["TALB"] == "Dune" and frames["TPE1"] == "Herbert"
            assert frames["TIT2"] == track.title
    frames = texts(plans["Frank's Café"].tracks[0].published)
    assert frames["TALB"] == "Дюна: часть?" and frames["TPE1"] == "Фрэнк"
    assert frames["TIT2"] == "Ünïcode"
    for track in plans[mixed.book_id].tracks:
        frames = texts(track.published)
        assert "TALB" not in frames and "TPE1" not in frames, "blank stays blank"
    assert {p.name for p in plans["One"].published_dir.iterdir()} == {"01 One.mp3", "02 Two.mp3"}
    assert {p.name for p in plans[mixed.book_id].published_dir.iterdir()} == {"01 a.mp3", "02 b.mp3"}
    # Sources and everything beside them: byte-identical, nothing new written there.
    assert hashes(tmp_path / "Library") == {p: h for p, h in before.items()
                                            if p.is_relative_to(tmp_path / "Library")}
    assert hashes(tmp_path / "Loose A") == {p: h for p, h in before.items()
                                            if p.is_relative_to(tmp_path / "Loose A")}
    assert not any(p.is_relative_to(tmp_path / "Outputs") for p in before)


# --------------------------------------------------------------------------- #
# Scenario B — numbering and titles
# --------------------------------------------------------------------------- #


def test_scenario_b_numbering_and_titles_over_120_tracks(make_panel, tmp_path, monkeypatch):
    """Pure planning over placeholders: media content is irrelevant to a name."""
    made = reservations_under(tmp_path, monkeypatch)
    root = tmp_path / "Big"
    for index in range(1, 121):
        touch(root / f"{index:03d} Chapter {index}.mp3", "not audio")
    panel = make_panel()
    import_folder(panel, root)
    assert panel.workspace.current.file_count == 120
    panel.type_start_number("7")
    panel.type_chapter_titles("Prologue\nThe Beginning\n\n\n")   # two typed, blank lines collapse
    assert panel.chapter_titles_text().startswith("Prologue")
    plan = mp3_plan.plan_run(
        panel.workspace, panel.store, operation=mp3_plan.MP3Operation.WRITE_ID3,
        reservation=output_paths.reserve_run_directory(mp3_tool.TOOL_KEY),
        catalog=wf.MP3_CATALOG, import_options=ImportOptions.for_catalog(wf.MP3_CATALOG),
        effective_config=make_config(), id_factory=panel._ids, numbers=panel.book_numbers)
    book = plan.books[0]
    assert [t.track_number for t in book.tracks] == list(range(7, 127)), "unpadded integers"
    assert book.tracks[0].filename == "007 Prologue.mp3"
    assert book.tracks[1].filename == "008 The Beginning.mp3"
    assert book.tracks[2].filename == "009 Chapter 3.mp3", "defaults remain for the rest"
    assert book.tracks[-1].filename == "126 Chapter 120.mp3"
    assert all(len(t.filename.split(" ", 1)[0]) == 3 for t in book.tracks), "one width"
    assert not any(t.title[:1].isdigit() for t in book.tracks), "no doubled source number"
    assert [t.title for t in book.tracks[2:5]] == ["Chapter 3", "Chapter 4", "Chapter 5"]
    assert len({t.filename for t in book.tracks}) == 120

    # Auto-number OFF: no prefix, no track number, names still collision-free.
    panel.var_auto_number.set(False)
    panel.on_auto_number()
    plan_off = mp3_plan.plan_run(
        panel.workspace, panel.store, operation=mp3_plan.MP3Operation.WRITE_ID3,
        reservation=output_paths.reserve_run_directory(mp3_tool.TOOL_KEY),
        catalog=wf.MP3_CATALOG, import_options=ImportOptions.for_catalog(wf.MP3_CATALOG),
        effective_config=make_config(), id_factory=panel._ids, numbers=panel.book_numbers)
    off = plan_off.books[0]
    assert all(t.track_number is None for t in off.tracks)
    assert off.tracks[0].filename == "Prologue.mp3"
    assert off.tracks[2].filename == "Chapter 3.mp3"
    assert len({t.filename for t in off.tracks}) == 120
    assert len(made) == 2


def test_scenario_b_trck_is_unpadded_on_real_media_across_the_width_change(
        make_panel, tmp_path, monkeypatch):
    """Three real tracks numbered 99, 100, 101: the filename width is three
    for all of them and the embedded TRCK is the plain integer."""
    made = reservations_under(tmp_path, monkeypatch)
    root = tmp_path / "W"
    for index, name in enumerate(("01 A.mp3", "02 B.mp3", "03 C.mp3")):
        junk_tag(tone(root / name, freq=400 + 40 * index), album="W", title="")
    panel = make_panel()
    import_folder(panel, root)
    panel.type_start_number("99")
    panel.write_id3_tags()
    settle(panel)
    book = panel.last_plan.books[0]
    assert panel.last_result.state is JobState.SUCCEEDED
    assert [t.filename for t in book.tracks] == ["099 A.mp3", "100 B.mp3", "101 C.mp3"]
    assert [texts(t.published)["TRCK"] for t in book.tracks] == ["99", "100", "101"]
    assert [texts(t.published)["TIT2"] for t in book.tracks] == ["A", "B", "C"]


# --------------------------------------------------------------------------- #
# Scenario C — frozen retry with Time, artwork and destinations
# --------------------------------------------------------------------------- #


def test_scenario_c_retry_keeps_every_frozen_value_and_publishes_b_whole(
        make_panel, tmp_path, monkeypatch):
    made = reservations_under(tmp_path, monkeypatch)
    lib = tmp_path / "Lib"
    for folder, names in {"A": ("01.mp3", "02.mp3"), "B": ("01.mp3", "02.mp3", "03.mp3"),
                          "C": ("01.mp3",)}.items():
        for index, name in enumerate(names):
            junk_tag(tone(lib / folder / name, freq=300 + 50 * index), album=folder)
    corrupt(lib / "B" / "02.mp3")
    art = png(tmp_path / "cover.png")
    art_hash = sha(art)
    panel = make_panel()
    import_folder(panel, lib)
    panel.surface.set_shared_text("time_delta", "0.5")
    panel.surface.set_shared_text("artist", "Frozen Artist")
    panel.on_shared_change("artwork", str(art))
    b = book_named(panel, "B")
    choose(panel, b.book_id)
    panel.type_chapter_titles("Frozen One\nFrozen Two\nFrozen Three")
    panel.write_id3_tags()
    settle(panel)
    first = panel.last_result
    plan = panel.last_plan
    plan_b = plan.book_for(b.book_id)
    assert first.disposition_for(b.book_id) is BookDisposition.FAILED
    assert not plan_b.published_dir.exists()
    kept = [t for t in plan_b.tracks if t.source.name != "02.mp3"]
    assert all(t.staged.is_file() for t in kept)
    kept_hashes = {t.staged: sha(t.staged) for t in kept}
    a_c_before = {t.published: t.published.stat().st_mtime_ns
                  for key in ("A", "C") for t in plan.book_for(book_named(panel, key).book_id).tracks}

    # Change every live value the retry could be tempted to read.
    panel.surface.set_shared_text("time_delta", "-0.3")
    panel.surface.set_shared_text("artist", "Someone Else")
    panel.on_shared_change("artwork", "")
    panel.type_chapter_titles("Changed\nChanged\nChanged")
    panel.type_start_number("50")
    panel.select_tracks(0)
    panel.move_down()
    panel.navigator.invoke(panel.navigator.REMOVE)          # B itself is removed live
    assert panel.workspace.count == 2
    junk_tag(tone(lib / "B" / "02.mp3", freq=999), album="B")

    engine_kwargs: list[dict] = []
    real_run = proc.write_id3_run

    def spy(plan_arg, **kwargs):
        engine_kwargs.append(kwargs)
        return real_run(plan_arg, **kwargs)

    monkeypatch.setattr(mp3_tool.mp3_processing, "write_id3_run", spy)
    assert panel.retry_failed() is True
    settle(panel)
    second = panel.last_result
    assert len(made) == 1
    assert second.state is JobState.SUCCEEDED
    assert second.snapshot is first.snapshot is plan.capture
    assert second.result_for(b.book_id).snapshot is plan_b.snapshot
    failed_occurrence = plan_b.track_for(next(
        t.occurrence_id for t in plan_b.tracks if t.source.name == "02.mp3")).occurrence_id
    assert dict(engine_kwargs[0]["retry_items"]) == {b.book_id: (failed_occurrence,)}
    # B published whole, in the frozen folder, with every frozen value.
    assert plan_b.published_dir.is_dir()
    assert sorted(p.name for p in plan_b.published_dir.iterdir()) == [
        "01 Frozen One.mp3", "02 Frozen Two.mp3", "03 Frozen Three.mp3"]
    for track in plan_b.tracks:
        frames = texts(track.published)
        assert frames["TPE1"] == "Frozen Artist" and frames["TIT2"] == track.title
        assert abs(duration(track.published) - 1.5) < 0.3, "the frozen +0.5 s, not -0.3"
        apic = [f for k, f in ID3(track.published).items() if k.startswith("APIC")]
        assert len(apic) == 1 and apic[0].data == art.read_bytes()
    for track in kept:
        assert sha(track.published) == kept_hashes[track.staged], "reused, not remade"
    assert {p: p.stat().st_mtime_ns for p in a_c_before} == a_c_before, "A and C untouched"
    assert sha(art) == art_hash
    assert not plan.work_root.exists()
    assert panel.workspace.count == 2 and panel.last_plan is plan


# --------------------------------------------------------------------------- #
# Scenario D — Combine: FAST, ineligible → Safe, forced fallback, hard paths
# --------------------------------------------------------------------------- #


def test_scenario_d_combine_fast_ineligible_and_forced_fallback(make_panel, tmp_path, monkeypatch):
    made = reservations_under(tmp_path, monkeypatch)
    lib = tmp_path / "Lib's Own"
    fast = lib / "Frank's Dune — Часть 1"
    for index, name in enumerate(("01 O'Neil's café.mp3", "02 Back＼slash.mp3")):
        junk_tag(tone_at(fast / name, freq=330 + 50 * index), album="Дюна", title="")
    unlike = lib / "Mixed rates"
    junk_tag(tone_at(unlike / "01.mp3", rate=44100), album="Mixed")
    junk_tag(tone_at(unlike / "02.mp3", rate=22050, channels=1, freq=520), album="Mixed")
    before = hashes(lib)

    panel = make_panel()
    import_folder(panel, lib)
    # Time 0 is a clean copy, so the unlike constituents stay unlike: the one
    # honest way to reach the FAST-ineligible branch on real media.
    panel.combine_mp3s()
    settle(panel)
    result = panel.last_result
    plan = panel.last_plan
    assert result.state is JobState.SUCCEEDED
    fast_plan = plan.book_for(book_named(panel, fast.name).book_id)
    safe_plan = plan.book_for(book_named(panel, "Mixed rates").book_id)
    technical = [e.detail for e in events_of(panel, JobEventKind.TECHNICAL_DETAIL)]
    assert any("trying FAST" in d for d in technical)
    assert any("not valid here" in d and "Safe" in d for d in technical), technical
    assert not any(e.message.startswith("Book") and "failed" in e.message
                   for e in events_of(panel, JobEventKind.WARNING))
    detailed = panel.log.rendered(panel.log.details_text)
    assert "not valid here" in detailed and "trying FAST" in detailed
    for entry in (fast_plan, safe_plan):
        assert entry.combined_published.is_file()
        assert abs(duration(entry.combined_published) - 2.0) < 0.4
        frames = texts(entry.combined_published)
        assert frames["TIT2"] == entry.album == frames["TALB"]
        assert "TRCK" not in frames
        lines = entry.timestamps_published.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
    assert fast_plan.combined_filename == "Дюна.mp3"
    assert "O'Neil's café" in fast_plan.timestamps_published.read_text(encoding="utf-8")
    assert hashes(lib) == before

    # Forced FAST failure: Safe takes over, with the reason; and with a signed
    # Time every constituent -- the final one included -- carries +0.5 s.
    real_fast = proc._fast_concat_args
    monkeypatch.setattr(mp3_tool.mp3_processing, "_fast_concat_args",
                        lambda listfile, out: real_fast(listfile, out)[:-1]
                        + ["-no_such_option", str(out)])
    panel.surface.set_shared_text("time_delta", "0.5")
    panel.combine_mp3s()
    settle(panel)
    assert panel.last_result.state is JobState.SUCCEEDED
    fallback = [e for e in events_of(panel, JobEventKind.WARNING) if "switching to Safe" in e.message]
    assert len(fallback) == 2, "with the Time applied both Books are alike, and both fell back"
    assert all("no_such_option" in e.detail for e in fallback)
    for key in (fast.name, "Mixed rates"):
        entry = panel.last_plan.book_for(book_named(panel, key).book_id)
        assert entry.combined_published.is_file()
        assert abs(duration(entry.combined_published) - 3.0) < 0.4, (
            "two constituents at 1.5 s each: the final one got its +0.5 s too")
        assert len(entry.timestamps_published.read_text(encoding="utf-8").splitlines()) == 2
    assert "no_such_option" in panel.log.rendered(panel.log.details_text)
    assert len(made) == 2
    assert hashes(lib) == before


# --------------------------------------------------------------------------- #
# Matrix cases no earlier module pins
# --------------------------------------------------------------------------- #


def test_heic_artwork_follows_the_real_capability_probe(make_panel, tmp_path, monkeypatch):
    """No hard-coded HEIC assumption: the actual probe decides which half runs."""
    made = reservations_under(tmp_path, monkeypatch)
    capability = image_capabilities.heif_capability()
    root = tmp_path / "H"
    junk_tag(tone(root / "01.mp3"), album="H")
    panel = make_panel()
    import_folder(panel, root)
    offered = [pattern for _label, pattern in panel.artwork_filetypes()]
    if not capability.decode:
        assert not any(".heic" in pattern for pattern in offered)
        bad = tmp_path / "cover.heic"
        bad.write_bytes(b"\x00\x00\x00\x18ftypheic")
        with pytest.raises(mp3_artwork.ArtworkError):
            mp3_artwork.load_artwork(bad)
        return
    assert any(".heic" in pattern for pattern in offered)
    cover = heic(tmp_path / "cover.heic")
    panel.on_shared_change("artwork", str(cover))
    panel.write_id3_tags()
    settle(panel)
    assert panel.last_result.state is JobState.SUCCEEDED
    track = panel.last_plan.books[0].tracks[0]
    apic = [f for k, f in ID3(track.published).items() if k.startswith("APIC")]
    assert len(apic) == 1 and apic[0].mime == "image/png"
    assert apic[0].data[:8] == b"\x89PNG\r\n\x1a\n"


def test_a_failed_run_keeps_its_directory_and_a_later_run_never_reuses_it(
        make_panel, tmp_path, monkeypatch):
    """Phase 9 judgment call B, proved: retention is what keeps a retry's
    frozen destinations true, and the real allocator can never hand the
    retained number to a later run."""
    real = output_paths.reserve_run_directory
    base = tmp_path / "Base"
    monkeypatch.setattr(output_paths, "reserve_run_directory",
                        lambda key, **kw: real(key, base=base))
    root = tmp_path / "R"
    junk_tag(tone(root / "01.mp3"), album="R")
    corrupt(root / "02.mp3")
    panel = make_panel()
    import_folder(panel, root)
    panel.write_id3_tags()
    settle(panel)
    first_plan = panel.last_plan
    first_dir = first_plan.run_directory
    assert panel.last_result.state is JobState.COMPLETED_WITH_FAILURES
    assert first_dir.is_dir(), "kept: the retry's frozen destinations live here"
    assert first_plan.books[0].tracks[0].staged.is_file(), "the retained piece"
    # A later, unrelated run takes the next number, never the retained one.
    panel.select_tracks(1)
    panel.remove_selected_tracks()                      # the broken track goes
    panel.combine_mp3s()
    settle(panel)
    assert panel.last_result.state is JobState.SUCCEEDED
    later = panel.last_plan.run_directory
    assert later != first_dir and later.parent == first_dir.parent
    assert int(later.name.rsplit("-", 1)[1]) == int(first_dir.name.rsplit("-", 1)[1]) + 1
    # The first run can no longer be retried from the panel (it is not the
    # last plan), and nothing of it was touched by the later run.
    assert panel.retry_failed() is False
    assert first_plan.books[0].tracks[0].staged.is_file()
    assert not first_plan.books[0].published_dir.exists()


def test_a_not_attempted_book_is_shown_as_not_attempted(make_panel, tmp_path, monkeypatch):
    """Focused plan §26: ``NOT_ATTEMPTED -> Not attempted``. Phase 9 rendered it
    as Ready; a Book a cancelled run never reached is not merely ready, and
    the disposition is the authority."""
    panel = make_panel()
    made = reservations_under(tmp_path, monkeypatch)
    root = tmp_path / "N"
    for folder in ("A", "B"):
        junk_tag(tone(root / folder / "01.mp3"), album=folder)
    import_folder(panel, root)

    def cancelled(plan, *, checkpoint=None, **kwargs):
        panel.job_controller.request_cancel()
        checkpoint()
        raise AssertionError("checkpoint must raise")

    monkeypatch.setattr(mp3_tool.mp3_processing, "write_id3_run", cancelled)
    panel.write_id3_tags()
    settle(panel)
    result = panel.last_result
    assert result.state is JobState.CANCELLED
    assert all(result.disposition_for(b.book_id) is BookDisposition.NOT_ATTEMPTED
               for b in panel.workspace.books)
    assert statuses(panel) == ["Not attempted", "Not attempted"]
    assert "Queued" not in statuses(panel), "Queued is live presentation only"
    panel.navigator.invoke(panel.navigator.ADD)
    assert panel.book_status_text() == "Ready", "a Book the result never knew"


def test_queued_is_derived_from_the_active_batch_and_stored_nowhere():
    """Phase 9 judgment call A: ``Queued`` may stay only as pure presentation."""
    source = (UNIVERSAL / "mp3_tools" / "mp3_tool.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    panel = next(node for node in ast.walk(tree)
                 if isinstance(node, ast.ClassDef) and node.name == "MP3ToolUI")
    # The only place the word is produced is the derivation, and that reads
    # the active attempt and the run's events -- never a stored per-Book state.
    producers = [node for node in ast.walk(panel)
                 if isinstance(node, ast.Return) and isinstance(node.value, ast.Name)
                 and node.value.id == "STATUS_QUEUED"]
    assert len(producers) == 1
    stores = [node for node in ast.walk(panel)
              if isinstance(node, (ast.Assign, ast.AnnAssign))
              and any(isinstance(t, ast.Attribute)
                      and ("book_status" in t.attr or "statuses" in t.attr
                           or t.attr.endswith("_state"))
                      for t in (node.targets if isinstance(node, ast.Assign)
                                else [node.target]))]
    assert stores == [], "no per-Book status is stored on the panel"
    derivation = next(node for node in ast.walk(panel)
                      if isinstance(node, ast.FunctionDef) and node.name == "book_status_for")
    called = {node.func.attr for node in ast.walk(derivation)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "disposition_for" in called, "the disposition stays authoritative"
    assert "STATUS_NOT_ATTEMPTED" in source and '"Not attempted"' in source


def test_track_failure_then_book_finalisation_failure_are_told_apart(
        make_panel, tmp_path, monkeypatch):
    """One run holds both failure identities: a track failure with its real
    occurrence (retryable) and an item-less finalisation failure (not)."""
    made = reservations_under(tmp_path, monkeypatch)
    lib = tmp_path / "F"
    junk_tag(tone(lib / "Track" / "01.mp3"), album="Track")
    corrupt(lib / "Track" / "02.mp3")
    junk_tag(tone(lib / "Final" / "01.mp3", freq=500), album="Final")
    junk_tag(tone(lib / "Final" / "02.mp3", freq=550), album="Final")
    real_publish = mp3_plan.publish_book

    def publish(book):
        if book.folder_name == "Final":
            raise OSError("the destination vanished")
        return real_publish(book)

    monkeypatch.setattr(mp3_tool.mp3_processing.mp3_plan, "publish_book", publish)
    panel = make_panel()
    import_folder(panel, lib)
    panel.write_id3_tags()
    settle(panel)
    result = panel.last_result
    track_book = book_named(panel, "Track")
    final_book = book_named(panel, "Final")
    assert result.disposition_for(track_book.book_id) is BookDisposition.FAILED
    assert result.disposition_for(final_book.book_id) is BookDisposition.FAILED
    assert result.retryable_book_ids == (track_book.book_id,)
    fatal = tuple(result.result_for(final_book.book_id).failures.fatal)
    assert len(fatal) == 1 and fatal[0].item_id is None and fatal[0].retryable is False
    assert result.result_for(track_book.book_id).failures.fatal == ()
    failures = events_of(panel, JobEventKind.FAILURE)
    assert sorted(e.item_id is None for e in failures) == [False, True]
    assert result.can_retry_failed is True
    assert not panel.last_plan.book_for(final_book.book_id).published_dir.exists()
    assert all(t.staged.is_file()
               for t in panel.last_plan.book_for(final_book.book_id).tracks), (
        "a finalisation failure keeps every staged piece")


def test_cancel_prevents_later_books_from_starting_under_real_threads(
        make_panel, tmp_path, monkeypatch):
    panel = make_panel(thread_factory=RealThreads())
    made = reservations_under(tmp_path, monkeypatch)
    root = tmp_path / "C"
    for folder in ("A", "B", "C"):
        junk_tag(tone(root / folder / "01.mp3"), album=folder)
    import_folder(panel, root)
    wait_for(panel, lambda: panel.workspace.count == 3)
    started: list[str] = []
    real_book = proc.write_id3_book

    def counting(book, **kwargs):
        started.append(book.folder_name)
        report = real_book(book, **kwargs)
        if len(started) == 1:
            panel.job_controller.request_cancel()
        return report

    monkeypatch.setattr(mp3_tool.mp3_processing, "write_id3_book", counting)
    panel.write_id3_tags()
    wait_for(panel, lambda: not panel.is_running)
    assert started == ["A"], "no later Book started after the cancel request"
    result = panel.last_result
    assert result.state is JobState.CANCELLED
    a, b, c = panel.workspace.books
    assert result.disposition_for(a.book_id) is BookDisposition.SUCCEEDED
    assert result.disposition_for(b.book_id) is BookDisposition.NOT_ATTEMPTED
    assert result.disposition_for(c.book_id) is BookDisposition.NOT_ATTEMPTED
    assert statuses(panel) == ["Completed", "Not attempted", "Not attempted"]


def test_explicitly_cleared_and_mixed_metadata_reach_the_output_exactly(
        make_panel, tmp_path, monkeypatch):
    """Cleared stays cleared, mixed is a marker not a value, both through a run."""
    made = reservations_under(tmp_path, monkeypatch)
    root = tmp_path / "M"
    junk_tag(tone(root / "01.mp3"), album="Same", artist="One")
    junk_tag(tone(root / "02.mp3", freq=500), album="Same", artist="Two")
    panel = make_panel()
    import_folder(panel, root)
    assert panel.mixed_text("artist") == mp3_tool.MIXED_MARK
    assert panel.mixed_text("album") == ""
    assert panel.surface.book_value("album") == "Same", "the majority seeds the field"
    assert panel.surface.book_value("artist") == "One", "a tie seeds the first seen, marked"
    panel.surface.set_book_text("album", "")                  # explicitly cleared
    panel.surface.set_book_text("artist", "")                 # the marked one, cleared too
    panel.write_id3_tags()
    settle(panel)
    assert panel.last_result.state is JobState.SUCCEEDED
    for track in panel.last_plan.books[0].tracks:
        frames = texts(track.published)
        assert "TALB" not in frames, "cleared means absent, never the source's value"
        assert "TPE1" not in frames, "cleared means absent, whatever the sources said"
        assert frames["TIT2"] == track.title


# --------------------------------------------------------------------------- #
# Architecture, re-checked structurally
# --------------------------------------------------------------------------- #


def _tree(relative: str) -> ast.Module:
    return ast.parse((UNIVERSAL / relative).read_text(encoding="utf-8"))


def _calls(tree: ast.AST) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                found.add(node.func.attr)
            elif isinstance(node.func, ast.Name):
                found.add(node.func.id)
    return found


def test_the_mp3_modules_keep_one_authority_for_each_concern():
    tool = _tree("mp3_tools/mp3_tool.py")
    plan = _tree("mp3_tools/mp3_plan.py")
    engine = _tree("mp3_tools/mp3_processing.py")
    workflow = _tree("mp3_tools/mp3_workflow.py")
    artwork = _tree("mp3_tools/mp3_artwork.py")
    for tree, name in ((tool, "tool"), (plan, "plan"), (engine, "engine"),
                       (workflow, "workflow"), (artwork, "artwork")):
        defined = {node.name for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        for foreign in ("sanitize_component", "sanitize_relative", "reserve_run_directory",
                        "DestinationPlanner", "effective_value", "disabled_fields",
                        "JobController", "RetryRequest", "retry_failed_books",
                        "ImportCoordinator", "ImportedFileManager", "scan_roots",
                        "decodable_suffixes", "probe_heif"):
            assert foreign not in defined, (name, foreign)
    # One JobController per operation, constructed in exactly one place, and
    # never inside a loop over Books.
    sites = [node for node in ast.walk(tool)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "JobController"]
    assert len(sites) == 1
    for loop in (n for n in ast.walk(tool) if isinstance(n, (ast.For, ast.While))):
        assert sites[0] not in ast.walk(loop)
    assert "JobController" not in _calls(engine) and "JobController" not in _calls(plan)
    # The retry is the shared one and reuses the frozen snapshot: the panel
    # never captures or plans again for it.
    retry = next(node for node in ast.walk(tool)
                 if isinstance(node, ast.FunctionDef) and node.name == "retry_failed")
    assert "retry_failed_books" in _calls(retry)
    for rebuilt in ("plan_run", "capture_workspace_run", "reserve_run_directory",
                    "_reserve_run", "RunSnapshot", "capture_run"):
        assert rebuilt not in _calls(retry), rebuilt
    # Collision and sanitising live in output_paths; the plan asks, never re-does.
    assert {"plan", "plan_directory", "sanitize_component"} & _calls(plan)
    literals = {node.value for node in ast.walk(artwork)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not any(v in (".heic", ".heif") for v in literals), "no hard-coded capability list"
    sources = {name: (UNIVERSAL / f"mp3_tools/{name}").read_text(encoding="utf-8")
               for name in ("mp3_tool.py", "mp3_plan.py", "mp3_processing.py",
                            "mp3_workflow.py", "mp3_artwork.py")}
    for name in sources:
        imported = set()
        for node in ast.walk(_tree(f"mp3_tools/{name}")):
            if isinstance(node, ast.Import):
                imported |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        assert not any(m.startswith("pillow_heif") for m in imported), name
        assert "rmtree" not in _calls(_tree(f"mp3_tools/{name}")), (
            name, "no broad recursive cleanup")
    assert "ffmpeg_log" not in sources["mp3_tool.py"]
    engine_calls = _calls(engine)
    assert "save_error_log" not in {
        node.func.id for f in ast.walk(engine) if isinstance(f, ast.FunctionDef)
        and f.name in ("write_id3_book", "combine_book", "_stage_clean_copy",
                       "_combine_constituents")
        for node in ast.walk(f) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }, "normal processing never depends on ffmpeg_log.txt"
    assert "write" not in {
        node.func.attr for node in ast.walk(engine)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "source"
    }, "no source write"
    assert "threading" not in {n.names[0].name for n in ast.walk(engine)
                               if isinstance(n, ast.Import)}
    assert engine_calls


def test_the_launcher_and_the_other_panels_are_where_they_were():
    from shared import config

    launcher = _tree("launcher.py")
    tools = next(node for node in ast.walk(launcher)
                 if isinstance(node, (ast.Assign, ast.AnnAssign))
                 and any(isinstance(t, ast.Name) and t.id == "TOOLS"
                         for t in (node.targets if isinstance(node, ast.Assign)
                                   else [node.target])))
    assert len(tools.value.elts) == 6
    assert config.get_effective().project.version == "0.6.2"
    for panel in ("mp3_tools/m4b_maker.py", "mp3_tools/m4b_metadata_editor.py",
                  "mp3_tools/m4b_converter.py"):
        text = (UNIVERSAL / panel).read_text(encoding="utf-8")
        assert "book_workspace" not in text and "mp3_workflow" not in text, panel
        assert "mp3_plan" not in text and "mp3_processing" not in text, panel


def test_the_hardening_suite_leaves_no_thread_root_or_callback_behind(make_panel, tk_root):
    import threading

    panel = make_panel()
    panel.close()
    panel.destroy()
    assert not [entry for entry in tk_root.tk.call("after", "info")]
    workers = [t for t in threading.enumerate() if t.name.startswith("mp3-")]
    assert workers == []
