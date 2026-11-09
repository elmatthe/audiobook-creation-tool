"""The launcher: six tools by physical clicks, real sizes, what survives a relaunch, and switching tools with work running."""

from __future__ import annotations

import json

from journeys.common import Context, TOOLS, expect_clean_close, native, open_tool, oracle, resize_and_check, scenario, wait_for_job, wait_until

#: The controls a user cannot do without, per tool. Each must be wholly on screen at every supported size.
PRIMARY = {
    "tts": ["go_btn", "jobs.controls.buttons[CANCEL]", "jobs.controls.buttons[PAUSE]", "importer.list.buttons[add_files]", "voice_combo"],
    "mp3_tool": ["btn_write_id3", "btn_combine", "btn_add_files", "jobs.controls.buttons[CANCEL]", "surface._rows[album].shared_entry"],
    "m4b_converter": ["btn_convert", "jobs.controls.buttons[CANCEL]", "importer.list.buttons[add_files]", "rb_split"],
    "m4b_maker": ["btn_build", "btn_add_files", "jobs.controls.buttons[CANCEL]", "surface._rows[album].shared_entry"],
    "m4b_metadata": ["btn_save", "btn_add_files", "btn_clear_tags", "jobs.controls.buttons[CANCEL]", "surface._rows[album].shared_entry"],
    "cover": ["btn_convert", "jobs.controls.buttons[CANCEL]", "importer.list.buttons[add_files]", "entry_size"],
}
SIZES = [(920, 600), (1024, 720), (1400, 900)]


@scenario("launcher.six-tools-at-three-sizes", tool="launcher", layers=("native", "visual"), tier="geometry", budget=300,
          summary="Each tool opened by a physical click at 920x600, 1024x720 and 1400x900: its primary controls wholly on screen, candidates captured for review")
def six_tools(context: Context) -> None:
    report = context.report
    session = context.app()
    report.equal("the window opens at the default size", list(native.client_size(session.hwnd)), [1024, 720])
    report.equal("the default tool is open with no output anywhere", session.read(None, "current_key"), "tts")
    for tool in TOOLS:
        open_tool(session, tool)
        for size in SIZES:
            resize_and_check(session, context, tool, PRIMARY[tool], size)
            session.screenshot(f"{tool}-{size[0]}x{size[1]}")
    wait_until(lambda: tuple(native.client_size(session.hwnd)) == SIZES[-1], 2, "the last size to hold")
    native.resize_client(session.hwnd, 700, 400)
    wait_until(lambda: native.client_size(session.hwnd)[0] >= 920, 5, "the window manager to respond")
    client = native.client_size(session.hwnd)
    report.check("the minimum size holds against a smaller request", client[0] >= 920 and client[1] >= 600, client)
    expect_clean_close(context, session)
    report.check("no output folder appeared just from looking", not context.output_base.exists() or not any(context.output_base.rglob("*.*")))


@scenario("launcher.settings-survive-relaunch", tool="launcher", layers=("native",), tier="journey",
          summary="Tool choice and appearance set by real clicks, the window resized by the window manager and closed, the app relaunched: "
                  "tool and appearance restored from the isolated settings file only, the size never carried over")
def settings(context: Context) -> None:
    report = context.report
    first = context.app(name="first")
    open_tool(first, "cover")
    before = first.read(None, "appearance_button") and first.widget(None, "appearance_button").get("text")
    first.click(None, "appearance_button")
    first.settle()
    after = first.widget(None, "appearance_button").get("text")
    report.check("the appearance button changed", before != after, f"{before!r} -> {after!r}")
    first.screenshot("changed")
    # v0.7.2 Phase 6, ACT72-056: a size the person chose is deliberately not remembered.
    native.resize_client(first.hwnd, 1400, 900)
    wait_until(lambda: tuple(native.client_size(first.hwnd)) == (1400, 900), 8, "the first window to reach 1400x900")
    expect_clean_close(context, first, label="first close")
    saved = json.loads((first.work / "runtime" / "settings.json").read_text(encoding="utf-8"))
    report.equal("the tool was written to the isolated settings", saved.get("last_tool"), "cover")
    report.check("the appearance was written to the isolated settings", saved.get("appearance") in ("light", "dark"), saved.get("appearance"))

    second = context.app(name="second", last_tool=saved.get("last_tool"), settings={"appearance": saved.get("appearance")})
    wait_until(lambda: second.widget(None, "appearance_button").get("text"), 10, "the appearance button")
    report.equal("the tool is restored", second.read(None, "current_key"), "cover")
    report.equal("the appearance is restored", second.widget(None, "appearance_button").get("text"), after)
    report.equal("the window opens at the default size, not the size it was closed at", list(native.client_size(second.hwnd)), [1024, 720])
    report.check("no window size or position was saved", not [key for key in saved if any(word in key.lower() for word in ("geometry", "size", "position", "window"))],
                 sorted(saved))
    second.screenshot("relaunched")
    expect_clean_close(context, second, label="second close")


@scenario("launcher.switch-tools-during-work", tool="launcher", layers=("native", "media"), tier="journey",
          summary="While a Converter run works, a physical click opens another tool and comes back: the run is still its own and its output is complete")
def switching(context: Context) -> None:
    report = context.report
    book = context.fixtures.get("book-long-m4b")
    session = context.app(last_tool="m4b_converter")
    open_tool(session, "m4b_converter")
    session.click("m4b_converter", "importer.list.buttons[add_files]")
    session.file_dialog(book.path, title="Select .m4b files")
    wait_until(lambda: len(session.widget("m4b_converter", "importer.list.listbox").get("items", [])) == 1, 30, "the book to be listed")
    session.click("m4b_converter", "rb_split")
    session.click("m4b_converter", "btn_convert")
    wait_until(lambda: session.read("m4b_converter", "jobs.state") == "RUNNING", 30, "the run to start")
    open_tool(session, "cover")
    report.equal("the other tool is really showing", session.widget("cover", "btn_convert").get("viewable"), True)
    report.check("the run keeps going while hidden", session.read("m4b_converter", "jobs.state") in ("RUNNING", "SUCCEEDED"))
    session.screenshot("switched-away")
    open_tool(session, "m4b_converter")
    report.equal("the run ended", wait_for_job(session, "m4b_converter", timeout=240), "SUCCEEDED")
    session.screenshot("came-back")
    outputs = sorted(context.run_dir("m4b_converter").rglob("*.mp3"))
    report.equal("all four chapters are there", len(outputs), 4)
    for index, output in enumerate(outputs):
        # The looped fixture loses about 21 ms of timestamps at each of its loops, so 15 minutes reads up to a second off. Measured, and its own:
        # this journey is about work surviving a tool switch. Exact boundaries are converter.split-by-chapter's, on a fixture built for them.
        oracle.inspect_audio(context.tools, output, report, label=f"chapter {index + 1}", codec="mp3", duration=900.0, duration_tolerance=1.2)
    expect_clean_close(context, session)
