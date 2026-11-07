"""M4B Maker: real MP3s, a typed Title, artwork through the real dialog, Build M4B(s); the M4B's container, chapters and audio read back."""

from __future__ import annotations

from journeys.common import Context, expect_clean_close, log_text, open_tool, oracle, scenario, wait_for_job, wait_for_listbox

TOOL = "m4b_maker"
TONES = [440.0, 660.0, 880.0]
TITLES = ["Opening", "Middle", "Ending"]
SECONDS = [3.0, 2.5, 2.0]


def _add_tracks(session, context: Context, ids: list[str]):
    paths = [context.fixtures.path(identifier) for identifier in ids]
    session.click(TOOL, "btn_add_files")
    session.file_dialog(paths if len(paths) > 1 else paths[0], title="Select MP3 files")
    wait_for_listbox(session, TOOL, "track_list", len(paths))
    session.settle()
    return paths


@scenario("maker.build-with-chapters-and-artwork", tool="m4b-maker", layers=("native", "media"), tier="journey",
          summary="Three MP3s become one M4B: chapter per track with titles and starts, typed tags, chosen artwork byte for byte, audio in order")
def build(context: Context) -> None:
    report = context.report
    session = context.app(last_tool=TOOL)
    open_tool(session, TOOL)
    paths = _add_tracks(session, context, ["track-1", "track-2", "track-3"])
    before = context.source_hashes(paths)
    session.type_into(TOOL, "surface._rows[album].shared_entry", "Built Album")
    session.type_into(TOOL, "surface._rows[artist].shared_entry", "Built Artist")
    session.type_into(TOOL, "book_entries[title]", "Built Title")
    art = context.fixtures.path("cover-square-jpeg")
    session.click(TOOL, "book_artwork.btn_choose")
    session.file_dialog(art, title="Select Book Artwork")
    session.settle()
    session.screenshot("ready")
    session.click(TOOL, "btn_build")
    report.equal("the run ended", wait_for_job(session, TOOL), "SUCCEEDED")
    session.screenshot("finished")
    outputs = sorted(context.run_dir(TOOL).rglob("*.m4b"))
    report.equal("one M4B", [item.name for item in outputs], ["Built Title.m4b"])
    output = outputs[0]
    probed = oracle.inspect_audio(context.tools, output, report, label="m4b", codec="aac", container="mp4", duration=sum(SECONDS), duration_tolerance=0.2,
                                  tags={"title": "Built Title", "album": "Built Album", "artist": "Built Artist"})
    position, expected = 0.0, []
    for title, seconds in zip(TITLES, SECONDS):
        expected.append({"title": title, "start": position, "end": position + seconds})
        position += seconds
    oracle.inspect_chapters(probed, report, label="m4b", expected=expected, tolerance=0.08)
    stored = oracle.extract_artwork(context.tools, output, context.work / "extracted-art.jpg")
    report.check("artwork is the chosen file's image", oracle.artwork_stream(probed) is not None and len(stored) > 0, f"{len(stored)} bytes")
    report.equal("artwork bytes", oracle.hashlib.sha256(stored).hexdigest(), oracle.hashlib.sha256(art.read_bytes()).hexdigest())
    pcm = oracle.decode_pcm(context.tools, output)
    tones = [tone for tone in oracle.tone_sequence(pcm, oracle.ORACLE_RATE, TONES, window=0.2) if tone is not None]
    report.equal("the tracks are in order", tones, TONES)
    # Round trip: each chapter, taken from the output by its own chapter table, is the source track.
    chapters = oracle.chapters_of(probed)
    for index, (chapter, source) in enumerate(zip(chapters, paths)):
        start = int(chapter["start"] * oracle.ORACLE_RATE)
        reference = oracle.decode_pcm(context.tools, source)
        metrics = oracle.compare_interval(reference, pcm[start:start + reference.size + 2048], limit=2048)
        problems = oracle.interval_problems(metrics, max_lag=2048, max_length_difference=0.2)
        report.check(f"chapter {index + 1} holds its whole track", not problems, "; ".join(problems) or "ok", **metrics)
    context.require_unchanged(before)
    expect_clean_close(context, session)


@scenario("maker.unreadable-track", tool="m4b-maker", layers=("native", "media"), tier="adverse",
          summary="Bytes named .mp3 among real tracks: the Book fails, no M4B appears under a final name, and sources are unchanged")
def unreadable(context: Context) -> None:
    report = context.report
    session = context.app(last_tool=TOOL)
    open_tool(session, TOOL)
    good = context.fixtures.path("track-1")
    bad = context.fixtures.path("track-garbage")
    before = context.source_hashes([good, bad])
    _add_tracks(session, context, ["track-1"])
    session.click(TOOL, "btn_add_files")
    session.file_dialog(bad, title="Select MP3 files")
    wait_for_listbox(session, TOOL, "track_list", 2)
    session.type_into(TOOL, "book_entries[title]", "Should Not Exist")
    session.click(TOOL, "btn_build")
    state = wait_for_job(session, TOOL)
    session.screenshot("finished")
    report.check("the build does not report success", state in ("COMPLETED_WITH_FAILURES", "FAILED"), state)
    root = context.output_base / "M4B-Maker-Outputs"
    report.equal("no M4B was published", list(root.rglob("*.m4b")) if root.exists() else [], [])
    text = log_text(session, TOOL, "details_text") + log_text(session, TOOL)
    report.check("the failure is explained", len(text.strip()) > 0 and ("not-audio" in text or "failed" in text.lower() or "could not" in text.lower()), text[-400:])
    report.check("Retry Failed is offered", not session.widget(TOOL, "jobs.controls.buttons[RETRY_FAILED]").get("disabled"))
    context.require_unchanged(before)
    expect_clean_close(context, session)
