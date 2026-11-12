"""M4B Metadata Editor: copies only, so the proof is that the audio stream is untouched, chapters and artwork survive, and only what was typed changed."""

from __future__ import annotations

from journeys.common import Context, expect_clean_close, log_text, open_tool, oracle, scenario, wait_for_job, wait_until

TOOL = "m4b_metadata"


def _stream_md5(context: Context, path) -> str:
    """The audio packets' digest, stream-copied: equal means the very same bytes of audio, whatever the container around them."""
    done = oracle._run([context.tools.ffmpeg, "-hide_banner", "-v", "error", "-i", str(path), "-map", "0:a:0", "-c", "copy", "-f", "md5", "-"], 60)
    if done.returncode != 0:
        raise oracle.OracleFailure(f"{path.name}: {done.stderr.decode('utf-8', 'replace')[:300]}")
    return done.stdout.decode("ascii", "replace").strip()


def _import(session, fixture) -> None:
    session.click(TOOL, "btn_add_files")
    session.file_dialog(fixture, title="Select M4B file(s)")
    wait_until(lambda: session.widget(TOOL, "surface._rows[title].book_entry").get("value"), 30, "the book's own values to appear")
    session.settle()


@scenario("metadata.save-tags-then-clear", tool="m4b-metadata-editor", layers=("native", "media"), tier="journey",
          summary="Album and Chapter 2's title typed and Save Tags; then Clear All Tags answered Yes in its real dialog. Audio, chapters, artwork and the original checked")
def save_then_clear(context: Context) -> None:
    report = context.report
    book = context.fixtures.get("book-m4b")
    before = context.source_hashes([book.path])
    source_md5 = _stream_md5(context, book.path)
    source_art = oracle.extract_artwork(context.tools, book.path, context.work / "source-art.jpg")
    expected_chapters = book.expected["chapters"]
    session = context.app(last_tool=TOOL)
    open_tool(session, TOOL)
    _import(session, book.path)
    report.equal("the book's own title is shown", session.widget(TOOL, "surface._rows[title].book_entry").get("value"), "Synthetic Book")
    session.type_into(TOOL, "surface._rows[album].book_entry", "Edited Album")
    # Line 2 of the box is chapter 2: reach it with real keys, as a person would.
    session.click(TOOL, "chapter_text")
    session.chord("control", "home")
    session.key("down")
    context.notes["chapter_box_before"] = session.widget(TOOL, "chapter_text").get("content")
    from adapters.windows import native_input

    native_input.type_text("Renamed ")
    session.input_count += 1
    session.screenshot("ready")
    session.click(TOOL, "btn_save")
    report.equal("Save Tags: the run ended", wait_for_job(session, TOOL), "SUCCEEDED")
    session.screenshot("saved")
    outputs = sorted(context.run_dir(TOOL, 1).rglob("*.m4b"))
    report.equal("Save Tags: one copy, named as the source", [item.name for item in outputs], ["Synthetic Book.m4b"])
    probed = oracle.inspect_audio(context.tools, outputs[0], report, label="saved", codec="aac", container="mp4", duration=15.691, duration_tolerance=0.08,
                                  tags={"album": "Edited Album", "title": "Synthetic Book", "artist": "Fixture Author", "genre": "Audiobook", "comment": "synthetic"})
    wanted = [dict(chapter) for chapter in expected_chapters]
    wanted[1]["title"] = "Renamed Chapter Two"
    oracle.inspect_chapters(probed, report, label="saved", expected=wanted)
    report.equal("saved: the audio packets are the source's, untouched", _stream_md5(context, outputs[0]), source_md5)
    report.equal("saved: the artwork is the source's", oracle.extract_artwork(context.tools, outputs[0], context.work / "saved-art.jpg"), source_art)
    context.require_unchanged(before)

    # -- Clear All Tags (keep chapters), through its own confirmation -------------------------------------- #
    session.click(TOOL, "btn_clear_tags")
    answer = session.answer_dialog("Yes", title="Clear all tags")
    context.notes["clear_confirmation"] = answer
    wait_until(lambda: context.run_dir(TOOL, 2).exists(), 30, "the second run to begin")
    report.equal("Clear: the run ended", wait_for_job(session, TOOL), "SUCCEEDED")
    session.screenshot("cleared")
    outputs = sorted(context.run_dir(TOOL, 2).rglob("*.m4b"))
    report.equal("Clear: one copy", len(outputs), 1)
    # The dialog's own promise: source values go, and only what was typed here is applied on top.
    report.check("the dialog promised what is checked next", "re-applied" in " ".join(answer["body"]), answer["body"])
    probed = oracle.inspect_audio(context.tools, outputs[0], report, label="cleared", codec="aac", container="mp4", tags={"album": "Edited Album"},
                                  absent_tags=("artist", "genre", "comment", "album_artist", "title", "date"))
    oracle.inspect_chapters(probed, report, label="cleared", expected=wanted)
    report.check("cleared: the source's artwork is gone too", oracle.artwork_stream(probed) is None)
    report.equal("cleared: the audio packets are the source's, untouched", _stream_md5(context, outputs[0]), source_md5)
    context.require_unchanged(before)
    expect_clean_close(context, session)


@scenario("metadata.confirmation-declined", tool="m4b-metadata-editor", layers=("native", "media"), tier="adverse",
          summary="Remove Series Numbering answered No in its real dialog: no run starts and nothing is written")
def declined(context: Context) -> None:
    report = context.report
    book = context.fixtures.get("book-plain-m4b")
    session = context.app(last_tool=TOOL)
    open_tool(session, TOOL)
    _import(session, book.path)
    session.click(TOOL, "btn_remove_numbering")
    session.answer_dialog("No", title="Remove series numbering")
    session.settle()
    session.screenshot("declined")
    report.equal("no run started", session.read(TOOL, "jobs.state"), "IDLE")
    root = context.output_base / "M4B-Metadata-Outputs"
    report.equal("nothing was written", list(root.rglob("*.m4b")) if root.exists() else [], [])
    expect_clean_close(context, session)


@scenario("metadata.unreadable-file", tool="m4b-metadata-editor", layers=("native", "media"), tier="adverse",
          summary="A truncated M4B: the import says it cannot be read, Save Tags refuses with a message, and nothing is written over anything")
def unreadable(context: Context) -> None:
    report = context.report
    broken = context.fixtures.path("book-truncated")
    before = context.source_hashes([broken])
    session = context.app(last_tool=TOOL)
    open_tool(session, TOOL)
    session.click(TOOL, "btn_add_files")
    session.file_dialog(broken, title="Select M4B file(s)")
    wait_until(lambda: "Broken Book" in session.widget(TOOL, "source_label").get("text", ""), 30, "the file to be shown as the current Book")
    session.settle()
    session.screenshot("imported")
    shown = session.widget(TOOL, "source_label").get("text", "")
    report.check("the import says it could not be read", "could not be read" in shown, shown)
    session.click(TOOL, "btn_save")
    answer = session.answer_dialog("OK", timeout=20)
    report.check("Save Tags explains why it cannot run", "could be read" in " ".join(answer["body"]), answer["body"])
    root = context.output_base / "M4B-Metadata-Outputs"
    report.equal("nothing was written", list(root.rglob("*.m4b")) if root.exists() else [], [])
    context.require_unchanged(before)
    text = log_text(session, TOOL)
    context.notes["summary"] = text[-300:]
    expect_clean_close(context, session)
