"""Cover Image: real images through the real dialog, real resizing, and the output's own pixels read back."""

from __future__ import annotations

from pathlib import Path

from journeys.common import Context, expect_clean_close, log_text, open_tool, scenario, wait_for_job, wait_until

RED, GREEN, BLUE, YELLOW = (220, 20, 20), (20, 200, 20), (20, 20, 220), (230, 210, 20)
BACKGROUND = (200, 200, 200)


def _near(pixel, colour, tolerance: int = 28) -> bool:
    return all(abs(int(a) - int(b)) <= tolerance for a, b in zip(pixel[:3], colour))


def _open_image(context: Context, path: Path, label: str, size: int, kind: str):
    from PIL import Image

    report = context.report
    report.record_output(path)
    report.require(f"{label}: exists", path.is_file(), path.name)
    with Image.open(path) as image:
        image.load()
        report.equal(f"{label}: dimensions", list(image.size), [size, size])
        report.equal(f"{label}: format", image.format, kind)
        return image.convert("RGB")


def _import(session, context: Context, ids: list[str]) -> list[Path]:
    paths = [context.fixtures.path(identifier) for identifier in ids]
    session.click("cover", "importer.list.buttons[add_files]")
    session.file_dialog(paths if len(paths) > 1 else paths[0], title="Select cover images")
    wait_until(lambda: len(session.widget("cover", "browser.details").get("items", [])) == len(paths), 30, "the browser to list the images")
    return paths


@scenario("cover.letterbox-numbered-run", tool="cover-image", layers=("native", "media"), tier="journey",
          summary="Add Files through the real dialog, target size typed, Resize Covers; letterboxed outputs read back pixel by pixel")
def letterbox(context: Context) -> None:
    report = context.report
    session = context.app(last_tool="cover")
    open_tool(session, "cover")
    paths = _import(session, context, ["cover-portrait-png", "cover-landscape-jpeg", "cover-alpha-png"])
    before = context.source_hashes(paths)
    session.type_into("cover", "entry_size", "512")
    report.check("letterbox is the default", session.widget("cover", "chk_letterbox").get("selected"), "the box a person sees ticked")
    session.screenshot("ready")
    session.click("cover", "btn_convert")
    state = wait_for_job(session, "cover")
    session.screenshot("finished")
    report.equal("the run ended", state, "SUCCEEDED")
    run = context.run_dir("cover")
    report.equal("exactly the planned files", sorted(item.name for item in run.iterdir()), ["alpha.png", "landscape.jpg", "portrait.png"])
    report.equal("the shown output folder is the run", session.widget("cover", "entry_outdir").get("value"), str(run))

    portrait = _open_image(context, run / "portrait.png", "portrait", 512, "PNG")
    # 300x500 scaled to 512 tall is 307 wide, centred, so bands of about 102 px stand either side and the source's corners stay.
    report.check("portrait: red corner kept, not cropped", _near(portrait.getpixel((102 + 8, 8)), RED), portrait.getpixel((110, 8)))
    report.check("portrait: yellow corner kept", _near(portrait.getpixel((102 + 299, 503)), YELLOW), portrait.getpixel((401, 503)))
    report.check("portrait: a band beside it, not stretched", not _near(portrait.getpixel((20, 256)), BACKGROUND, 12), portrait.getpixel((20, 256)))
    landscape = _open_image(context, run / "landscape.jpg", "landscape", 512, "JPEG")
    report.check("landscape: green corner kept", _near(landscape.getpixel((503, 128 + 8)), GREEN), landscape.getpixel((503, 136)))
    report.check("landscape: blue corner kept", _near(landscape.getpixel((8, 128 + 247)), BLUE), landscape.getpixel((8, 375)))
    _open_image(context, run / "alpha.png", "alpha", 512, "PNG")
    context.require_unchanged(before)
    report.check("the Summary says it finished", "All done" in log_text(session, "cover") or "finished" in log_text(session, "cover").lower(),
                 log_text(session, "cover")[-300:])
    expect_clean_close(context, session)


@scenario("cover.center-crop", tool="cover-image", layers=("native", "media"), tier="journey",
          summary="The letterbox box unticked with a real click, then the crop shown in the output's pixels")
def crop(context: Context) -> None:
    report = context.report
    session = context.app(last_tool="cover")
    open_tool(session, "cover")
    paths = _import(session, context, ["cover-landscape-jpeg"])
    session.type_into("cover", "entry_size", "256")
    session.click("cover", "chk_letterbox")
    wait_until(lambda: not session.widget("cover", "chk_letterbox").get("selected"), 5, "the letterbox box to clear")
    session.click("cover", "btn_convert")
    report.equal("the run ended", wait_for_job(session, "cover"), "SUCCEEDED")
    session.screenshot("finished")
    image = _open_image(context, context.run_dir("cover") / "landscape.jpg", "cropped", 256, "JPEG")
    for corner, colour in (((8, 8), RED), ((247, 8), GREEN), ((8, 247), BLUE), ((247, 247), YELLOW)):
        report.check(f"cropped: the source's corner at {corner} is gone", not _near(image.getpixel(corner), colour), image.getpixel(corner))
    report.check("cropped: filled by the image's middle", _near(image.getpixel((128, 128)), BACKGROUND), image.getpixel((128, 128)))
    context.require_unchanged(context.source_hashes(paths))
    expect_clean_close(context, session)


@scenario("cover.corrupt-image", tool="cover-image", layers=("native", "media"), tier="adverse",
          summary="A truncated PNG beside a good image: the good one is published, the bad one is named as failed and left unchanged")
def corrupt(context: Context) -> None:
    report = context.report
    session = context.app(last_tool="cover")
    open_tool(session, "cover")
    bad = context.fixtures.path("cover-truncated")
    good = context.fixtures.path("cover-portrait-png")
    before = context.source_hashes([bad, good])
    session.click("cover", "importer.list.buttons[add_files]")
    session.file_dialog(good, title="Select cover images")
    wait_until(lambda: len(session.widget("cover", "browser.details").get("items", [])) == 1, 30, "the good image to be listed")
    session.click("cover", "importer.list.buttons[add_files]")
    session.file_dialog(bad, title="Select cover images")
    wait_until(lambda: len(session.widget("cover", "browser.details").get("items", [])) == 2, 30, "both images to be listed")
    session.click("cover", "btn_convert")
    state = wait_for_job(session, "cover")
    session.screenshot("finished")
    report.equal("the run reports the failure", state, "COMPLETED_WITH_FAILURES")
    produced = sorted(item.name for item in context.run_dir("cover").iterdir())
    report.equal("only the good image was published", produced, ["portrait.png"])
    _open_image(context, context.run_dir("cover") / "portrait.png", "good image", 1024, "PNG")
    detail = log_text(session, "cover", "details_text") + log_text(session, "cover")
    report.check("the failure names the bad file", "broken.png" in detail, detail[-400:])
    report.check("Retry Failed is offered", not session.widget("cover", "jobs.controls.buttons[RETRY_FAILED]").get("disabled"), "")
    context.require_unchanged(before)
    expect_clean_close(context, session)
