"""The multi-Book Combine pipeline — v0.6.3 focused MP3 plan, Phase 8.

``mp3_processing.combine_run`` runs one frozen Phase 5 Combine ``RunPlan``: every
constituent track is staged with the frozen signed Time applied (the final one
too), FAST concat is tried automatically when the constituents are alike and
Safe WAV normalisation is used otherwise or on a FAST failure, the one combined
MP3 carries exactly the frozen metadata (Title = effective Album, no Track
Number, the frozen artwork), ``combined_time-stamps.txt`` lists the final Titles
at their adjusted offsets, and the Book is published whole or not at all.

Real media, as in Phase 7: FFmpeg-generated tones, junk-tagged by mutagen.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from mutagen.id3 import ID3

from shared import ffmpeg_utils
from shared import subprocess_utils as sp
from shared.book_workspace import SharedMetadata
from shared.importing import ImportOptions
from shared.job_control import JobState

from mp3_tools import mp3_plan as mp
from mp3_tools import mp3_processing as proc
from mp3_tools import mp3_workflow as wf
from mp3_tools.mp3_processing import ProcessingEvent

from test_importing import make_config
from test_mp3_write_id3 import (  # noqa: F401 - fixtures and helpers shared with Phase 7
    MODULE,
    book,
    duration,
    frames,
    imported,
    jpg,
    junk_tag,
    observe,
    png,
    reserve,
    sha,
    sources,
    texts,
    tone,
    workspace,
    _IDS,
)

pytestmark = pytest.mark.skipif(
    not ffmpeg_utils.have_ffmpeg(), reason="ffmpeg/ffprobe not available in this environment")


def plan(space, store, reserve, **kwargs) -> mp.RunPlan:
    return mp.plan_run(
        space, store, operation=mp.MP3Operation.COMBINE, reservation=reserve(),
        catalog=wf.MP3_CATALOG, import_options=ImportOptions.for_catalog(wf.MP3_CATALOG),
        effective_config=make_config(), id_factory=_IDS, **kwargs)


def one_book(sources, reserve, names=("01 One.mp3", "02 Two.mp3"), seconds=1.0,
             title="Old Title", **configuration):
    files = [imported(sources, "Book", name, seconds=seconds, title=title) for name in names]
    entry = book(files, **configuration)
    return plan(workspace(entry), observe(entry), reserve), entry


def timestamps(book_plan: mp.BookPlan) -> list[str]:
    return book_plan.timestamps_published.read_text(encoding="utf-8").splitlines()


def collect():
    seen: list[ProcessingEvent] = []
    return seen, seen.append


def stages(events, stage):
    return [e for e in events if e.stage == stage]


# --------------------------------------------------------------------------- #
# One Book, one combined MP3
# --------------------------------------------------------------------------- #


def test_one_book_becomes_exactly_one_combined_mp3_in_track_order(sources, reserve):
    made, entry = one_book(sources, reserve, names=("01.mp3", "02.mp3", "03.mp3"),
                           album="Dune", title="")
    report = proc.combine_run(made)
    plan_book = made.books[0]
    assert report.books[0].succeeded
    assert plan_book.combined_published.is_file()
    assert plan_book.timestamps_published.is_file()
    assert sorted(p.name for p in plan_book.published_dir.iterdir()) == [
        "Dune.mp3", "combined_time-stamps.txt"]
    total = sum(duration(f.path) for f in entry.files.files)
    assert abs(duration(plan_book.combined_published) - total) < 0.5
    lines = timestamps(plan_book)
    assert len(lines) == 3
    assert lines[0].startswith("01. 01 @ 00:00.000 (+00:01.0")
    assert lines[1].startswith("02. 02 @ 00:01.0")
    assert lines[2].startswith("03. 03 @ 00:02.0")
    assert [line.split(". ", 1)[1].split(" @")[0] for line in lines] == [
        "01", "02", "03"], "titles in frozen track order"
    assert report.books[0].result.state is JobState.SUCCEEDED
    assert set(report.books[0].result.completed_ids) == set(plan_book.snapshot.item_ids)


def test_books_are_never_combined_with_each_other(sources, reserve):
    a = book([imported(sources, "A", "1.mp3"), imported(sources, "A", "2.mp3")], album="A")
    b = book([imported(sources, "B", "1.mp3")], album="B")
    made = plan(workspace(a, b), observe(a, b), reserve)
    report = proc.combine_run(made)
    assert all(r.succeeded for r in report.books)
    assert abs(duration(made.books[0].combined_published) - 2.0) < 0.5
    assert abs(duration(made.books[1].combined_published) - 1.0) < 0.5
    assert made.books[0].combined_published.parent != made.books[1].combined_published.parent


def test_a_write_id3_plan_is_refused(sources, reserve):
    files = [imported(sources, "Book", "01.mp3")]
    entry = book(files)
    write = mp.plan_run(workspace(entry), observe(entry), operation=mp.MP3Operation.WRITE_ID3,
                        reservation=reserve(), catalog=wf.MP3_CATALOG,
                        import_options=ImportOptions.for_catalog(wf.MP3_CATALOG),
                        effective_config=make_config(), id_factory=_IDS)
    with pytest.raises(proc.ProcessingError):
        proc.combine_run(write)


# --------------------------------------------------------------------------- #
# Signed Time on every constituent, the final one included
# --------------------------------------------------------------------------- #


def test_zero_time_keeps_the_total_duration(sources, reserve):
    made, entry = one_book(sources, reserve, names=("a.mp3", "b.mp3"), time_delta="0")
    proc.combine_run(made)
    assert abs(duration(made.books[0].combined_published) - 2.0) < 0.4


def test_positive_time_is_added_to_every_constituent_including_the_last(sources, reserve):
    made, entry = one_book(sources, reserve, names=("a.mp3", "b.mp3", "c.mp3"), time_delta="0.5")
    proc.combine_run(made)
    combined = made.books[0].combined_published
    assert abs(duration(combined) - (3 * 1.0 + 3 * 0.5)) < 0.5, "three tracks, three appends"
    lines = timestamps(made.books[0])
    starts = [line.split("@ ")[1].split(" ")[0] for line in lines]
    assert starts[0] == "00:00.000"
    assert starts[1].startswith("00:01.5"), "the second chapter starts after 1.0 + 0.5"
    assert starts[2].startswith("00:03.0")
    assert lines[2].endswith(")") and "(+00:01.5" in lines[2], "the final constituent lists its own adjusted length"


def test_negative_time_is_trimmed_from_every_constituent(sources, reserve):
    made, entry = one_book(sources, reserve, names=("a.mp3", "b.mp3"), seconds=2.0,
                           time_delta="-0.5")
    proc.combine_run(made)
    assert abs(duration(made.books[0].combined_published) - 3.0) < 0.5
    starts = [line.split("@ ")[1].split(" ")[0] for line in timestamps(made.books[0])]
    assert starts[1].startswith("00:01.5")


def test_an_excessive_trim_fails_the_book_with_the_real_occurrences(sources, reserve):
    made, entry = one_book(sources, reserve, names=("a.mp3", "b.mp3"), time_delta="-9")
    report = proc.combine_run(made)
    result = report.books[0].result
    assert not report.books[0].succeeded
    assert result.state is JobState.COMPLETED_WITH_FAILURES
    assert {r.item_id for r in result.failures.records} == {f.occurrence_id for f in entry.files.files}
    assert all(r.retryable for r in result.failures.records)
    assert not made.books[0].published_dir.exists()
    assert not made.books[0].combined_staged.exists()


# --------------------------------------------------------------------------- #
# FAST first, Safe on failure or ineligibility
# --------------------------------------------------------------------------- #


def test_fast_is_tried_first_and_used_when_it_succeeds(sources, reserve):
    made, entry = one_book(sources, reserve, names=("a.mp3", "b.mp3"))
    events, listener = collect()
    report = proc.combine_run(made, on_event=listener)
    assert report.books[0].succeeded
    assert stages(events, "fast"), "FAST was attempted"
    assert not stages(events, "fallback")
    assert not stages(events, "safe")
    assert not (made.books[0].staging_dir / "wavs").exists(), "no WAV intermediates were needed"


def test_a_fast_failure_falls_back_to_safe_with_the_reason(sources, reserve, monkeypatch):
    made, entry = one_book(sources, reserve, names=("a.mp3", "b.mp3"))
    real = proc._fast_concat_args

    def broken(listfile, out_mp3):
        args = real(listfile, out_mp3)
        return args[:-1] + ["-no_such_option_for_ffmpeg", args[-1]]

    monkeypatch.setattr(proc, "_fast_concat_args", broken)
    events, listener = collect()
    report = proc.combine_run(made, on_event=listener)
    assert report.books[0].succeeded, "Safe rescued it"
    fallback = stages(events, "fallback")
    assert fallback and "FAST" in fallback[0].message
    assert "no_such_option" in fallback[0].detail or "ffmpeg" in fallback[0].detail.lower()
    assert stages(events, "safe")
    assert abs(duration(made.books[0].combined_published) - 2.0) < 0.5


def test_unlike_constituents_go_straight_to_safe_with_a_reason(sources, reserve):
    a = imported(sources, "Book", "a.mp3")
    b = imported(sources, "Book", "b.mp3")
    # A mono 22.05 kHz constituent: the concat demuxer cannot join it to a
    # stereo 44.1 kHz one, so FAST is not eligible and must not be tried.
    sp.run([ffmpeg_utils.ffmpeg_cmd(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=660:duration=1", "-ac", "1", "-ar", "22050",
            "-c:a", "libmp3lame", "-b:a", "48k", str(b.path)], check=True)
    junk_tag(b.path)
    entry = book([a, b])
    made = plan(workspace(entry), observe(entry), reserve)
    events, listener = collect()
    report = proc.combine_run(made, on_event=listener)
    assert report.books[0].succeeded
    assert not stages(events, "fast")
    ineligible = stages(events, "ineligible")
    assert ineligible and ("sample" in ineligible[0].detail.lower()
                           or "channel" in ineligible[0].detail.lower())
    assert stages(events, "safe")
    assert abs(duration(made.books[0].combined_published) - 2.0) < 0.5


# --------------------------------------------------------------------------- #
# The combined tag
# --------------------------------------------------------------------------- #


def test_the_combined_tag_is_exact(sources, reserve, tmp_path):
    cover = png(tmp_path / "cover.png")
    made, entry = one_book(sources, reserve, artist="Narrated By", album_artist="Author",
                           album="The Album", artwork=str(cover))
    proc.combine_run(made)
    out = made.books[0].combined_published
    present = set(frames(out))
    assert present == {"TIT2", "TPE1", "TPE2", "TALB", "APIC"}
    text = texts(out)
    assert text["TIT2"] == "The Album", "Title is the effective Album"
    assert text["TPE1"] == "Narrated By"
    assert text["TPE2"] == "Author"
    assert text["TALB"] == "The Album"
    apic, = [f for k, f in frames(out).items() if k == "APIC"]
    assert apic.mime == "image/png" and apic.data == cover.read_bytes() and int(apic.type) == 3
    for junk in ("TRCK", "TYER", "TCON", "TCOM", "COMM", "TXXX", "CHAP", "CTOC"):
        assert junk not in present, junk


def test_a_blank_album_leaves_no_title_and_invents_nothing(sources, reserve):
    made, entry = one_book(sources, reserve, artist="Someone")
    proc.combine_run(made)
    out = made.books[0].combined_published
    assert set(frames(out)) == {"TPE1"}
    assert out.parent.name == "Book", "the folder name is not smuggled into the tag"


def test_jpg_artwork_and_no_artwork(sources, reserve, tmp_path):
    cover = jpg(tmp_path / "cover.jpg")
    with_art, _ = one_book(sources, reserve, album="X", artwork=str(cover))
    proc.combine_run(with_art)
    apic, = [f for k, f in frames(with_art.books[0].combined_published).items() if k == "APIC"]
    assert apic.mime == "image/jpeg" and apic.data == cover.read_bytes()
    without, _ = one_book(sources, reserve, album="Y")
    proc.combine_run(without)
    assert "APIC" not in frames(without.books[0].combined_published), "old source art is gone"


def test_no_chapter_frames_are_embedded(sources, reserve):
    made, entry = one_book(sources, reserve, names=("a.mp3", "b.mp3", "c.mp3"), album="Z")
    proc.combine_run(made)
    tags = ID3(made.books[0].combined_published)
    assert not [k for k in tags.keys() if k.startswith(("CHAP", "CTOC"))]


# --------------------------------------------------------------------------- #
# combined_time-stamps.txt
# --------------------------------------------------------------------------- #


def test_timestamps_use_the_final_titles_and_adjusted_offsets(sources, reserve):
    made, entry = one_book(sources, reserve, names=("01 x.mp3", "02 y.mp3", "03 z.mp3"),
                           chapter_titles="Prologue\n\nChapter One", time_delta="0.5",
                           title="")
    proc.combine_run(made)
    lines = timestamps(made.books[0])
    assert [line.split(". ", 1)[1].split(" @")[0] for line in lines] == [
        "Prologue", "Chapter One", "z"]
    assert lines[0].startswith("01. Prologue @ 00:00.000")
    assert lines[1].startswith("02. Chapter One @ 00:01.5")
    assert lines[2].startswith("03. z @ 00:03.0")
    assert made.books[0].timestamps_published.read_text(encoding="utf-8").count("\n") >= 2
    assert "01 x" not in "".join(lines), "filenames are not the labels"


def test_the_timestamp_file_is_deterministic_for_the_same_plan(sources, reserve):
    made, entry = one_book(sources, reserve, names=("a.mp3", "b.mp3"))
    proc.combine_run(made)
    first = timestamps(made.books[0])
    again, _ = one_book(sources, reserve, names=("a2.mp3", "b2.mp3"))
    proc.combine_run(again)
    second = timestamps(again.books[0])
    assert [line.split(" @")[1] for line in first] == [line.split(" @")[1] for line in second]


# --------------------------------------------------------------------------- #
# Atomicity across Books, identity, safety
# --------------------------------------------------------------------------- #


def test_a_succeeds_b_fails_c_succeeds(sources, reserve):
    a = book([imported(sources, "A", "1.mp3"), imported(sources, "A", "2.mp3")], album="A")
    bad = imported(sources, "B", "2.mp3", junk=False)
    bad.path.write_bytes(b"not an mp3")
    b = book([imported(sources, "B", "1.mp3"), bad, imported(sources, "B", "3.mp3")], album="B")
    c = book([imported(sources, "C", "1.mp3")], album="C")
    made = plan(workspace(a, b, c), observe(a, b, c), reserve)
    report = proc.combine_run(made)
    ra, rb, rc = report.books
    assert ra.succeeded and rc.succeeded and not rb.succeeded
    assert made.books[0].combined_published.is_file() and made.books[2].combined_published.is_file()
    assert not made.books[1].published_dir.exists(), "B publishes nothing"
    record, = rb.result.failures.records
    assert record.item_id == bad.occurrence_id and record.retryable is True
    assert rb.result.retry().item_ids == (bad.occurrence_id,)
    assert rb.result.retry().snapshot is made.books[1].snapshot
    good = [t for t in made.books[1].tracks if t.occurrence_id != bad.occurrence_id]
    assert all(t.staged.is_file() for t in good), "B's good constituents stay for the retry"
    assert not made.books[1].combined_staged.exists()
    assert report.failed_book_ids == (b.book_id,)


def test_a_finalisation_failure_is_item_less_and_publishes_nothing(sources, reserve, monkeypatch):
    made, entry = one_book(sources, reserve, names=("a.mp3", "b.mp3"), album="F")
    real_fast = proc._fast_concat_args
    real_safe = proc._safe_concat_args

    def bad(listfile, out_mp3):
        return real_fast(listfile, out_mp3)[:-1] + ["-no_such_option", str(out_mp3)]

    monkeypatch.setattr(proc, "_fast_concat_args", bad)
    monkeypatch.setattr(proc, "_safe_concat_args", bad)
    report = proc.combine_run(made)
    result = report.books[0].result
    assert result.state is JobState.FAILED
    fatal = tuple(result.failures.fatal)
    assert len(fatal) == 1 and fatal[0].item_id is None and fatal[0].retryable is False
    assert set(result.completed_ids) == set(made.books[0].snapshot.item_ids), (
        "every constituent was staged fine; the failure is the Book's")
    assert result.has_retryable is False
    assert not made.books[0].published_dir.exists()
    assert all(t.staged.is_file() for t in made.books[0].tracks)


def test_sources_are_byte_identical_after_a_run(sources, reserve, tmp_path):
    a = book([imported(sources, "A", "1.mp3"), imported(sources, "A", "2.mp3")],
             time_delta="0.5", artwork=str(png(tmp_path / "c.png")))
    b = book([imported(sources, "B", "1.mp3", seconds=2.0)], time_delta="-0.5")
    made = plan(workspace(a, b), observe(a, b), reserve)
    before = {f.path: sha(f.path) for e in (a, b) for f in e.files.files}
    proc.combine_run(made)
    assert {path: sha(path) for path in before} == before


def test_live_edits_after_capture_cannot_reach_the_combine(sources, reserve):
    files = [imported(sources, "Book", "01.mp3"), imported(sources, "Book", "02.mp3")]
    entry = book(files, album="Frozen", chapter_titles="One\nTwo")
    space = workspace(entry)
    made = plan(space, observe(entry), reserve)
    edited = wf.set_book_field(space, "album", "Live").workspace
    edited = wf.set_book_field(edited, "chapter_titles", "X\nY").workspace
    edited = wf.set_book_field(edited, "time_delta", "5").workspace
    edited = SharedMetadata(wf.SHARED_FIELDS, {"album": "Shared"})
    proc.combine_run(made)
    out = made.books[0].combined_published
    assert texts(out)["TIT2"] == "Frozen" and out.name == "Frozen.mp3"
    assert [line.split(". ", 1)[1].split(" @")[0] for line in timestamps(made.books[0])] == ["One", "Two"]
    assert abs(duration(out) - 2.0) < 0.5, "the live Time of 5 never applied"


def test_successful_intermediates_are_cleaned_and_the_work_area_goes_when_empty(sources, reserve):
    made, entry = one_book(sources, reserve, names=("a.mp3", "b.mp3"), album="Clean")
    proc.combine_run(made)
    assert not made.books[0].staging_dir.exists(), "intermediates of a published Book are gone"
    assert not made.work_root.exists()
    assert sorted(p.name for p in made.run_directory.iterdir()) == ["Clean"]


def test_a_checkpoint_stops_between_stages(sources, reserve):
    from shared.cancellation import ConversionCancelled

    made, entry = one_book(sources, reserve, names=("a.mp3", "b.mp3", "c.mp3"))
    calls = {"n": 0}

    def checkpoint():
        calls["n"] += 1
        if calls["n"] == 3:
            raise ConversionCancelled("stop")

    with pytest.raises(ConversionCancelled):
        proc.combine_run(made, checkpoint=checkpoint)
    assert not made.books[0].published_dir.exists()


# --------------------------------------------------------------------------- #
# Boundaries
# --------------------------------------------------------------------------- #


def test_combine_lives_in_the_processing_module_and_reuses_the_helpers():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    declared = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert {"combine_run", "combine_book", "validate_combined_book",
            "_fast_concat_args", "_safe_concat_args", "_normalize_args"} <= declared
    engine = [node for node in ast.walk(tree)
              if isinstance(node, ast.FunctionDef)
              and node.name in ("combine_book", "_combine_constituents")]
    assert len(engine) == 2
    called = {n.func.id for fn in engine for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    called |= {n.func.attr for fn in engine for n in ast.walk(fn)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for reused in ("_stage_clean_copy", "prepare_staging", "publish_book", "artwork_for",
                   "write_concat_listfile", "settle"):
        assert reused in called or any(reused in n for n in called), reused
    for absent in ("JobController", "RetryRequest", "retry_failed_books", "Thread"):
        assert absent not in called, absent
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            modules |= {f"{node.module}.{alias.name}" for alias in node.names}
        elif isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
    for banned in ("tkinter", "threading", "queue", "shared.job_ui", "shared.job_control.JobController"):
        assert banned not in modules, banned


def test_the_report_types_are_shared_with_write_id3():
    assert proc.CombineReport is proc.RunReport
    assert proc.WriteId3Report is proc.RunReport
