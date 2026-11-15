#!/usr/bin/env python3
"""macos-native-dialogs (P1B closeout): the five tools' REAL NSOpenPanel and NSAlert, opened by their own controls.

    verify.py --mode qualification --platform macos --scenario macos-native-dialogs

No stand-ins: the application is started with ``native_dialogs`` and its own panels appear. ``adapters/macos/native_ui.py``,
inside the application, reads each panel's configuration from the panel itself, pictures it, and answers it:

  * an open panel is sent its own ``cancel:`` action (what its Cancel button does) -- the tool must then hold exactly what
    it held before;
  * an alert gets Return or Escape posted to the application's own event queue, so AppKit's own key handling picks the
    button -- Escape must do nothing, Return must do the alert's default.

What this does not prove, and never claims: a real keyboard or pointer (the events are synthetic, no Accessibility grant
exists), and anything inside the open panel's browser, which another process draws (choosing files there is the
``native-panel-selection`` requirement, BLOCKED on Accessibility; see verification.json darwin_p1b).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qualification import common, macos_common  # noqa: E402

NAME = "macos-native-dialogs"
TITLES = {"mp3": "Select MP3 files", "m4b": "Select .m4b files", "meta": "Select M4B file(s)", "cover": "Select cover images",
          "art": "Select Book Artwork"}
FOUND: dict[str, list] = {"opened": [], "cancel_ok": [], "escape_ok": [], "return_ok": []}


def _panel(session, report, label: str, tool: str, key: str, *, title: str | None, multiple: bool | None, files: bool, folders: bool,
           types: tuple = (), count=None):
    """Open one real panel through the tool's control, read it, cancel it, and show the tool unchanged."""
    from journeys.common import wait_until

    held = count() if count else None
    before = len(session.native_events())
    session.expect_native({"kind": "open", "respond": "cancel", "capture": f"panel-{label}"})
    session.click(tool, key)
    events = wait_until(lambda: (lambda found: found if len(found) > before else None)(session.native_events()), 30,
                        f"the real panel of {label}")
    event = events[before]
    facts = event.get("facts", {})
    opened = event.get("kind") == "open" and str(facts.get("panel_class", "")).endswith("OpenPanel") and not event.get("unexpected")
    FOUND["opened"].append(opened)
    report.check(f"{label}: a real NSOpenPanel opened", opened, facts)
    if title is not None:
        report.equal(f"{label}: the panel's message is the tool's title", facts.get("message") or facts.get("title"), title)
    if multiple is not None:
        report.equal(f"{label}: multiple selection", facts.get("multiple"), multiple)
    report.equal(f"{label}: it chooses files", facts.get("choose_files"), files)
    report.equal(f"{label}: it chooses folders", facts.get("choose_directories"), folders)
    if types:
        offered = set(facts.get("content_types") or [])
        report.check(f"{label}: it offers {list(types)}", set(types) <= offered, sorted(offered))
    elif files:
        report.check(f"{label}: it restricts the file types", bool(facts.get("content_types")), facts.get("content_types"))
    picture = event.get("picture") or {}
    report.check(f"{label}: the panel's own window was imaged, and marked as not showing the browser",
                 picture.get("captured") is True and picture.get("content_is_remote") is True, picture)
    answered = event.get("answered") or {}
    cancelled = "cancel:" in str(answered.get("by")) and not answered.get("fallback")
    session.settle()
    unchanged = held is None or count() == held
    FOUND["cancel_ok"].append(cancelled and unchanged)
    report.check(f"{label}: ended as Cancel, the tool added nothing", cancelled and unchanged, {"before": held, "after": count() if count else None})
    report.check(f"{label}: no run started", session.read(tool, "jobs.state") in ("IDLE", None), session.read(tool, "jobs.state"))


def _alert(session, report, label: str, tool: str, key: str, respond: str):
    """Press a control that raises a real alert; answer it with a key event; return the native record."""
    from journeys.common import wait_until

    before = len(session.native_events())
    session.expect_native({"kind": "alert", "respond": respond, "capture": f"alert-{label}"})
    session.click(tool, key)
    events = wait_until(lambda: (lambda found: found if len(found) > before else None)(session.native_events()), 30, f"the alert of {label}")
    event = events[before]
    report.check(f"{label}: a real NSAlert appeared", event.get("kind") == "alert" and not event.get("unexpected"), event.get("window"))
    picture = event.get("picture") or {}
    report.check(f"{label}: the alert was imaged", picture.get("captured") is True and picture.get("width_px", 0) > 100, picture)
    report.check(f"{label}: answered by a {respond} key event, not a stand-in", respond in str((event.get("answered") or {}).get("by")),
                 event.get("answered"))
    session.settle()
    return event


def mp3_case(context):
    from journeys.common import expect_clean_close, open_tool

    session = context.app(last_tool="mp3_tool", native_dialogs=["file", "message"])
    open_tool(session, "mp3_tool")
    count = lambda: len(session.widget("mp3_tool", "track_list").get("items", []))  # noqa: E731
    _panel(session, context.report, "mp3-add-files", "mp3_tool", "btn_add_files", title=TITLES["mp3"], multiple=True, files=True,
           folders=False, types=("public.mp3",), count=count)
    session.screenshot("after-cancel", tool="mp3_tool")
    expect_clean_close(context, session)


def converter_case(context):
    from journeys.common import expect_clean_close, open_tool

    session = context.app(last_tool="m4b_converter", native_dialogs=["file", "message"])
    open_tool(session, "m4b_converter")
    count = lambda: len(session.widget("m4b_converter", "importer.list.listbox").get("items", []))  # noqa: E731
    _panel(session, context.report, "converter-add-files", "m4b_converter", "importer.list.buttons[add_files]", title=TITLES["m4b"],
           multiple=True, files=True, folders=False, count=count)
    _panel(session, context.report, "converter-add-folder", "m4b_converter", "importer.list.buttons[add_folder]", title=None,
           multiple=None, files=False, folders=True, count=count)
    session.screenshot("after-cancel", tool="m4b_converter")
    expect_clean_close(context, session)


def maker_case(context):
    from journeys.common import expect_clean_close, open_tool

    session = context.app(last_tool="m4b_maker", native_dialogs=["file", "message"])
    open_tool(session, "m4b_maker")
    count = lambda: len(session.widget("m4b_maker", "track_list").get("items", []))  # noqa: E731
    _panel(session, context.report, "maker-add-files", "m4b_maker", "btn_add_files", title=TITLES["mp3"], multiple=True, files=True,
           folders=False, types=("public.mp3",), count=count)
    _panel(session, context.report, "maker-book-artwork", "m4b_maker", "book_artwork.btn_choose", title=TITLES["art"], multiple=False,
           files=True, folders=False, types=("public.jpeg", "public.png"), count=count)
    session.screenshot("after-cancel", tool="m4b_maker")
    expect_clean_close(context, session)


def cover_case(context):
    from journeys.common import expect_clean_close, open_tool

    session = context.app(last_tool="cover", native_dialogs=["file", "message"])
    open_tool(session, "cover")
    count = lambda: len(session.widget("cover", "browser.details").get("items", []))  # noqa: E731
    _panel(session, context.report, "cover-add-files", "cover", "importer.list.buttons[add_files]", title=TITLES["cover"], multiple=True,
           files=True, folders=False, types=("public.jpeg", "public.png"), count=count)
    _panel(session, context.report, "cover-add-folder", "cover", "importer.list.buttons[add_folder]", title=None, multiple=None,
           files=False, folders=True, count=count)
    session.screenshot("after-cancel", tool="cover")
    expect_clean_close(context, session)


def metadata_case(context):
    """The open panel, then (a second instance, real alerts, a book added through the stand-in) both confirmations."""
    from journeys.common import expect_clean_close, open_tool, wait_for_job, wait_until

    report = context.report
    session = context.app(last_tool="m4b_metadata", native_dialogs=["file", "message"])
    open_tool(session, "m4b_metadata")
    title = lambda: session.widget("m4b_metadata", "surface._rows[title].book_entry").get("value")  # noqa: E731
    _panel(session, report, "metadata-add-files", "m4b_metadata", "btn_add_files", title=TITLES["meta"], multiple=True, files=True,
           folders=False, count=title)
    expect_clean_close(context, session)

    book = context.fixtures.get("book-plain-m4b")
    before = context.source_hashes([book.path])
    session = context.app(last_tool="m4b_metadata", name="alerts", native_dialogs=["message"])
    open_tool(session, "m4b_metadata")
    session.click("m4b_metadata", "btn_add_files")
    session.file_dialog(book.path, title=TITLES["meta"])
    wait_until(title, 30, "the book's own values to appear")
    session.settle()
    run_root = context.output_base / "M4B-Metadata-Outputs"
    _alert(session, report, "metadata-clear-escape", "m4b_metadata", "btn_clear_tags", "escape")
    nothing = session.read("m4b_metadata", "jobs.state") == "IDLE" and not (run_root.exists() and any(run_root.iterdir()))
    FOUND["escape_ok"].append(nothing)
    report.check("metadata-clear-escape: Escape did nothing (no run, no folder)", nothing, session.read("m4b_metadata", "jobs.state"))
    numbering = _alert(session, report, "metadata-numbering-escape", "m4b_metadata", "btn_remove_numbering", "escape")
    nothing = session.read("m4b_metadata", "jobs.state") == "IDLE" and not (run_root.exists() and any(run_root.iterdir()))
    FOUND["escape_ok"].append(nothing)
    report.check("metadata-numbering-escape: Escape did nothing", nothing, numbering.get("window", {}).get("title"))
    _alert(session, report, "metadata-clear-return", "m4b_metadata", "btn_clear_tags", "return")
    started = wait_for_job(session, "m4b_metadata")
    outputs = sorted(run_root.rglob("*.m4b")) if run_root.exists() else []
    did = started == "SUCCEEDED" and len(outputs) == 1
    FOUND["return_ok"].append(did)
    report.check("metadata-clear-return: Return chose the default (Yes): one cleared copy written", did, {"state": started, "outputs": len(outputs)})
    session.screenshot("cleared-after-return", tool="m4b_metadata")
    context.require_unchanged(before)
    expect_clean_close(context, session, label="alerts close")


def main(argv=None) -> int:
    q = common.start(NAME, argv)
    if isinstance(q, int):
        return q

    def body(q):
        q.identity(native_dialogs=True, synthetic_events=True, accessibility_used=False)
        cases = [macos_common.Case("mp3-tool", "panels", mp3_case, tool="mp3-tool"),
                 macos_common.Case("m4b-converter", "panels", converter_case, tool="m4b-converter"),
                 macos_common.Case("m4b-maker", "panels", maker_case, tool="m4b-maker"),
                 macos_common.Case("m4b-metadata-editor", "panels-and-alerts", metadata_case, tool="m4b-metadata-editor"),
                 macos_common.Case("cover-image", "panels", cover_case, tool="cover-image")]
        macos_common.run_cases(q, cases)
        q.check("every tool opened a real native open panel", len(FOUND["opened"]) >= 7 and all(FOUND["opened"]), FOUND["opened"])
        q.check("every real open panel ended as Cancel added nothing", len(FOUND["cancel_ok"]) >= 7 and all(FOUND["cancel_ok"]),
                FOUND["cancel_ok"])
        q.check("a real alert's Escape did nothing", len(FOUND["escape_ok"]) >= 2 and all(FOUND["escape_ok"]), FOUND["escape_ok"])
        q.check("a real alert's Return chose its default", FOUND["return_ok"] == [True], FOUND["return_ok"])

    return q.finish(body)


if __name__ == "__main__":
    sys.exit(main())
