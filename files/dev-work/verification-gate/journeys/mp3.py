"""MP3 Tool: real MP3s in, Write ID3 Tags and Combine through the real buttons, and tags and audio read back independently."""

from __future__ import annotations

from pathlib import Path

from journeys.common import Context, expect_clean_close, log_text, open_tool, oracle, scenario, wait_for_job, wait_for_listbox, wait_until

TOOL = "mp3_tool"
TRACKS = ["track-1", "track-2", "track-3"]
ALBUM, ARTIST = "Acceptance Album", "Acceptance Artist"
TONES = [440.0, 660.0, 880.0]


def _add_tracks(session, context: Context, ids: list[str]) -> list[Path]:
    paths = [context.fixtures.path(identifier) for identifier in ids]
    session.click(TOOL, "btn_add_files")
    session.file_dialog(paths if len(paths) > 1 else paths[0], title="Select MP3 files")
    wait_for_listbox(session, TOOL, "track_list", len(paths))
    session.settle()
    return paths


def _files_of(folder: Path, suffix: str = ".mp3") -> list[Path]:
    """What was published. A Book's staging stays under ``.work`` for Retry Failed, and is not an output."""
    return sorted(item for item in folder.rglob(f"*{suffix}") if ".work" not in item.parts)


@scenario("mp3.write-id3-then-combine", tool="mp3-tool", layers=("native", "media"), tier="journey",
          summary="Three real MP3s added through the real dialog, Album and Artist typed, Write ID3 Tags and then Combine; tags and audio read back")
def write_then_combine(context: Context) -> None:
    report = context.report
    session = context.app(last_tool=TOOL)
    open_tool(session, TOOL)
    paths = _add_tracks(session, context, TRACKS)
    before = context.source_hashes(paths)
    session.type_into(TOOL, "surface._rows[album].shared_entry", ALBUM)
    session.type_into(TOOL, "surface._rows[artist].shared_entry", ARTIST)
    session.screenshot("ready")

    # -- Write ID3 Tags ---------------------------------------------------------------------- #
    session.click(TOOL, "btn_write_id3")
    report.equal("Write ID3: the run ended", wait_for_job(session, TOOL), "SUCCEEDED")
    session.screenshot("wrote-id3")
    written = _files_of(context.run_dir(TOOL, 1))
    report.equal("Write ID3: one output per track", len(written), 3)
    for index, (output, source) in enumerate(zip(written, paths)):
        label = f"track {index + 1}"
        oracle.inspect_audio(context.tools, output, report, label=label, codec="mp3", container="mp3", channels=2, duration=[3.0, 2.5, 2.0][index],
                             tags={"album": ALBUM, "artist": ARTIST, "track": str(index + 1), "title": ["Opening", "Middle", "Ending"][index]})
        oracle.inspect_interval(report, label=label, reference=oracle.decode_pcm(context.tools, source),
                                candidate=oracle.decode_pcm(context.tools, output))
    context.require_unchanged(before)

    # -- Combine on the same session: its run gets the next folder ------------------------------ #
    session.click(TOOL, "btn_combine")
    wait_until(lambda: session.read(TOOL, "jobs.state") not in ("SUCCEEDED",) or context.run_dir(TOOL, 2).exists(), 30,
               "the second run to begin")
    report.equal("Combine: the run ended", wait_for_job(session, TOOL), "SUCCEEDED")
    session.screenshot("combined")
    run = context.run_dir(TOOL, 2)
    report.check("Combine: its own numbered run folder", run.is_dir(), str(run.name))
    combined = _files_of(run)
    report.equal("Combine: one combined MP3", [item.name for item in combined], [f"{ALBUM}.mp3"])
    probed = oracle.inspect_audio(context.tools, combined[0], report, label="combined", codec="mp3", container="mp3", channels=2, duration=7.5,
                                  tags={"album": ALBUM, "artist": ARTIST})
    pcm = oracle.decode_pcm(context.tools, combined[0])
    tones = [t for t in oracle.tone_sequence(pcm, oracle.ORACLE_RATE, TONES, window=0.2) if t is not None]
    report.equal("combined: tracks in their order", tones, TONES)
    position = 0.0
    for index, (source, seconds) in enumerate(zip(paths, (3.0, 2.5, 2.0))):
        reference = oracle.decode_pcm(context.tools, source)
        start = int(position * oracle.ORACLE_RATE)
        # A FAST concat keeps each MP3's own encoder padding, so a later track sits a few frames late: bounded, and measured on the build.
        metrics = oracle.compare_interval(reference, pcm[start:start + reference.size + 4096], limit=4096)
        problems = oracle.interval_problems(metrics, max_lag=4096, max_length_difference=0.25)
        report.check(f"combined: track {index + 1} is present whole, first and last frames included", not problems, "; ".join(problems) or "ok", **metrics)
        position += seconds
    stamps = run / ALBUM / "combined_time-stamps.txt"
    report.check("combined: its timestamp list", stamps.is_file() and stamps.stat().st_size > 0, str(stamps.name))
    report.record_output(stamps) if stamps.is_file() else None
    context.notes["combined_format"] = probed["format"].get("format_name")
    context.require_unchanged(before)
    expect_clean_close(context, session)


TYPED_ALBUM = "Typed Before Import"


def _summary(session) -> dict:
    return session.widget(TOOL, "log.summary_text")


@scenario("mp3.typed-values-survive-first-import", tool="mp3-tool", layers=("native", "media"), tier="journey",
          summary="Album typed and Artist cleared with real keys before the first Add Files; the tracks' own tags overwrite neither, the "
                  "published tags say so, and the Summary log follows, holds under the real wheel and resumes across three runs")
def typed_values_survive_first_import(context: Context) -> None:
    """ACT72-006 and ACT72-005 (v0.7.2 Phase 5) through a person's hands: the fixtures carry "Source Album" and "Source Artist"."""
    report = context.report
    session = context.app(last_tool=TOOL)
    open_tool(session, TOOL)
    session.type_into(TOOL, "surface._rows[album].book_entry", TYPED_ALBUM)
    session.type_into(TOOL, "surface._rows[artist].book_entry", "deleted again")
    session.type_into(TOOL, "surface._rows[artist].book_entry", "")
    paths = _add_tracks(session, context, ["track-1", "track-2"])
    before = context.source_hashes(paths)
    report.equal("the typed Album survives the first files", session.widget(TOOL, "surface._rows[album].book_entry").get("value"), TYPED_ALBUM)
    report.equal("the cleared Artist stays cleared", session.widget(TOOL, "surface._rows[artist].book_entry").get("value"), "")
    session.screenshot("typed-then-added")

    def write(number: int) -> None:
        session.click(TOOL, "btn_write_id3")
        wait_until(lambda: context.run_dir(TOOL, number).exists(), 30, f"run {number} to begin")
        report.equal(f"Write ID3 run {number}: ended", wait_for_job(session, TOOL), "SUCCEEDED")
        session.settle()

    write(1)
    written = _files_of(context.run_dir(TOOL, 1))
    report.equal("one output per track", len(written), 2)
    for index, output in enumerate(written):
        oracle.inspect_audio(context.tools, output, report, label=f"track {index + 1}", codec="mp3", container="mp3",
                             tags={"album": TYPED_ALBUM}, absent_tags=("artist",))
    context.require_unchanged(before)

    # -- the Summary pane, read as a person reads it --------------------------------------------- #
    first = _summary(session)
    report.check("after run 1 the Summary shows its newest line", first.get("newest_line_shown"), first.get("top_text"))
    session.wheel(TOOL, "log.summary_text", 1)
    session.settle()
    held = _summary(session)
    # Held below line 1: the view the old renderer reset to on every update would look the same as holding there.
    report.check("one notch moved the reader off the newest line, not to the top",
                 not held.get("newest_line_shown") and 1 < held["top_line"] < first["top_line"],
                 {"before": first.get("top_line"), "after": held.get("top_line")})
    write(2)
    during = _summary(session)
    report.equal("run 2's lines did not move a reader who had scrolled up", (during.get("top_line"), during.get("top_text")),
                 (held.get("top_line"), held.get("top_text")))
    report.check("run 2's lines arrived below the reader", len(during.get("content", "")) > len(held.get("content", "")), "")
    for _ in range(12):
        if _summary(session).get("newest_line_shown"):
            break
        session.wheel(TOOL, "log.summary_text", -1)
        session.settle()
    report.check("the wheel brought the reader back to the newest line", _summary(session).get("newest_line_shown"), "")
    write(3)
    after = _summary(session)
    report.check("back at the bottom, run 3's lines are followed", after.get("newest_line_shown"), after.get("top_text"))
    session.screenshot("log-followed")
    expect_clean_close(context, session)


@scenario("mp3.unreadable-track", tool="mp3-tool", layers=("native", "media"), tier="adverse",
          summary="Bytes that are not audio named .mp3, beside a real track: the failure is named, nothing false is published, sources are unchanged")
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
    session.type_into(TOOL, "surface._rows[album].shared_entry", ALBUM)
    session.click(TOOL, "btn_combine")
    state = wait_for_job(session, TOOL)
    session.screenshot("finished")
    report.check("Combine does not report success", state in ("COMPLETED_WITH_FAILURES", "FAILED"), state)
    run = context.run_dir(TOOL, 1)
    report.equal("nothing was published", _files_of(run) if run.exists() else [], [])
    text = log_text(session, TOOL, "details_text") + log_text(session, TOOL)
    report.check("the failure says what it was", "not-audio" in text or "invalid" in text.lower() or "could not" in text.lower(), text[-400:])
    context.require_unchanged(before)
    expect_clean_close(context, session)
    staging = sorted(item.relative_to(run).as_posix() for item in (run / ".work").rglob("*") if item.is_file()) if (run / ".work").exists() else []
    context.notes["staging_left_after_exit"] = staging
    # v0.7.2 Phase 6 (ACT72-019): closing the tool drops the run, and no Retry Failed can reach its staging any more.
    report.equal("no private staging is left once the tool has closed", staging, [])
    report.check("no .work folder is left in the run folder", not (run / ".work").exists(), str(run))
