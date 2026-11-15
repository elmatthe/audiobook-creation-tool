#!/usr/bin/env python3
"""macos-visual (P1B closeout): pictures of the real application, reviewed by machine, indexed for a person.

    verify.py --mode qualification --platform macos --scenario macos-visual

For each appearance (the application's own Light/Dark setting, which also sets each window's native Aqua appearance):

  * shell     every panel empty at the 1120 x 800 Aqua minimum, then at the largest size the visible desktop holds, and
              Preferences & Data;
  * populated every panel with long file names (accents, an em dash, NFC and NFD spellings) and long typed titles, and the
              M4B Maker's Chapter Titles box with 23 tracks, scrolled;
  * work      real runs, pictured while busy and when finished (MP3 Combine, M4B Maker, M4B Converter on long inputs; Cover
              and Metadata finished): progress, publication and status lines;
  * alerts    the real NSAlert warnings two tools raise when asked to run with nothing imported, answered with Return.

Every picture is the window server's image of the application's own window (no Screen Recording grant is needed for that),
written with its provenance (tool, appearance, size, state, source SHA) and judged by ``helpers/visual_review.py``. A
required picture that is missing, was not captured, or does not pass review fails the scenario. ``index.html`` and
``contact-sheet.png`` index them all. Everything stays in this run's ignored folder.
"""

from __future__ import annotations

import json
import shutil
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qualification import common, macos_common  # noqa: E402

NAME = "macos-visual"
APPEARANCES = ("dark", "light")
TOOLS = ("tts", "m4b_converter", "mp3_tool", "m4b_maker", "cover", "m4b_metadata")
MINIMUM = (1120, 800)
LONG = "The Extraordinarily Long Chapter Title That Keeps Going — Café Ünïcode Édition"
LONG_TITLE = "A Very Long Book Title That Should Wrap Or Truncate Gracefully — Volume One of the Collected Works"
#: What each appearance must show; anything missing fails (the native warning alerts are listed when the control is enabled).
REQUIRED = ([f"shell/{tool}-empty-1120x800" for tool in TOOLS] + [f"shell/{tool}-empty-max" for tool in TOOLS] + ["shell/preferences"]
            + [f"populated/{tool}-populated" for tool in TOOLS] + ["populated/maker-long-list-scrolled"]
            + [f"work/{name}" for name in ("mp3-busy", "mp3-finished", "maker-busy", "maker-finished", "converter-busy",
                                           "converter-finished", "cover-finished", "metadata-finished")])
ALERTS: list[str] = []


def _size(session, size) -> None:
    from journeys.common import native, wait_until

    native.resize_client(session.hwnd, *size)
    wait_until(lambda: tuple(native.client_size(session.hwnd)) == tuple(size), 10, f"the window to reach {size}")
    session.settle()


def _largest(session) -> tuple[int, int]:
    from journeys.common import native

    left, top, right, bottom = native.visible_frame()
    title_bar = int(session.client.call("window").get("frame_top", 28))
    return right - left, bottom - top - title_bar


def _copies(context, fixture: str, folder: str, names: list[str]) -> list[Path]:
    target = context.work / "in" / folder
    target.mkdir(parents=True, exist_ok=True)
    source = context.fixtures.path(fixture)
    made = []
    for name in names:
        path = target / name
        shutil.copyfile(source, path)
        made.append(path)
    return made


def shell_case(appearance: str):
    def run(context):
        from journeys.common import expect_clean_close, native, open_tool, wait_until

        session = context.app(last_tool="tts", settings={"appearance": appearance})
        for tool in TOOLS:
            open_tool(session, tool)
            _size(session, MINIMUM)
            session.screenshot(f"{tool}-empty-1120x800", tool=tool)
        largest = _largest(session)
        context.notes["largest"] = largest
        _size(session, largest)
        for tool in TOOLS:
            open_tool(session, tool)
            session.screenshot(f"{tool}-empty-max", tool=tool)
        _size(session, MINIMUM)
        before = {item["path"] for item in session.client.call("toplevels")["toplevels"]}
        session.click(None, "preferences_button")
        wait_until(lambda: {item["path"] for item in session.client.call("toplevels")["toplevels"]} - before, 15, "Preferences & Data")
        session.settle()
        dialog = wait_until(lambda: next((item["hwnd"] for item in native.windows_of(session.pid)
                                          if item["class"] == "TkTopLevel" and item["owner"] and item["hwnd"] != session.hwnd), None),
                            10, "the Preferences window")
        session.screenshot("preferences", window=dialog, tool="preferences")
        session.key("escape")
        wait_until(lambda: not ({item["path"] for item in session.client.call("toplevels")["toplevels"]} - before), 15, "Preferences to close")
        expect_clean_close(context, session)

    return run


def populated_case(appearance: str):
    def run(context):
        from journeys.common import expect_clean_close, open_tool, wait_for_listbox, wait_until

        report = context.report
        session = context.app(last_tool="tts", settings={"appearance": appearance})
        nfd = unicodedata.normalize("NFD", f"03 {LONG} (NFD).mp3")
        tracks = _copies(context, "track-1", "long-names", [f"01 {LONG}.mp3", f"02 {LONG} — Part Two.mp3", nfd])
        open_tool(session, "mp3_tool")
        session.click("mp3_tool", "btn_add_files")
        session.file_dialog(tracks, title="Select MP3 files")
        wait_for_listbox(session, "mp3_tool", "track_list", 3)
        session.type_into("mp3_tool", "surface._rows[album].shared_entry", LONG_TITLE)
        session.screenshot("mp3_tool-populated", tool="mp3_tool")
        open_tool(session, "m4b_maker")
        session.click("m4b_maker", "btn_add_files")
        session.file_dialog(tracks, title="Select MP3 files")
        wait_for_listbox(session, "m4b_maker", "track_list", 3)
        session.type_into("m4b_maker", "book_entries[title]", LONG_TITLE)
        session.screenshot("m4b_maker-populated", tool="m4b_maker")
        many = _copies(context, "track-1", "long-list", [f"{index:02d} {LONG}.mp3" for index in range(4, 24)])
        session.click("m4b_maker", "btn_add_files")
        session.file_dialog(many, title="Select MP3 files")
        wait_for_listbox(session, "m4b_maker", "track_list", 23)
        session.settle()
        session.wheel("m4b_maker", "chapter_text", -3)
        session.settle()
        report.check("the long Chapter Titles box scrolled", session.widget("m4b_maker", "chapter_text").get("top_line", 1) > 1)
        session.screenshot("maker-long-list-scrolled", tool="m4b_maker")
        open_tool(session, "m4b_converter")
        books = _copies(context, "book-m4b", "long-books", [f"{LONG}.m4b"])
        session.click("m4b_converter", "importer.list.buttons[add_files]")
        session.file_dialog(books, title="Select .m4b files")
        wait_until(lambda: len(session.widget("m4b_converter", "importer.list.listbox").get("items", [])) >= 1, 30, "the book to be listed")
        session.settle()
        session.screenshot("m4b_converter-populated", tool="m4b_converter")
        open_tool(session, "m4b_metadata")
        plain = _copies(context, "book-plain-m4b", "long-plain", [f"{LONG} (plain).m4b"])
        session.click("m4b_metadata", "btn_add_files")
        session.file_dialog(plain, title="Select M4B file(s)")
        wait_until(lambda: session.widget("m4b_metadata", "surface._rows[title].book_entry").get("value"), 30, "the book's values")
        session.settle()
        session.screenshot("m4b_metadata-populated", tool="m4b_metadata")
        open_tool(session, "cover")
        covers = _copies(context, "cover-landscape-jpeg", "long-covers", [f"{LONG}.jpg"]) + \
            _copies(context, "cover-portrait-png", "long-covers", [f"{LONG} portrait.png"])
        session.click("cover", "importer.list.buttons[add_files]")
        session.file_dialog(covers, title="Select cover images")
        wait_until(lambda: len(session.widget("cover", "browser.details").get("items", [])) == 2, 30, "the images to be listed")
        session.settle()
        session.screenshot("cover-populated", tool="cover")
        open_tool(session, "tts")
        stories = _copies(context, "story-text", "long-stories", [f"{LONG}.txt"])
        session.click("tts", "importer.list.buttons[add_files]")
        session.file_dialog(stories, title="Source files")
        session.settle()
        session.screenshot("tts-populated", tool="tts")
        expect_clean_close(context, session)

    return run


def work_case(appearance: str):
    def run(context):
        from journeys.common import expect_clean_close, open_tool, wait_for_job, wait_for_listbox, wait_until
        from journeys.shutdown import wait_for_long_encode

        report = context.report
        session = context.app(last_tool="mp3_tool", settings={"appearance": appearance})
        long_tracks = [context.fixtures.path(item) for item in ("track-long-1", "track-long-2", "track-long-3")]
        open_tool(session, "mp3_tool")
        session.click("mp3_tool", "btn_add_files")
        session.file_dialog(long_tracks, title="Select MP3 files")
        wait_for_listbox(session, "mp3_tool", "track_list", 3)
        session.click("mp3_tool", "btn_combine")
        wait_for_long_encode(session, "mp3_tool")
        session.screenshot("mp3-busy", tool="mp3_tool")
        report.equal("MP3 Combine finished", wait_for_job(session, "mp3_tool", timeout=600), "SUCCEEDED")
        session.settle()
        session.screenshot("mp3-finished", tool="mp3_tool")
        open_tool(session, "m4b_maker")
        session.click("m4b_maker", "btn_add_files")
        session.file_dialog(long_tracks, title="Select MP3 files")
        wait_for_listbox(session, "m4b_maker", "track_list", 3)
        session.click("m4b_maker", "btn_build")
        wait_for_long_encode(session, "m4b_maker")
        session.screenshot("maker-busy", tool="m4b_maker")
        report.equal("M4B Maker finished", wait_for_job(session, "m4b_maker", timeout=600), "SUCCEEDED")
        session.settle()
        session.screenshot("maker-finished", tool="m4b_maker")
        open_tool(session, "m4b_converter")
        session.click("m4b_converter", "importer.list.buttons[add_files]")
        session.file_dialog(context.fixtures.path("book-long-m4b"), title="Select .m4b files")
        wait_until(lambda: len(session.widget("m4b_converter", "importer.list.listbox").get("items", [])) >= 1, 30, "the book")
        session.click("m4b_converter", "btn_convert")
        wait_for_long_encode(session, "m4b_converter")
        session.screenshot("converter-busy", tool="m4b_converter")
        report.equal("M4B Converter finished", wait_for_job(session, "m4b_converter", timeout=900), "SUCCEEDED")
        session.settle()
        session.screenshot("converter-finished", tool="m4b_converter")
        open_tool(session, "cover")
        session.click("cover", "importer.list.buttons[add_files]")
        session.file_dialog([context.fixtures.path("cover-landscape-jpeg"), context.fixtures.path("cover-portrait-png")], title="Select cover images")
        wait_until(lambda: len(session.widget("cover", "browser.details").get("items", [])) == 2, 30, "the images")
        session.click("cover", "btn_convert")
        report.equal("Cover finished", wait_for_job(session, "cover"), "SUCCEEDED")
        session.settle()
        session.screenshot("cover-finished", tool="cover")
        open_tool(session, "m4b_metadata")
        session.click("m4b_metadata", "btn_add_files")
        session.file_dialog(context.fixtures.path("book-plain-m4b"), title="Select M4B file(s)")
        wait_until(lambda: session.widget("m4b_metadata", "surface._rows[title].book_entry").get("value"), 30, "the book's values")
        session.type_into("m4b_metadata", "surface._rows[album].shared_entry", "Pictured Album")
        session.click("m4b_metadata", "btn_save")
        report.equal("Metadata Save finished", wait_for_job(session, "m4b_metadata"), "SUCCEEDED")
        session.settle()
        session.screenshot("metadata-finished", tool="m4b_metadata")
        expect_clean_close(context, session)

    return run


def alerts_case(appearance: str):
    def run(context):
        from journeys.common import expect_clean_close, open_tool, wait_until

        report = context.report
        session = context.app(last_tool="mp3_tool", settings={"appearance": appearance}, native_dialogs=["message"])
        for tool, key, label in (("mp3_tool", "btn_write_id3", "mp3-nothing-imported"), ("m4b_converter", "btn_convert", "converter-nothing-imported")):
            open_tool(session, tool)
            if session.widget(tool, key).get("disabled"):
                context.notes.setdefault("alerts_skipped", []).append(f"{tool}:{key} is disabled with nothing imported: no alert to picture")
                continue
            before = len(session.native_events())
            session.expect_native({"kind": "alert", "respond": "return", "capture": f"alert-{label}"})
            session.click(tool, key)
            events = wait_until(lambda: (lambda found: found if len(found) > before else None)(session.native_events()), 30, label)
            event = events[before]
            _alert_record(session, event, appearance, tool, label)
            report.check(f"{label}: a real warning alert", event.get("kind") == "alert" and not event.get("unexpected"), event.get("window"))
            session.settle()
            report.equal(f"{label}: nothing started", session.read(tool, "jobs.state"), "IDLE")
            ALERTS.append(f"{appearance}/alerts/alert-{label}")
        expect_clean_close(context, session)

    return run


def _alert_record(session, event: dict, appearance: str, tool: str, label: str) -> None:
    """A native alert's picture gets the same provenance record and review as any other picture."""
    from adapters.macos.app_session import source_identity
    from helpers import visual_review

    picture = event.get("picture") or {}
    png = session.screenshots / picture.get("name", f"alert-{label}.png")
    window = event.get("window") or {}
    record = {"name": png.name, "session": session.name, "scenario": session.evidence.name, "state": f"alert-{label}", "subject": "alert",
              "tool": tool, "captured": bool(picture.get("captured")), "why": picture.get("why"), "width_px": picture.get("width_px"),
              "height_px": picture.get("height_px"), "window": {key: window.get(key) for key in ("frame", "scale", "title", "class")},
              "appearance": {"app": appearance, "native": window.get("appearance")}, "viewport": window.get("frame", [0, 0, 0, 0])[2:],
              "message": (event.get("facts") or {}).get("title"), **source_identity()}
    if record["captured"] and png.is_file():
        record["sha256"] = visual_review.sha256(png)
    record["review"] = visual_review.review(png, record)
    png.with_suffix(".json").write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")


def main(argv=None) -> int:
    q = common.start(NAME, argv)
    if isinstance(q, int):
        return q

    def body(q):
        from helpers import visual_review

        identity = q.identity(appearances=list(APPEARANCES), minimum=list(MINIMUM))
        cases = []
        for appearance in APPEARANCES:
            cases += [macos_common.Case(appearance, "shell", shell_case(appearance), tool="launcher"),
                      macos_common.Case(appearance, "populated", populated_case(appearance), tool="launcher"),
                      macos_common.Case(appearance, "work", work_case(appearance), tool="launcher", budget=1800),
                      macos_common.Case(appearance, "alerts", alerts_case(appearance), tool="launcher")]
        macos_common.run_cases(q, cases)
        pictures, entries = {}, []
        for sidecar in sorted((q.root / "cases").glob("*/screenshots/*.json")):
            case = sidecar.parent.parent.name  # e.g. dark.shell
            appearance, part = case.split(".", 1)
            key = f"{appearance}/{part}/{sidecar.stem}"
            record = json.loads(sidecar.read_text(encoding="utf-8"))
            png = sidecar.with_suffix(".png")
            verdict = visual_review.review(png, record)
            pictures[key] = verdict["status"]
            entries.append({"path": png.relative_to(q.root).as_posix(), "record": record, "review": verdict})
            q.check(f"picture / {key}", verdict["status"] == "PASS" and record.get("sha") == identity["head"],
                    f"{verdict['status']}: {verdict['reason']}; sha {str(record.get('sha'))[:12]}")
            for line in verdict.get("advisories", []):
                q.log(f"advisory {key}: {line}")
        wanted = [f"{appearance}/{name}" for appearance in APPEARANCES for name in REQUIRED] + ALERTS
        missing = [key for key in wanted if key not in pictures]
        failing = [key for key in wanted if pictures.get(key) not in (None, "PASS")]
        q.check("every required picture was captured and reviewed", not missing and not failing,
                {"required": len(wanted), "missing": missing, "not passing": failing})
        sheet = visual_review.contact_sheet(entries, q.root, title=f"macos-visual at {identity['head'][:12]}")
        q.check("a contact sheet indexes every picture", sheet["pictures"] == len(entries) and (q.root / "index.html").is_file()
                and sheet["sheet"] is not None, sheet)
        (q.root / "pictures.json").write_text(json.dumps({"pictures": pictures, "required": wanted}, indent=1), encoding="utf-8")

    return q.finish(body)


if __name__ == "__main__":
    sys.exit(main())
