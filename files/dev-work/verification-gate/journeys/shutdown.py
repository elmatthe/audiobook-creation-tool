"""Closing a real window while work is running (owner's Phase 3 requirement; plan 7.2).

The Phase 2 hazard is a closed Tk root finalised on a worker thread: ``Tcl_AsyncDelete``, exit 0x80000003. Where a collection lands follows
allocation history, so a clean exit from one unforced close proves little. Each tool therefore gets two arms: the plain close a person
performs, and the same close with one collection forced onto a worker the moment ``main()`` has returned, which makes the hazard a yes or
no. The two module lists that happen to hold the closed root are emptied first, so the application's own holder, ``launcher._ROOT``,
is what the forced arm tests on every tool. ``control.forced-landing-sees-the-crash`` shows that the forced arm really can see this crash,
and ``control.act-crash-seen-with-the-root-released`` that the real application crashes once its own holder is gone too.

Everything is read from outside the process: its own exit status, its windows, the job's process list before kill-on-close could tidy up.
"""

from __future__ import annotations

import json
import shutil

from journeys import tts as tts_journeys
from journeys.common import Context, expect_clean_close, open_tool, oracle, scenario, wait_for_listbox, wait_until
from journeys.converter import native_image


def _ffmpeg_running(session) -> bool:
    return any(native_image(pid) == "ffmpeg.exe" for pid in session.job.pids())


def wait_for_long_encode(session, tool: str, *, timeout: float = 60) -> None:
    """Until one FFmpeg process has been working for a full second. A brief probe writes progress to its pipe and dies with the application by
    itself; a long encode writes nothing, and that is the child that outlives a closed window."""
    seen: dict[int, float] = {}

    def settled() -> bool:
        now = oracle.time_now()
        running = {pid for pid in session.job.pids() if native_image(pid) == "ffmpeg.exe"}
        for pid in list(seen):
            if pid not in running:
                del seen[pid]
        for pid in running:
            seen.setdefault(pid, now)
        return session.read(tool, "jobs.state") == "RUNNING" and any(now - first >= 1.0 for first in seen.values())

    wait_until(settled, timeout, "FFmpeg to be busy on a long encode")


def _finish(context: Context, session, *, tool: str, active: str, forced_record=None) -> dict:
    """Close, and hold the result to the requirement. No partial output may sit under a final name afterwards."""
    report = context.report
    report.equal(f"{tool}: the run is working at the moment of closing", session.read(tool, "jobs.state"), "RUNNING")
    report.check(f"{tool}: {active} is really active", _active(session, active), active)
    session.screenshot("about-to-close")
    facts = expect_clean_close(context, session)
    if forced_record is not None:
        report.check("the forced collection really ran on a worker", forced_record.is_file(), str(forced_record.name))
        if forced_record.is_file():
            # The application runs at Low integrity and writes only to its scratch; keep its record with the evidence.
            for item in (forced_record, forced_record.with_suffix(".stacks.txt")):
                if item.is_file():
                    shutil.copy2(item, context.evidence / item.name)
            forced = context.notes["forced_collection"] = json.loads(forced_record.read_text(encoding="utf-8"))
            report.check("the closed root was held by the application itself, with the accidental holders emptied",
                         forced.get("held_by_application") is True, forced.get("root_holder_chain"))
    return facts


def _active(session, active: str) -> bool:
    return _ffmpeg_running(session) if active == "the FFmpeg child" else True


def _published_mp3s(context: Context, slug: str) -> list:
    root = context.output_base / f"{slug}-Outputs"
    return [item for item in root.rglob("*.mp3") if ".work" not in item.parts] if root.exists() else []


def _converter(context: Context, forced: bool) -> None:
    record = context.work / "forced.json" if forced else None
    session = context.app(last_tool="m4b_converter", force_worker_collection=record)
    open_tool(session, "m4b_converter")
    session.click("m4b_converter", "importer.list.buttons[add_files]")
    session.file_dialog(context.fixtures.path("book-long-m4b"), title="Select .m4b files")
    wait_until(lambda: len(session.widget("m4b_converter", "importer.list.listbox").get("items", [])) == 1, 30, "the book to be listed")
    session.click("m4b_converter", "rb_split")
    session.click("m4b_converter", "btn_convert")
    wait_for_long_encode(session, "m4b_converter")
    _finish(context, session, tool="m4b_converter", active="the FFmpeg child", forced_record=record)


def _tts(context: Context, forced: bool) -> None:
    record = context.work / "forced.json" if forced else None
    replay = tts_journeys.replay_config(context, delay_seconds=0.6)
    session = context.app(last_tool="tts", replay=replay, force_worker_collection=record)
    open_tool(session, "tts")
    session.click("tts", "importer.list.buttons[add_files]")
    session.file_dialog(context.fixtures.path("story-long-text"), title="Source files")
    wait_until(lambda: len(session.widget("tts", "importer.list.listbox").get("items", [])) == 1, 30, "the source to be listed")
    session.click("tts", tts_journeys.START)
    wait_until(lambda: len(tts_journeys.requests_of(replay)) >= 2, 60, "requests to be in flight")
    _finish(context, session, tool="tts", active="narration requests", forced_record=record)
    context.report.equal("no MP3 was published for the interrupted book", _published_mp3s(context, "TTS-Audiobook"), [])
    count = len(tts_journeys.requests_of(replay))
    oracle.time_sleep(1.0)
    context.report.equal("no request after the process ended", len(tts_journeys.requests_of(replay)), count)


def _mp3(context: Context, forced: bool) -> None:
    record = context.work / "forced.json" if forced else None
    session = context.app(last_tool="mp3_tool", force_worker_collection=record)
    open_tool(session, "mp3_tool")
    paths = [context.fixtures.path(item) for item in ("track-long-1", "track-long-2", "track-long-3")]
    session.click("mp3_tool", "btn_add_files")
    session.file_dialog(paths, title="Select MP3 files")
    wait_for_listbox(session, "mp3_tool", "track_list", 3)
    session.type_into("mp3_tool", "surface._rows[time_delta].shared_entry", "1")  # the Safe route's re-encode, so the worker is really busy
    session.click("mp3_tool", "btn_combine")
    wait_for_long_encode(session, "mp3_tool")
    _finish(context, session, tool="mp3_tool", active="the FFmpeg child", forced_record=record)


def _maker(context: Context, forced: bool) -> None:
    record = context.work / "forced.json" if forced else None
    session = context.app(last_tool="m4b_maker", force_worker_collection=record)
    open_tool(session, "m4b_maker")
    paths = [context.fixtures.path(item) for item in ("track-long-1", "track-long-2", "track-long-3")]
    session.click("m4b_maker", "btn_add_files")
    session.file_dialog(paths, title="Select MP3 files")
    wait_for_listbox(session, "m4b_maker", "track_list", 3)
    session.click("m4b_maker", "btn_build")
    wait_for_long_encode(session, "m4b_maker")
    _finish(context, session, tool="m4b_maker", active="the FFmpeg child", forced_record=record)
    root = context.output_base / "M4B-Maker-Outputs"
    context.report.equal("no M4B was published under a final name", [item for item in root.rglob("*.m4b") if ".work" not in item.parts] if root.exists() else [], [])


def _copies_of(context: Context, fixture: str, count: int) -> list:
    source = context.fixtures.path(fixture)
    folder = context.work / "in" / f"{fixture}-copies"
    folder.mkdir(exist_ok=True)
    copies = []
    for index in range(count):
        copy = folder / f"Copy {index:02d}{source.suffix}"
        copy.write_bytes(source.read_bytes())
        copies.append(copy)
    return copies


def _metadata(context: Context, forced: bool) -> None:
    record = context.work / "forced.json" if forced else None
    session = context.app(last_tool="m4b_metadata", force_worker_collection=record)
    open_tool(session, "m4b_metadata")
    copies = _copies_of(context, "book-long-m4b", 6)
    session.click("m4b_metadata", "btn_add_files")
    session.file_dialog(copies, title="Select M4B file(s)")
    wait_until(lambda: "of 6" in str(session.widget("m4b_metadata", "navigator.label").get("text", "")), 60, "the six Books to be listed")
    session.settle()
    session.click("m4b_metadata", "btn_save")
    wait_until(lambda: session.read("m4b_metadata", "jobs.state") == "RUNNING", 30, "the run to be working")
    _finish(context, session, tool="m4b_metadata", active="the save", forced_record=record)


def _cover(context: Context, forced: bool) -> None:
    record = context.work / "forced.json" if forced else None
    session = context.app(last_tool="cover", force_worker_collection=record)
    open_tool(session, "cover")
    copies = _copies_of(context, "cover-landscape-jpeg", 40)
    session.click("cover", "importer.list.buttons[add_folder]")
    session.folder_dialog(copies[0].parent, title="Select a folder of cover images")
    wait_until(lambda: len(session.widget("cover", "browser.details").get("items", [])) == 40, 60, "the images to be listed")
    session.type_into("cover", "entry_size", "4096")
    session.click("cover", "btn_convert")
    wait_until(lambda: session.read("cover", "jobs.state") == "RUNNING", 30, "the run to be working")
    _finish(context, session, tool="cover", active="the resize", forced_record=record)


def _register(name: str, tool: str, function, summary: str) -> None:
    def plain(context: Context) -> None:
        function(context, False)

    def forced(context: Context) -> None:
        function(context, True)

    scenario(f"shutdown.{name}-close-during-work", tool=tool, layers=("native", "shutdown"), tier="shutdown",
             summary=f"{summary}: Alt+F4 while it works; exit status 0, no window, no owned process, no Tcl crash")(plain)
    scenario(f"shutdown.{name}-close-forced-landing", tool=tool, layers=("native", "shutdown"), tier="shutdown",
             summary=f"{summary}: the same close, accidental root holders emptied, a collection forced onto a worker once the window has gone")(forced)


_register("tts", "tts-audiobook", _tts, "TTS with narration requests in flight")
_register("converter", "m4b-converter", _converter, "Converter with FFmpeg encoding")
_register("mp3", "mp3-tool", _mp3, "MP3 Tool combining long tracks")
_register("maker", "m4b-maker", _maker, "Maker building from long tracks")
_register("metadata", "m4b-metadata-editor", _metadata, "Metadata Editor saving a batch of Books")
_register("cover", "cover-image", _cover, "Cover Image resizing a batch")
