"""M4B Converter: a real M4B with chapters through the real controls, every chapter's MP3 compared with its exact interval of the source.

The source's complete decode, straight through with no seeking, is the reference. Each output is compared with the samples the source's
chapter table says belong there, which is what a duration check can never do: the historical priming defect had correct durations.
"""

from __future__ import annotations

import json
from pathlib import Path

from journeys.common import Context, expect_clean_close, log_text, media_fixtures, open_tool, oracle, scenario, wait_for_job, wait_until

TOOL = "m4b_converter"


def _add_book(session, fixture: Path) -> None:
    session.click(TOOL, "importer.list.buttons[add_files]")
    session.file_dialog(fixture, title="Select .m4b files")
    wait_until(lambda: len(session.widget(TOOL, "importer.list.listbox").get("items", [])) >= 1, 30, "the book to be listed")
    session.settle()


@scenario("converter.split-by-chapter", tool="m4b-converter", layers=("native", "media"), tier="journey",
          summary="Split by chapter chosen with a real click; five chapters come out in order, each matching its exact source interval, first and last included")
def split(context: Context) -> None:
    report = context.report
    entry = context.fixtures.entries["book-m4b"]
    book = context.fixtures.get("book-m4b")
    before = context.source_hashes([book.path])
    session = context.app(last_tool=TOOL)
    open_tool(session, TOOL)
    _add_book(session, book.path)
    session.click(TOOL, "rb_split")
    wait_until(lambda: session.widget(TOOL, "rb_split").get("selected"), 5, "Split by chapter to be selected")
    session.screenshot("ready")
    session.click(TOOL, "btn_convert")
    report.equal("the run ended", wait_for_job(session, TOOL), "SUCCEEDED")
    session.screenshot("finished")
    reveals = wait_until(lambda: reveal_log(session), 10, "the finished run to ask for its folder to be revealed")
    report.equal("the finished run reveals its own folder", [item["path"] for item in reveals], [str(context.run_dir(TOOL))])
    outputs = sorted(context.run_dir(TOOL).rglob("*.mp3"))
    sections = entry["sections"]
    report.equal("one MP3 per chapter", len(outputs), len(sections))
    reference = oracle.decode_pcm(context.tools, book.path)
    for index, (output, section) in enumerate(zip(outputs, sections)):
        label = f"chapter {index + 1}"
        report.check(f"{label}: named for its title, in order", section["title"] in output.name, output.name)
        oracle.inspect_audio(context.tools, output, report, label=label, codec="mp3", container="mp3", duration=section["seconds"],
                             duration_tolerance=0.06, tags={"title": section["title"], "artist": "Fixture Author", "album": "Fixture Series"})
        start, end = media_fixtures.section_interval(sections, index)
        candidate = oracle.decode_pcm(context.tools, output)
        oracle.inspect_interval(report, label=label, reference=reference[start:end], candidate=candidate)
        report.check(f"{label}: carries its own tone", oracle.tone_power(candidate[int(0.1 * oracle.ORACLE_RATE):int(0.5 * oracle.ORACLE_RATE)],
                                                                         oracle.ORACLE_RATE, section["tone"]) > 0.01)
        probed = oracle.probe(context.tools, output)
        report.check(f"{label}: artwork carried over", oracle.artwork_stream(probed) is not None)
    context.require_unchanged(before)
    expect_clean_close(context, session)


@scenario("converter.whole-book-replace-metadata", tool="m4b-converter", layers=("native", "media"), tier="journey",
          summary="Whole book with Replace metadata: the typed values and the chosen VBR quality reach the one MP3, whose audio matches the entire source")
def whole(context: Context) -> None:
    report = context.report
    book = context.fixtures.get("book-m4b")
    session = context.app(last_tool=TOOL)
    open_tool(session, TOOL)
    _add_book(session, book.path)
    session.click(TOOL, "rb_replace")
    wait_until(lambda: not session.widget(TOOL, "title_entry").get("disabled"), 5, "the replacement fields to open")
    session.type_into(TOOL, "title_entry", "Replaced Title")
    session.type_into(TOOL, "artist_entry", "Replaced Artist")
    session.type_into(TOOL, "album_entry", "Replaced Album")
    session.type_into(TOOL, "entry_quality", "5")
    session.click(TOOL, "btn_convert")
    report.equal("the run ended", wait_for_job(session, TOOL), "SUCCEEDED")
    session.screenshot("finished")
    outputs = sorted(context.run_dir(TOOL).rglob("*.mp3"))
    report.equal("one MP3 for the whole book", len(outputs), 1)
    oracle.inspect_audio(context.tools, outputs[0], report, label="whole book", codec="mp3", container="mp3", duration=15.691, duration_tolerance=0.08,
                         tags={"title": "Replaced Title", "artist": "Replaced Artist", "album": "Replaced Album"})
    reference, candidate = oracle.decode_pcm(context.tools, book.path), oracle.decode_pcm(context.tools, outputs[0])
    oracle.inspect_interval(report, label="whole book", reference=reference, candidate=candidate)
    # Quality 5 is well below the default 2: the same audio must really have been encoded smaller, or the typed value went nowhere.
    bitrate = int(oracle.probe(context.tools, outputs[0])["format"]["bit_rate"])
    report.check("the typed VBR quality reached the encoder", bitrate < 160000, f"{bitrate} bit/s")
    expect_clean_close(context, session)


@scenario("converter.corrupt-source", tool="m4b-converter", layers=("native", "media"), tier="adverse",
          summary="A truncated M4B and bytes named .m4b: nothing is converted, no output folder appears, the sources stay as they were")
def corrupt(context: Context) -> None:
    report = context.report
    broken = context.fixtures.path("book-truncated")
    fake = context.fixtures.path("book-garbage")
    before = context.source_hashes([broken, fake])
    session = context.app(last_tool=TOOL)
    open_tool(session, TOOL)
    session.click(TOOL, "importer.list.buttons[add_files]")
    session.file_dialog([broken, fake], title="Select .m4b files")
    wait_until(lambda: len(session.widget(TOOL, "importer.list.listbox").get("items", [])) == 2, 30, "both files to be listed")
    session.click(TOOL, "btn_convert")
    state = wait_for_job(session, TOOL)
    session.screenshot("finished")
    report.check("the run does not report success", state in ("FAILED", "COMPLETED_WITH_FAILURES"), state)
    outputs = list((context.output_base / "M4B-Converter-Outputs").rglob("*.mp3")) if (context.output_base / "M4B-Converter-Outputs").exists() else []
    report.equal("no MP3 was published", outputs, [])
    text = log_text(session, TOOL) + log_text(session, TOOL, "details_text")
    report.check("the log names what could not be read", "Broken Book" in text and "Not A Book" in text, text[-500:])
    context.require_unchanged(before)
    expect_clean_close(context, session)


@scenario("converter.cancel-during-encode", tool="m4b-converter", layers=("native", "media"), tier="adverse",
          summary="Two books; Cancel clicked while FFmpeg encodes a late chapter of the second: the encoder stops in budget, the first book stays valid, the partial one is rolled back")
def cancel(context: Context) -> None:
    report = context.report
    done_book, long_book = context.fixtures.path("book-plain-m4b"), context.fixtures.path("book-long-m4b")
    session = context.app(last_tool=TOOL)
    open_tool(session, TOOL)
    _add_book(session, done_book)
    _add_book(session, long_book)
    wait_until(lambda: len(session.widget(TOOL, "importer.list.listbox").get("items", [])) == 2, 30, "both books to be listed")
    session.click(TOOL, "rb_split")
    wait_until(lambda: session.widget(TOOL, "rb_split").get("selected"), 5, "Split by chapter to be selected")
    session.click(TOOL, "btn_convert")
    run = context.run_dir(TOOL)

    def encoding():
        return [pid for pid in session.job.pids() if native_image(pid) == "ffmpeg.exe"] and session.read(TOOL, "jobs.state") == "RUNNING"

    def a_late_chapter_is_encoding():
        return encoding() and any(True for _ in (run / "Long Book").glob("01 - *.mp3"))

    wait_until(lambda: run.exists() and a_late_chapter_is_encoding(), 120, "the second book's first chapter to finish and a later one to be encoding")
    context.notes["files_when_cancelled"] = sorted(item.relative_to(run).as_posix() for item in run.rglob("*") if item.is_file())
    report.check("FFmpeg is really running when Cancel is clicked", bool(encoding()))
    began = oracle.time_now()
    session.click(TOOL, "jobs.controls.buttons[CANCEL]")
    state = wait_for_job(session, TOOL, timeout=30)
    seconds = oracle.time_now() - began
    session.screenshot("cancelled")
    report.equal("the run says it was cancelled", state, "CANCELLED")
    report.check("settled inside the 5 s budget", seconds <= 5.0, f"{seconds:.2f} s")
    context.notes["cancel_seconds"] = round(seconds, 3)
    wait_until(lambda: not [pid for pid in session.job.pids() if native_image(pid) == "ffmpeg.exe"], 5, "the encoder to be gone")
    kept = sorted((run / "Plain Book").glob("*.mp3"))
    report.equal("the finished book's two chapters stay", len(kept), 2)
    sections = context.fixtures.entries["book-plain-m4b"]["sections"]
    for index, (output, section) in enumerate(zip(kept, sections)):
        oracle.inspect_audio(context.tools, output, report, label=f"kept chapter {index + 1}", codec="mp3", duration=section["seconds"], duration_tolerance=0.06)
    # The product's contract: "A partially split book must never look complete", so the interrupted book's finished chapters go with it.
    left = sorted(item.relative_to(run).as_posix() for item in (run / "Long Book").rglob("*") if item.is_file()) if (run / "Long Book").exists() else []
    report.equal("the interrupted book left nothing behind", left, [])
    expect_clean_close(context, session)


def reveal_log(session) -> list[dict]:
    """What the application asked Explorer to show. The test launcher records it instead of opening a window on the owner's desktop."""
    path = session.work / "runtime" / "reveals.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def native_image(pid: int) -> str:
    from helpers import winproc

    return Path(winproc._image_name(pid)).name.lower()
