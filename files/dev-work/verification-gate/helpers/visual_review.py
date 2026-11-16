"""Judging one picture of the real application, and indexing a set of them (v0.8.x P1B closeout). Pure: files in, findings out
(``take_in_register`` alone renames a rejected take).

A picture is evidence only when all of this holds, and each failure is named:

  * it was really captured (``captured`` true) of a window this application drew itself -- a file panel's browser is drawn
    by another process, so its picture is UNVERIFIED, never a pass;
  * the file is a PNG that decodes, of exactly the size recorded, and that size is the window's frame times its backing scale;
  * the window fills the picture to its edges (in register): the window server's image of a window can, for an instant, be
    out of register with the window's bounds, leaving a transparent band along one edge and cutting the opposite edge off;
  * it is not blank (more than a handful of colours, real variation);
  * it shows the appearance the application was set to (a dark or light content area, and AppKit's own appearance name);
  * where Tk named solid points (``layout_audit.probes``), most of them are that colour in the picture at that place, which
    ties the image to the window Tk laid out;
  * Tk's own audit at that moment found no defect: no control's text clipped, no control outside the window, no overlapping
    controls, no text below a 3.0 contrast ratio.

PASS needs every one. A picture that could not be evaluated is UNVERIFIED, which no policy counts as a pass. Advisory findings
(a clipped label, contrast between 3.0 and 4.5) are recorded for the human reviewer and never decide the status alone.
"""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SIZE_SLACK_PX = 4
MIN_PX = (160, 90)
PROBE_TOLERANCE = 28
PROBE_SHARE = 0.6
DARK_MAX, LIGHT_MIN = 0.36, 0.55
STATUSES = ("PASS", "FAIL", "UNVERIFIED")
#: A transparent band this wide (pixels) along an edge's middle means the image is out of register; 1 px is border rounding.
REGISTER_BAND_PX = 4
REGISTER_CHECK = "the window fills the picture to its edges (in register)"
#: Retakes of a picture found out of register, and the pause before each (``take_in_register``).
RETAKES, RETAKE_PAUSE = 2, 0.4


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def edge_bands(alpha) -> dict:
    """How many fully transparent pixels run inward from each edge along the middle row and column of an alpha channel.

    A window imaged in register is opaque to its edges on those lines (its rounded corners are not on them). Measured once at
    ``b97d5bf`` (``converter.cancel-during-encode``, just after the run was cancelled): 32 px transparent at the left and the
    right 16 points cut off, with AppKit's frame and Tk's layout exactly as in 96 other pictures at that position.
    """
    width, height = alpha.size
    row, column = height // 2, width // 2

    def run(points) -> int:
        count = 0
        for point in points:
            if alpha.getpixel(point) != 0:
                break
            count += 1
        return count

    return {"left": run((x, row) for x in range(width)), "right": run((x, row) for x in range(width - 1, -1, -1)),
            "top": run((column, y) for y in range(height)), "bottom": run((column, y) for y in range(height - 1, -1, -1))}


def out_of_register(verdict: dict) -> bool:
    """True when the verdict failed the in-register check: the picture, not the window, is wrong, and a retake may be right."""
    return any(item["name"] == REGISTER_CHECK and not item["ok"] for item in verdict.get("checks", []))


def take_in_register(take, path: Path, *, retakes: int = RETAKES, pause: float = RETAKE_PAUSE, sleep=None, log=None) -> tuple[dict, list]:
    """``take()`` captures into ``path`` and returns the reviewed record; the final record and the rejected takes come back.

    Only a take whose review failed the in-register check is retaken, at most ``retakes`` times, ``pause`` seconds apart. Each
    rejected image is renamed ``<stem>.out-of-register-<n>.png`` beside the picture (no sidecar of its own, so nothing counts
    it as a picture) and described in the returned list. A take showing the wrong content, appearance or layout is never
    retaken, and a picture still out of register after the last retake fails as it was taken. The one function here that
    moves a file.
    """
    import time

    path, rejected = Path(path), []
    while True:
        record = take()
        if len(rejected) >= retakes or not out_of_register(record.get("review") or {}) or not path.is_file():
            return record, rejected
        kept = path.with_name(f"{path.stem}.out-of-register-{len(rejected) + 1}.png")
        path.replace(kept)
        review_ = record.get("review") or {}
        rejected.append({"file": kept.name, "sha256": record.get("sha256"), "at": record.get("at"),
                         "registration": review_.get("registration"), "reason": review_.get("reason")})
        if log is not None:
            log(rejected[-1])
        (sleep or time.sleep)(pause)


def layout_defects(audit: dict) -> list[str]:
    lines = [f"control text clipped: {item['path']} {item['text']!r} asked {item['requested']}, given {item['given']}"
             for item in audit.get("clipped", []) if item.get("kind") == "control"]
    lines += [f"control outside the window: {item['path']} {item['text']!r} at {item['box']}"
              for item in audit.get("outside", []) if item.get("kind") == "control"]
    lines += [f"overlapping controls: {item['first']} and {item['second']} ({item['area']} square points)" for item in audit.get("overlaps", [])]
    lines += [f"text contrast {item['ratio']} below 3.0: {item['path']} {item['text']!r}" for item in audit.get("contrast", [])
              if item.get("kind") == "defect"]
    return lines


def layout_advisories(audit: dict) -> list[str]:
    lines = [f"label text clipped: {item['path']} {item['text']!r} asked {item['requested']}, given {item['given']}"
             for item in audit.get("clipped", []) if item.get("kind") != "control"]
    lines += [f"text contrast {item['ratio']} below 4.5: {item['path']} {item['text']!r}" for item in audit.get("contrast", [])
              if item.get("kind") != "defect"]
    return lines


def _luminance(pixel) -> float:
    red, green, blue = pixel[:3]
    return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255


def review(png: Path, record: dict) -> dict:
    """The verdict on one picture and its sidecar ``record`` (what the session wrote beside it)."""
    found = {"status": "UNVERIFIED", "checks": [], "defects": [], "advisories": [], "reason": ""}

    def check(name: str, ok: bool, detail: str = "") -> bool:
        found["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:400]})
        return bool(ok)

    if not record.get("captured"):
        found["reason"] = f"not captured: {record.get('why') or 'no reason given'}"
        return found
    if record.get("content_is_remote"):
        found["reason"] = "the panel's content is drawn by another process (openAndSavePanelService); this picture is not evidence of it"
        return found
    png = Path(png)
    try:
        raw = png.read_bytes()
    except OSError as exc:
        found["reason"] = f"the picture is missing: {exc}"
        return found
    if not check("is a PNG", raw[:8] == PNG_SIGNATURE, png.name):
        found["status"], found["reason"] = "FAIL", "not a PNG"
        return found
    if record.get("sha256") and not check("is the file the session recorded", sha256(png) == record["sha256"]):
        found["status"], found["reason"] = "FAIL", "the picture is not the one the session recorded"
        return found
    try:
        from PIL import Image

        with Image.open(png) as opened:
            opened.load()
            alpha = opened.getchannel("A") if "A" in opened.getbands() else None
            image = opened.convert("RGB")
    except Exception as exc:  # noqa: BLE001 - an undecodable picture is a finding, not a crash
        found["status"], found["reason"] = "FAIL", f"the picture does not decode: {type(exc).__name__}: {exc}"
        return found
    width, height = image.size
    check("decodes at the recorded size", (width, height) == (record.get("width_px"), record.get("height_px")),
          f"{width}x{height} against {record.get('width_px')}x{record.get('height_px')}")
    window = record.get("window") or {}
    frame, scale = window.get("frame") or [0, 0, 0, 0], float(window.get("scale") or 0)
    expected = (round(frame[2] * scale), round(frame[3] * scale))
    check("is the window's frame at its backing scale", scale > 0 and abs(width - expected[0]) <= SIZE_SLACK_PX
          and abs(height - expected[1]) <= SIZE_SLACK_PX, f"{width}x{height} against {expected[0]}x{expected[1]} (scale {scale})")
    check("has a plausible size", width >= MIN_PX[0] and height >= MIN_PX[1], f"{width}x{height}")
    if alpha is not None:  # every subject here is a window-server image of one of the application's own windows
        bands = edge_bands(alpha)
        found["registration"] = bands
        check(REGISTER_CHECK, max(bands.values()) < REGISTER_BAND_PX,
              "transparent inward from each edge's middle: " + ", ".join(f"{side} {pixels} px" for side, pixels in bands.items()))
    small = image.resize((96, 96))
    pixels = list(small.getdata())
    levels = [_luminance(pixel) for pixel in pixels]
    mean = sum(levels) / len(levels)
    spread = (sum((level - mean) ** 2 for level in levels) / len(levels)) ** 0.5
    colours = len({tuple(value // 8 for value in pixel) for pixel in pixels})
    check("is not blank", spread >= 0.015 and colours >= 12, f"luminance spread {spread:.3f}, {colours} colours")
    audit = record.get("layout") or {}
    content = audit.get("window_points") or [frame[2], frame[3]]
    title_bar = max(0.0, frame[3] - float(content[1])) if frame[3] else 0.0
    appearance = record.get("appearance") or {}
    wanted = appearance.get("app")
    if wanted in ("dark", "light") and record.get("subject", "window") == "window":
        top = round(title_bar * scale)
        body = image.crop((0, top, width, height)).resize((64, 64))
        body_mean = sum(_luminance(pixel) for pixel in body.getdata()) / (64 * 64)
        if wanted == "dark":
            check("shows the dark appearance it was set to", body_mean <= DARK_MAX, f"content luminance {body_mean:.2f}")
        else:
            check("shows the light appearance it was set to", body_mean >= LIGHT_MIN, f"content luminance {body_mean:.2f}")
        native = str(appearance.get("native") or "")
        if native:
            check("AppKit drew the window in that appearance", ("Dark" in native) == (wanted == "dark"), native)
    probes = audit.get("probes") or []
    if len(probes) >= 3 and scale > 0:
        matched = 0
        for probe in probes:
            x, y = round(probe["x"] * scale), round((probe["y"] + title_bar) * scale)
            if 0 <= x < width and 0 <= y < height:
                pixel = image.getpixel((x, y))
                if max(abs(int(a) - int(b)) for a, b in zip(pixel, probe["rgb"])) <= PROBE_TOLERANCE:
                    matched += 1
        check("Tk's solid points are where Tk put them", matched >= PROBE_SHARE * len(probes), f"{matched} of {len(probes)} probes")
    elif record.get("subject", "window") == "window":
        found["advisories"].append(f"only {len(probes)} solid points to register the picture against Tk's layout")
    found["defects"] = layout_defects(audit)
    found["advisories"] += layout_advisories(audit)
    failed = [item["name"] for item in found["checks"] if not item["ok"]]
    if failed or found["defects"]:
        found["status"] = "FAIL"
        found["reason"] = "; ".join(failed + found["defects"][:6])
    else:
        found["status"], found["reason"] = "PASS", f"{len(found['checks'])} picture checks, Tk audit of {audit.get('widgets', 0)} widgets"
    return found


def load_record(png: Path) -> dict | None:
    sidecar = Path(png).with_suffix(".json")
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def contact_sheet(entries: list[dict], folder: Path, *, title: str) -> dict:
    """``index.html`` (every picture, its provenance and its review) and ``contact-sheet.png`` (thumbnails) in ``folder``."""
    from PIL import Image, ImageDraw

    folder = Path(folder)
    rows = []
    thumbs = []
    for entry in entries:
        png = folder / entry["path"]
        record, verdict = entry.get("record") or {}, entry.get("review") or {}
        rows.append("<tr><td><a href='{0}'><img src='{0}' width='240'></a></td><td>{1}</td><td><b>{2}</b><br>{3}</td><td>{4}</td></tr>".format(
            html.escape(entry["path"]), html.escape(json.dumps({key: record.get(key) for key in (
                "tool", "state", "scenario", "viewport", "appearance", "sha", "dirty", "subject", "retakes")}, indent=1)),
            html.escape(verdict.get("status", "")), html.escape(verdict.get("reason", "")),
            "<br>".join(html.escape(line) for line in verdict.get("defects", []) + verdict.get("advisories", []))))
        if png.is_file() and record.get("captured"):
            try:
                with Image.open(png) as opened:
                    thumb = opened.convert("RGB")
                    thumb.thumbnail((360, 240))
                    thumbs.append((thumb, f"{verdict.get('status', '?')} {entry['path']}"[:60]))
            except Exception:  # noqa: BLE001 - the index still lists it
                continue
    page = ("<!doctype html><meta charset='utf-8'><title>{0}</title><style>body{{font:13px -apple-system,sans-serif}}td{{vertical-align:top;"
            "border-bottom:1px solid #ccc;padding:4px}}pre{{margin:0}}</style><h1>{0}</h1><table>{1}</table>").format(
        html.escape(title), "".join(rows))
    (folder / "index.html").write_text(page, encoding="utf-8")
    sheet_path = None
    if thumbs:
        columns = 4
        cell_w, cell_h = 370, 270
        sheet = Image.new("RGB", (columns * cell_w, ((len(thumbs) + columns - 1) // columns) * cell_h), "white")
        draw = ImageDraw.Draw(sheet)
        for index, (thumb, caption) in enumerate(thumbs):
            x, y = (index % columns) * cell_w + 5, (index // columns) * cell_h + 5
            sheet.paste(thumb, (x, y))
            draw.text((x, y + 245), caption, fill="black")
        sheet_path = folder / "contact-sheet.png"
        sheet.save(sheet_path)
    return {"index": "index.html", "sheet": sheet_path.name if sheet_path else None, "pictures": len(entries), "thumbnails": len(thumbs)}
