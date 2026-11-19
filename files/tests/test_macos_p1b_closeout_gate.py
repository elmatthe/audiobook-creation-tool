"""v0.8.x P1B closeout -- real pictures, the dialog contract, the revised darwin policy and incremental evidence cannot pass falsely.

The owner's instruction of 2026-11-15 replaced the P1B manual checklist with automated evidence and asked for negative tests
showing that missing screenshots, invalid captures, failed visual inspection, missing functional artifacts, unexpected
outputs and incomplete process cleanup cannot result in PASS; and for incremental verification that keeps earlier evidence
with its SHA and invalidates only what a change can reach. Pure tests, on every platform (synthetic PNGs drawn with Pillow,
a throwaway git repository for the ledger); nothing here starts the application.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gate_locator import GATE_DIR, REPO_ROOT, load_gate

sys.path.insert(0, str(GATE_DIR))
from helpers import acceptance_report as ar  # noqa: E402
from helpers import evidence_ledger as ledger  # noqa: E402
from helpers import visual_review as vr  # noqa: E402

sys.path.remove(str(GATE_DIR))

POLICY = json.loads((GATE_DIR / "verification.json").read_text(encoding="utf-8"))
ACCEPTANCE = POLICY["acceptance"]
SHA = "b" * 40
ID = "mp3.write-id3-then-combine"
#: The twenty journeys whose native-dialog steps used to wait on the owner's signed checklist record.
FORMERLY_MANUAL = [
    "launcher.six-tools-at-three-sizes", "launcher.settings-survive-relaunch", "launcher.switch-tools-during-work",
    "cover.letterbox-numbered-run", "cover.center-crop", "cover.corrupt-image", "cover.replace-confirmation",
    "mp3.write-id3-then-combine", "mp3.unreadable-track", "mp3.typed-values-survive-first-import",
    "converter.split-by-chapter", "converter.whole-book-replace-metadata", "converter.corrupt-source", "converter.cancel-during-encode",
    "maker.build-with-chapters-and-artwork", "maker.unreadable-track", "maker.wheel-over-a-long-book",
    "metadata.save-tags-then-clear", "metadata.confirmation-declined", "metadata.unreadable-file"]


# --------------------------------------------------------------------------- #
#  Synthetic pictures
# --------------------------------------------------------------------------- #
def _picture(folder: Path, name: str = "shot", *, appearance: str = "dark", blank: bool = False, size=(400, 300), scale: float = 2.0,
             title_bar: int = 28, audit: dict | None = None, **record) -> tuple[Path, dict]:
    """A PNG shaped like a window-server capture of a Tk window, and the sidecar record the session writes beside it."""
    from PIL import Image, ImageDraw

    width, height = size
    pixels = (round(width * scale), round((height + title_bar) * scale))
    background = (30, 30, 32) if appearance == "dark" else (236, 236, 236)
    image = Image.new("RGB", pixels, background)
    probes = []
    if not blank:
        draw = ImageDraw.Draw(image)
        draw.rectangle([0, 0, pixels[0], title_bar * scale], fill=(60, 60, 64) if appearance == "dark" else (210, 210, 210))
        for index in range(12):
            x, y = 20 + (index % 4) * 90, 40 + (index // 4) * 80
            colour = (40 + index * 15, 90, 200 - index * 10)
            draw.rectangle([x * scale, (y + title_bar) * scale, (x + 60) * scale, (y + 40 + title_bar) * scale], fill=colour)
            probes.append({"path": f".w{index}", "class": "Frame", "x": x + 5, "y": y + 5, "rgb": list(colour)})
            # Text below the probe point, as a probe is always a point no child covers.
            draw.text(((x + 30) * scale, (y + 24 + title_bar) * scale), f"{index}", fill=(255, 255, 255))
    path = folder / f"{name}.png"
    folder.mkdir(parents=True, exist_ok=True)
    image.save(path)
    base = {"name": path.name, "captured": True, "width_px": pixels[0], "height_px": pixels[1], "sha": SHA, "subject": "window",
            "window": {"frame": [0, 0, width, height + title_bar], "scale": scale},
            "appearance": {"app": appearance, "native": "NSAppearanceNameDarkAqua" if appearance == "dark" else "NSAppearanceNameAqua"},
            "layout": audit if audit is not None else {"widgets": 40, "window_points": [width, height], "probes": probes,
                                                       "clipped": [], "outside": [], "overlaps": [], "contrast": []},
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    base.update(record)
    path.with_suffix(".json").write_text(json.dumps(base), encoding="utf-8")
    return path, base


def test_a_real_looking_capture_passes_review(tmp_path):
    for appearance in ("dark", "light"):
        path, record = _picture(tmp_path / appearance, appearance=appearance)
        verdict = vr.review(path, record)
        assert verdict["status"] == "PASS", verdict


def _surround(*, rgb, x: int = 30, y: int = 270) -> dict:
    """A native button's rectangle as ``layout_audit.surrounds`` names it; (30, 270) is the synthetic window's background."""
    return {"path": ".status.button", "surface": ".status", "text": "Dark mode", "x": x, "y": y, "rgb": rgb}


def test_a_native_button_on_its_own_surface_colour_passes_review(tmp_path):
    """ACT72-081's check passes a button whose rectangle is the colour of the surface it sits on, in either appearance."""
    for appearance, background in (("dark", [30, 30, 32]), ("light", [236, 236, 236])):
        path, record = _picture(tmp_path / appearance, appearance=appearance)
        record["layout"]["surrounds"] = [_surround(rgb=background)]
        verdict = vr.review(path, record)
        assert verdict["status"] == "PASS" and not verdict["defects"], verdict


@pytest.mark.parametrize("damage, status, words", [
    ("not captured", "UNVERIFIED", "not captured"),
    ("remote content", "UNVERIFIED", "another process"),
    ("missing file", "UNVERIFIED", "missing"),
    ("placeholder bytes", "FAIL", "not a PNG"),
    ("swapped file", "FAIL", "not the one the session recorded"),
    ("size lies", "FAIL", "decodes at the recorded size"),
    ("not the window", "FAIL", "frame at its backing scale"),
    ("blank", "FAIL", "is not blank"),
    ("wrong appearance", "FAIL", "appearance it was set to"),
    ("misplaced probes", "FAIL", "solid points"),
    ("clipped control", "FAIL", "control text clipped"),
    ("overlapping controls", "FAIL", "overlapping controls"),
    ("low contrast", "FAIL", "below 3.0"),
    ("tiny placeholder png", "FAIL", "plausible size"),
    ("button in a box", "FAIL", "in a box of another colour"),
])
def test_an_invalid_capture_or_a_failed_inspection_is_never_a_pass(tmp_path, damage, status, words):
    """Never a pass when captured is false, never a placeholder PNG, never a picture whose review found a defect."""
    path, record = _picture(tmp_path)
    if damage == "not captured":
        record.update(captured=False, why="no Screen Recording grant")
    elif damage == "remote content":
        record["content_is_remote"] = True
    elif damage == "missing file":
        path.unlink()
    elif damage == "placeholder bytes":
        path.write_bytes(b"not an image at all")
    elif damage == "swapped file":
        _other, _ = _picture(tmp_path / "other", appearance="light")
        path.write_bytes(_other.read_bytes())
    elif damage == "size lies":
        record["width_px"] += 10
    elif damage == "not the window":
        record["window"]["frame"][2] += 100
    elif damage == "blank":
        path, record = _picture(tmp_path / "blank", blank=True)
    elif damage == "wrong appearance":
        record["appearance"] = {"app": "light", "native": "NSAppearanceNameAqua"}
    elif damage == "misplaced probes":
        for probe in record["layout"]["probes"]:
            probe["x"] += 70  # into the gap between the solid boxes: the picture is not the layout Tk described
    elif damage == "clipped control":
        record["layout"]["clipped"] = [{"path": ".b", "class": "TButton", "text": "Build M4B(s)", "kind": "control",
                                        "requested": [120, 24], "given": [80, 24]}]
    elif damage == "overlapping controls":
        record["layout"]["overlaps"] = [{"first": ".a", "second": ".b", "area": 400}]
    elif damage == "low contrast":
        record["layout"]["contrast"] = [{"path": ".l", "class": "TLabel", "text": "faint", "ratio": 1.4, "kind": "defect"}]
    elif damage == "button in a box":
        # ACT72-081: Tk's surface is light grey; the picture shows the (dark) window colour there.
        record["layout"]["surrounds"] = [_surround(rgb=[236, 236, 236])]
    elif damage == "tiny placeholder png":
        from PIL import Image

        Image.new("RGB", (1, 1)).save(path)
        record.update(width_px=1, height_px=1, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                      window={"frame": [0, 0, 0.5, 0.5], "scale": 2.0})
    verdict = vr.review(path, record)
    assert verdict["status"] == status and words in (verdict["reason"] + " ".join(item["name"] for item in verdict["checks"]
                                                                                   if not item["ok"])), verdict


def test_advisories_alone_do_not_fail_a_picture(tmp_path):
    path, record = _picture(tmp_path)
    record["layout"]["clipped"] = [{"path": ".l", "class": "TLabel", "text": "/a/long/path", "kind": "label", "requested": [400, 20],
                                    "given": [200, 20]}]
    record["layout"]["contrast"] = [{"path": ".s", "class": "TLabel", "text": "hint", "ratio": 4.1, "kind": "advisory"}]
    verdict = vr.review(path, record)
    assert verdict["status"] == "PASS" and len(verdict["advisories"]) == 2, verdict


def _as_window_server_returned(path: Path, record: dict, *, shift_px: int = 0, clear_rows: tuple = ()) -> None:
    """Make a synthetic picture RGBA like a real capture. ``shift_px`` draws the window that far right of the image's bounds, as
    the window server returned it once at ``b97d5bf`` (``converter.cancel-during-encode``: 32 px transparent at the left, the
    right edge cut off, the same size); ``clear_rows`` makes whole rows transparent, as a 1 px border rounding does."""
    from PIL import Image

    with Image.open(path) as opened:
        window = opened.convert("RGBA")
    picture = Image.new("RGBA", window.size, (0, 0, 0, 0))
    picture.paste(window, (shift_px, 0))
    for row in clear_rows:
        for x in range(picture.size[0]):
            picture.putpixel((x, row % picture.size[1]), (0, 0, 0, 0))
    picture.save(path)
    record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_picture_out_of_register_fails_by_name_and_a_border_pixel_does_not(tmp_path):
    """Regression (b97d5bf, converter.cancel-during-encode): an image offset from the window's bounds is never a pass, and the
    review says what is wrong with the picture rather than only that Tk's points are elsewhere."""
    path, record = _picture(tmp_path / "in")
    _as_window_server_returned(path, record)
    verdict = vr.review(path, record)
    assert verdict["status"] == "PASS" and verdict["registration"] == {"left": 0, "right": 0, "top": 0, "bottom": 0}, verdict

    path, record = _picture(tmp_path / "border")
    _as_window_server_returned(path, record, clear_rows=(0, -1))
    verdict = vr.review(path, record)
    assert verdict["status"] == "PASS" and not vr.out_of_register(verdict), verdict

    path, record = _picture(tmp_path / "out")
    _as_window_server_returned(path, record, shift_px=32)
    verdict = vr.review(path, record)
    assert verdict["status"] == "FAIL" and vr.out_of_register(verdict) and vr.REGISTER_CHECK in verdict["reason"], verdict
    assert verdict["registration"]["left"] == 32 and verdict["registration"]["right"] == 0


def _taker(path: Path, record: dict, takes: list[dict]):
    """A stand-in for one capture: writes the next synthetic take into ``path`` and returns its reviewed record."""
    import shutil

    good = path.with_name("good.png")
    shutil.copyfile(path, good)

    def take() -> dict:
        shape = takes.pop(0)
        shutil.copyfile(good, path)
        fresh = json.loads(json.dumps(record))
        _as_window_server_returned(path, fresh, **shape)
        fresh["review"] = vr.review(path, fresh)
        return fresh

    return take


def test_only_a_take_out_of_register_is_retaken_and_every_rejected_take_is_kept(tmp_path):
    path, record = _picture(tmp_path / "retake")
    logged, slept = [], []
    final, rejected = vr.take_in_register(_taker(path, record, [{"shift_px": 32}, {}]), path, sleep=slept.append, log=logged.append)
    assert final["review"]["status"] == "PASS" and len(rejected) == 1 and len(logged) == 1 and slept == [vr.RETAKE_PAUSE]
    kept = path.with_name(rejected[0]["file"])
    assert kept.name == "shot.out-of-register-1.png" and kept.is_file() and not kept.with_suffix(".json").exists()
    assert rejected[0]["registration"]["left"] == 32 and hashlib.sha256(kept.read_bytes()).hexdigest() == rejected[0]["sha256"]


def test_a_picture_still_out_of_register_after_the_last_retake_fails(tmp_path):
    path, record = _picture(tmp_path / "never")
    final, rejected = vr.take_in_register(_taker(path, record, [{"shift_px": 32}] * (vr.RETAKES + 1)), path, sleep=lambda _s: None)
    assert final["review"]["status"] == "FAIL" and vr.out_of_register(final["review"]) and len(rejected) == vr.RETAKES


def test_a_picture_with_the_wrong_content_is_never_retaken(tmp_path):
    """A take that is in register but wrong (here: the wrong appearance) fails as it was taken; retaking is not a way to a pass."""
    path, record = _picture(tmp_path / "wrong")
    record["appearance"] = {"app": "light", "native": "NSAppearanceNameAqua"}
    final, rejected = vr.take_in_register(_taker(path, record, [{}, {}]), path, sleep=lambda _s: None)
    assert final["review"]["status"] == "FAIL" and not vr.out_of_register(final["review"]) and rejected == []


def _pure_function(path: Path, name: str):
    """One module-level function of a source file, compiled alone (``native_ui`` loads libobjc at import, so it cannot be
    imported off macOS; the function under test uses nothing else of the module)."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    namespace: dict = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102 - our own source
    return namespace[name], tree


def test_a_return_reaches_a_real_alert_whether_or_not_the_application_is_active():
    """Regression (c0a1553, f8af54b): with a system alert frontmost the application is not active, and AppKit honours no key
    equivalent in it: a posted Return left the real alert up for ever (c0a1553), and so did handing the event to the alert
    window's performKeyEquivalent: (f8af54b). Return is then answered by the button Return presses -- the window's
    defaultButtonCell (Tk's Yes carries no key equivalent of its own, measured) -- performing its click, recorded as that
    route; Escape, measured to work either way, keeps the queue."""
    source = GATE_DIR / "adapters" / "macos" / "native_ui.py"
    route, tree = _pure_function(source, "alert_key_route")
    alert = 8283
    active = {"active": True, "key_window": alert}
    assert route("return", active, alert) == "queue" and route("escape", active, alert) == "queue"
    for state in ({"active": False, "key_window": None}, {"active": True, "key_window": 17}, {"active": False, "key_window": alert}):
        assert route("return", state, alert) == "default-button", state
        assert route("escape", state, alert) == "queue", state
    import ast

    text = source.read_text(encoding="utf-8")
    answer = next(item for item in ast.walk(tree) if getattr(item, "name", "") == "_answer")
    body = "\n".join(text.splitlines()[answer.lineno - 1:answer.end_lineno])
    assert "alert_key_route(respond, state, window[\"number\"])" in body and 'return_button(window["ptr"])' in body
    assert '"performClick:"' in body and '"performKeyEquivalent:"' not in body
    assert all(key in body for key in ('"route": route', '"app_active": state["active"]', '"alert_was_key"', '"button":'))
    finder = next(item for item in ast.walk(tree) if getattr(item, "name", "") == "return_button")
    assert '"defaultButtonCell"' in "\n".join(text.splitlines()[finder.lineno - 1:finder.end_lineno])
    scenario = (GATE_DIR / "qualification" / "macos_native_dialogs.py").read_text(encoding="utf-8")
    assert 'route == "default-button" and respond == "return"' in scenario and 'answered.get("app_active") is False' in scenario
    assert '.get("via") == "defaultButtonCell"' in scenario


def test_the_contact_sheet_indexes_every_picture(tmp_path):
    entries = []
    for name in ("one", "two", "three"):
        path, record = _picture(tmp_path / "shots", name=name)
        entries.append({"path": f"shots/{path.name}", "record": record, "review": vr.review(path, record)})
    sheet = vr.contact_sheet(entries, tmp_path, title="t")
    assert sheet == {"index": "index.html", "sheet": "contact-sheet.png", "pictures": 3, "thumbnails": 3}
    text = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert all(f"shots/{name}.png" in text for name in ("one", "two", "three"))


# --------------------------------------------------------------------------- #
#  The darwin judge with the revised evidence
# --------------------------------------------------------------------------- #
def _entry(**extra) -> dict:
    return {"id": ID, "status": "PASS", "reason": "", "tool": "mp3-tool", "tier": "journey", "layers": ["native", "media"],
            "checks": [{"name": "a check", "ok": True}], "native_inputs": 4, "sessions": ["app"],
            "fixtures": [{"id": "f", "kind": "generated", "validation": [{"ok": True}]}],
            "outputs": [{"name": "o.mp3", "sha256": "x", "bytes": 10}], "notes": {"exits": []},
            "screenshots": [{"name": "ready.png", "path": f"{ID}/screenshots/ready.png"}], **extra}


def _actions(evidence: Path, *lines: dict) -> None:
    folder = evidence / ID
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "app-actions.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")


GOOD_DIALOG = {"kind": "input", "action": "file dialog", "title": "Select MP3 files", "dialog_kind": "askopenfilenames", "stand_in": True,
               "options": {"title": "Select MP3 files", "filetypes": "(('MP3 files', '*.mp3'),)"}}


def _judge(tmp_path, entry, *, evidence_list=("journey-checks", "real-screenshots", "dialog-contract"), actions=(GOOD_DIALOG,),
           picture=None, runtime_after=None, sha=SHA, tier=None):
    evidence = tmp_path / "evidence"
    _actions(evidence, *actions)
    if picture is not False:
        path, record = _picture(evidence / ID / "screenshots", name="ready", **(picture or {}))
    darwin_map = {ID: {"class": "automated", "journey": ID, "evidence": list(evidence_list)}}
    report = {"schema_version": 1, "token": "t", "finished": True, "scenarios": [entry], "registered": [ID],
              "runtime_before": {"x": 1}, "runtime_after": runtime_after or {"x": 1}}
    (tmp_path / "acceptance.json").write_text(json.dumps(report))
    return ar.judge_darwin(tmp_path / "acceptance.json", token="t", wanted=[ID], required=[ID], optional=[], evidence_root=evidence,
                           returncode=0, ended="exited", darwin_map=darwin_map, manual_evidence=None, sha=sha)


def test_a_journey_with_real_pictures_and_its_dialog_contract_passes(tmp_path):
    judged = _judge(tmp_path, _entry())
    assert judged.status == "PASS", judged.detail
    assert judged.scenarios[0]["requirement"] == "AUTOMATED PASS" and judged.candidates, judged.scenarios


@pytest.mark.parametrize("damage, words", [
    ("no screenshot", "no picture of the real window"),
    ("not captured", "was not captured"),
    ("another sha", "this run is of"),
    ("failed inspection", "review FAIL"),
    ("no provenance", "no provenance record"),
    ("dialog without options", "recorded no options"),
    ("open dialog without file types", "given no file types"),
    ("no dialog at all", "answered no file or folder dialog"),
    ("no output", "no inspected output"),
    ("failed check", "failed checks"),
    ("orphan at exit", "not clean"),
    ("unexpected output outside the run", "default output folder changed"),
])
def test_missing_or_false_evidence_is_never_a_pass(tmp_path, damage, words):
    entry, kwargs = _entry(), {}
    if damage == "no screenshot":
        entry["screenshots"], kwargs["picture"] = [], False
    elif damage == "not captured":
        kwargs["picture"] = {"captured": False, "why": "the window server returned no image"}
    elif damage == "another sha":
        kwargs["picture"] = {"sha": "c" * 40}
    elif damage == "failed inspection":
        kwargs["picture"] = {"audit": {"widgets": 3, "window_points": [400, 300], "probes": [], "outside": [], "contrast": [],
                                       "overlaps": [{"first": ".a", "second": ".b", "area": 99}], "clipped": []}}
    elif damage == "no provenance":
        kwargs["picture"] = False
        folder = tmp_path / "evidence" / ID / "screenshots"
        folder.mkdir(parents=True)
        _picture(folder, name="ready")
        (folder / "ready.json").unlink()
    elif damage == "dialog without options":
        kwargs["actions"] = ({**GOOD_DIALOG, "options": {}},)
    elif damage == "open dialog without file types":
        kwargs["actions"] = ({**GOOD_DIALOG, "options": {"title": "Select MP3 files"}},)
    elif damage == "no dialog at all":
        kwargs["actions"] = ({"kind": "input", "action": "click"},)
    elif damage == "no output":
        entry["outputs"] = []
    elif damage == "failed check":
        entry["checks"] = [{"name": "x", "ok": False}]
    elif damage == "orphan at exit":
        entry.update(tier="shutdown", layers=["native", "shutdown"],
                     notes={"exits": [{"exit_status": 0, "orphans": [{"pid": 9, "image": "ffmpeg"}], "windows_after": []}]})
    elif damage == "unexpected output outside the run":
        kwargs["runtime_after"] = {"x": 2}
    judged = _judge(tmp_path, entry, **kwargs)
    assert judged.status == "FAIL" and words in judged.detail, judged.detail
    if damage not in ("unexpected output outside the run",):
        assert judged.scenarios[0]["requirement"] == "AUTOMATED FAIL"


def test_the_map_refuses_a_counterpart_without_evidence_or_with_unknown_evidence():
    required = [ID]
    assert any("names no evidence list" in p for p in ar.darwin_map_problems({ID: {"class": "automated", "journey": ID}}, required, []))
    assert any("unknown evidence" in p for p in ar.darwin_map_problems(
        {ID: {"class": "automated", "journey": ID, "evidence": ["journey-checks", "a-signature"]}}, required, []))
    assert ar.darwin_map_problems({ID: {"class": "automated", "journey": ID, "evidence": ["journey-checks"]}}, required, []) == []


# --------------------------------------------------------------------------- #
#  The real policy
# --------------------------------------------------------------------------- #
#: A completed counterpart that opens no file or folder dialog (its confirmation is the application's own window).
ANSWERS_NO_FILE_DIALOG = {"setup.clear-downloaded-data", "setup.first-run-choices-and-cancel"}
#: P5-E made setup.clear-downloaded-data, and P5-F-R1 setup.first-run-choices-and-cancel (Cancel before Begin Setup), automated
#: counterparts; P5-G closed the last one: nothing is pending on P5 any more.
STILL_PENDING_ON_P5: set = set()
#: P5-G (owner exception, 2026-11-18): a later-phase journey mapped NOT APPLICABLE ON MACOS under its own reviewed reason.
PLATFORM_EXCEPTIONS = {"setup.first-run-refuses-a-folder-too-deep": "windows-only-installation-path-limit"}


def test_no_automated_journey_waits_on_an_owner_signature_and_each_names_its_evidence():
    darwin = ACCEPTANCE["darwin_map"]
    assert ar.darwin_map_problems(darwin, ACCEPTANCE["required_scenarios"], ACCEPTANCE["optional_scenarios"]) == []
    assert not [sid for sid, entry in darwin.items() if entry.get("manual")]
    for sid in FORMERLY_MANUAL:
        evidence = darwin[sid]["evidence"]
        assert "journey-checks" in evidence and "real-screenshots" in evidence, sid
        if not sid.startswith(("launcher.six-tools", "launcher.settings")):
            assert "dialog-contract" in evidence, sid
    later_phase_prefixes = ("tts.", "shutdown.tts-", "setup.")
    pending = {sid for sid, entry in darwin.items() if entry.get("pending_phase")}
    # Nothing is pending any more; moving one back into this set is a deliberate edit here.
    assert pending == STILL_PENDING_ON_P5, "later phases stay NOT RUN, and only those"
    assert all(darwin[sid]["pending_phase"] == "P5" for sid in pending)
    for sid in pending:
        assert sid.startswith("setup."), sid
    # Every scenario of those later-phase families that is NOT pending has completed: it must carry full automated evidence.
    for sid, reason in PLATFORM_EXCEPTIONS.items():
        assert darwin[sid]["class"] == "not-applicable" and darwin[sid]["reason_id"] == reason, sid
        assert darwin[sid]["qualification"] == "fresh-macos", sid
    for sid in (s for s in darwin if s.startswith(later_phase_prefixes) and s not in pending and s not in PLATFORM_EXCEPTIONS):
        entry = darwin[sid]
        assert entry["class"] == "automated" and not entry.get("manual"), sid
        if sid in ANSWERS_NO_FILE_DIALOG:  # dialog-contract would fail it by construction (acceptance_report); named exactly
            assert entry["evidence"] == ["journey-checks", "real-screenshots"], sid
        else:
            assert {"journey-checks", "real-screenshots", "dialog-contract"} <= set(entry["evidence"]), sid


def test_the_darwin_scenarios_have_runners_and_whole_pass_requirements():
    verify = load_gate("act_verify_closeout")
    scenarios = POLICY["darwin_scenarios"]
    assert set(scenarios) == set(verify.DARWIN_SCENARIO_NAMES)
    for name in ("macos-native-dialogs", "macos-visual", "macos-kx10"):
        entry = scenarios[name]
        assert (GATE_DIR / entry["runner"]).is_file() and entry["network"] == [], name
        requires = entry["pass_requires"]
        assert requires["checks"] >= 12 and requires["runs"] >= 1 and requires["names"] and requires["families"], name
    assert "REAL CLEAN" in scenarios["fresh-macos"]["evidence_classes"] and "runner" not in scenarios["fresh-macos"]


def test_a_darwin_scenario_verdict_short_of_its_requirements_is_not_accepted(tmp_path):
    verify = load_gate("act_verify_closeout_q")
    requires = POLICY["darwin_scenarios"]["macos-kx10"]["pass_requires"]
    folder = tmp_path / "q"
    folder.mkdir()
    (folder / "identity.json").write_text(json.dumps({"scenario": "macos-kx10", "head": SHA}))
    (folder / "runs.json").write_text(json.dumps([{"label": "kx10.maker-sigkill"}]))
    verdict = {"scenario": "macos-kx10", "status": "PASS", "runs": 1,
               "checks": [{"name": "kx10 / the encoder was running when the application was killed", "status": "PASS"}]}
    problems = verify.scenario_evidence_problems("macos-kx10", verdict, folder, SHA, requires)
    assert any("required checks are missing" in p for p in problems) and any("checks named 'kx10 / '" in p for p in problems)
    assert verify.scenario_evidence_problems("macos-kx10", verdict, folder, "d" * 40, requires), "another HEAD is refused"


def test_the_p1b_ledger_covers_every_former_checklist_item_and_names_its_evidence():
    block = POLICY["darwin_p1b"]
    kinds = {"journeys", "tests", "scenario", "owner-visual", "blocked-permission", "approved-exception", "later-phase",
             "not-applicable"}
    ids = {item["id"] for item in block["requirements"]}
    for item in block["requirements"]:
        assert item["kind"] in kinds and item["what"], item
        if item["kind"] == "tests":
            assert all((REPO_ROOT / test).is_file() for test in item["tests"]), item["id"]
        if item["kind"] == "scenario":
            assert item["scenario"] in POLICY["darwin_scenarios"], item["id"]
        if item["kind"] in ("blocked-permission", "approved-exception"):
            assert "Accessibility" in item["permission"], item["id"]
        if item["kind"] == "approved-exception":
            assert item["issue"] and item["decided"] and item["revisit"] and item["scope"], item["id"]
        if item["kind"] == "later-phase":
            assert item["phase"], item["id"]
    assert set(block["checklist_map"]) == {
        "macos-checklist:native-dialogs", "macos-checklist:appearance", "macos-checklist:retina-geometry", "macos-checklist:scrolling",
        "macos-checklist:finder-reveal", "macos-checklist:focus-dock-menu", "macos-checklist:terminal-autoclose",
        "macos-checklist:five-tools", "kx10:force-quit-maker"}
    for text in block["checklist_map"].values():
        named = {word.strip(" ,;:()") for word in text.split()}
        assert named & ids, text
    assert {"fresh-macos", "native-panel-selection", "owner-visual-dark", "kx10"} <= ids


def test_act72_080_is_an_approved_exception_that_stays_unverified():
    """The owner's decision of 2026-11-15: P1B may close without the privacy grants needed to automate a selection inside the
    native file picker. The selection stays UNVERIFIED and the record says who decided, the issue and when it is revisited."""
    entry = next(item for item in POLICY["darwin_p1b"]["requirements"] if item["id"] == "native-panel-selection")
    assert entry["kind"] == "approved-exception" and entry["issue"] == "ACT72-080"
    assert entry["decided"].startswith("2026-11-15") and "Decisions.md" in entry["decided"]
    assert "P5" in entry["revisit"] and "P7" in entry["revisit"] and "not blanket" in entry["revisit"]
    assert "UNVERIFIED" in entry["scope"] and "never PASS" in entry["scope"]
    assert "APPROVED P1B EXCEPTION (ACT72-080, unverified)" in POLICY["darwin_p1b"]["checklist_map"]["macos-checklist:native-dialogs"]
    verify = load_gate("act_verify_exception_label")
    label = verify.approved_exception_label(entry)
    assert label.startswith("APPROVED P1B EXCEPTION - ACT72-080 UNVERIFIED (owner decision 2026-11-15")
    assert "PASS" not in label.replace("P1B", "")
    assert verify.approved_exception_label({**entry, "decided": ""}).startswith("BLOCKED"), (
        "an exception nobody is recorded as deciding is not accepted")


PASSING = ["AUTOMATED PASS", "AUTOMATED PASS (carried)", "OWNER VISUAL ACCEPTANCE (reported at 455bf833e681; application unchanged "
           "since)", "NOT RUN - LATER PHASE (P2)", "NOT APPLICABLE - JUSTIFIED"]
EXCEPTION = "APPROVED P1B EXCEPTION - ACT72-080 UNVERIFIED (owner decision 2026-11-15; revisit P5/P7)"


@pytest.mark.parametrize("other, outcome", [
    ("AUTOMATED FAIL", "FAIL"),
    ("BLOCKED - needs Accessibility", "BLOCKED"),
    ("NEEDS RERUN", "INCOMPLETE"),
    ("NOT RUN", "INCOMPLETE"),
    ("NEEDS RE-REVIEW - 9 application file(s) changed since the owner looked at 455bf833e681",
     "AWAITING THE OWNER'S VISUAL RE-REVIEW"),
])
def test_an_approved_exception_never_makes_another_requirement_pass(other, outcome):
    verify = load_gate("act_verify_outcome")
    assert verify.evidence_outcome(PASSING + [EXCEPTION, other])[0] == outcome
    assert verify.evidence_outcome(PASSING + [other])[0] == outcome, "the same verdict without the exception"


def test_the_outcome_names_an_approved_exception_and_is_never_plain_complete():
    verify = load_gate("act_verify_outcome_names")
    outcome, code = verify.evidence_outcome(PASSING + [EXCEPTION])
    assert outcome == "COMPLETE WITH 1 APPROVED P1B EXCEPTION(S) (ACT72-080: UNVERIFIED)"
    assert verify.evidence_outcome(PASSING) == ("COMPLETE", code)


def test_an_owner_visual_record_reopened_by_a_code_change_is_not_complete():
    """Regression: the outcome checked NEEDS RERUN and NOT RUN only, so NEEDS RE-REVIEW (the owner's visual acceptance
    re-opened by an application change) read as COMPLETE."""
    verify = load_gate("act_verify_outcome_rereview")
    outcome, code = verify.evidence_outcome(PASSING[:2] + ["NEEDS RE-REVIEW - 1 application file(s) changed"])
    assert outcome != "COMPLETE" and code != 0


# --------------------------------------------------------------------------- #
#  Incremental evidence (helpers/evidence_ledger.py)
# --------------------------------------------------------------------------- #
def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", "-c", "core.autocrlf=false", *args],
                          cwd=root, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "r"
    files = {"scripts/a.py": "VALUE = 1\n", "scripts/b.py": "import a\n", "scripts/c.py": "X = 3\n",
             "files/tests/conftest.py": "\n", "files/tests/test_a.py": "import a\n", "files/tests/test_b.py": "import b\n",
             "files/tests/test_c.py": "import c\n", "files/test-files/data.txt": "fixture\n", "md-instructions/Notes.md": "doc\n",
             "files/dev-work/verification-gate/verification.json": "{}\n"}
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "one")
    return root


POLICY_SMALL = {"changed": {"always": [], "no_selection": ["md-instructions/"],
                            "routes": {"files/dev-work/verification-gate/": ["files/tests/test_c.py"]}}}
TESTS = ["files/tests/test_a.py", "files/tests/test_b.py", "files/tests/test_c.py"]
ENV = {"python": "3.12.15", "tk": "9.0.4", "ffmpeg": "9.0.1"}


def test_the_owner_visual_record_carries_until_application_code_changes_and_owner_files_are_not_code(repo, monkeypatch):
    """Regression (b8e0c92): the owner's own untracked ``scripts/project-status.py``, which the policy names in
    ``changed.no_selection``, was read as an application change, so the owner's reported visual acceptance showed NEEDS
    RE-REVIEW with no application file changed. A real application change must still invalidate it."""
    verify = load_gate("act_verify_owner_visual")
    monkeypatch.setattr(verify, "REPO_ROOT", repo)
    sha = _git(repo, "rev-parse", "HEAD")
    folder = repo / "files" / "dev-work" / "macos-acceptance" / "evidence" / sha
    folder.mkdir(parents=True)
    (folder / "owner-visual-acceptance.json").write_text(json.dumps({"sha": sha, "code_sha": sha}), encoding="utf-8")
    policy = {"changed": {"no_selection": ["md-instructions/", "scripts/project-status.py"]}, "darwin_p1b": {}}
    assert verify._owner_visual_status(policy, ledger.blob_map(repo)).startswith("OWNER VISUAL ACCEPTANCE (reported at")
    (repo / "scripts" / "project-status.py").write_text("print('the owner')\n", encoding="utf-8")
    (repo / "md-instructions" / "Notes.md").write_text("changed\n", encoding="utf-8")
    assert verify._owner_visual_status(policy, ledger.blob_map(repo)).startswith("OWNER VISUAL ACCEPTANCE (reported at")
    (repo / "scripts" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert verify._owner_visual_status(policy, ledger.blob_map(repo)).startswith("NEEDS RE-REVIEW - 1 application file(s)")
    (folder / "owner-visual-acceptance.json").unlink()
    assert verify._owner_visual_status(policy, ledger.blob_map(repo)).startswith("NOT RUN - no owner visual record")


@pytest.fixture(autouse=True)
def _synthetic_runs_are_admissible(monkeypatch):
    """These runs are hand-made, not sealed by the gate; the admission rule itself is tested on its own below."""
    monkeypatch.setattr(ledger, "admissible", lambda folder: (json.loads((folder / "results.json").read_text())["lifecycle"] == "completed", ""))


def test_a_run_the_gate_would_not_read_back_is_not_evidence(tmp_path, monkeypatch):
    monkeypatch.undo()
    folder = tmp_path / "2026-01-01_000000_focused_aaaa"
    folder.mkdir()
    (folder / "results.json").write_text(json.dumps({"run_id": folder.name, "lifecycle": "completed", "status": "PASS", "seal": "forged"}))
    valid, why = ledger.admissible(folder)
    assert not valid and why
    runs, skipped = ledger.load_runs(tmp_path, [tmp_path])
    assert runs == [] and skipped and "not admissible" in skipped[0]


def _run(root: Path, outputs: Path, name: str, outcomes: dict, *, record=True, environment=ENV, dirty=False) -> Path:
    folder = outputs / name
    (folder / "reports").mkdir(parents=True)
    head = _git(root, "rev-parse", "HEAD")
    (folder / "results.json").write_text(json.dumps({"run_id": name, "lifecycle": "completed", "status": "PASS", "started_at": name,
                                                     "environment": environment, "checks": []}))
    (folder / "start.json").write_text(json.dumps({"identity": {"head": head, "dirty_tracked": [" M x"] if dirty else [],
                                                                "untracked_in_scope": []}, "environment": environment}))
    if record:
        (folder / ledger.FILES_NAME).write_text(json.dumps(ledger.blob_map(root)))
    cases = "".join(
        f'<testcase classname="files.tests.{Path(test).stem}" name="t">' + ("<failure/>" if outcome == "FAIL" else "") + "</testcase>"
        for test, outcome in outcomes.items())
    (folder / "reports" / "pytest.xml").write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>")
    return folder


def _assess(root: Path, outputs: Path, *, environment=ENV, tests=TESTS) -> dict:
    runs, _ = ledger.load_runs(root, [outputs])
    items = ledger.build_items(root, POLICY_SMALL, tests=tests)
    head = _git(root, "rev-parse", "HEAD")
    current = ledger.blob_map(root)
    return {item.id.rsplit("/", 1)[-1]: ledger.assess(item, runs, current, head, environment, POLICY_SMALL) for item in items}


def test_unchanged_evidence_is_current_and_a_change_invalidates_only_what_imports_it(repo, tmp_path):
    outputs = tmp_path / "outputs"
    _run(repo, outputs, "2026-01-01_000000_focused_aaaa", {test: "PASS" for test in TESTS})
    assert {name: entry["status"] for name, entry in _assess(repo, outputs).items()} == {
        "test_a.py": ledger.CURRENT, "test_b.py": ledger.CURRENT, "test_c.py": ledger.CURRENT}
    (repo / "scripts" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")
    found = _assess(repo, outputs)
    assert found["test_a.py"]["status"] == ledger.RERUN and found["test_a.py"]["changed"] == ["scripts/a.py"]
    assert found["test_b.py"]["status"] == ledger.RERUN, "b imports a: the change reaches it through the closure"
    assert found["test_c.py"]["status"] == ledger.CARRIED, "c does not import a: its evidence carries, with its SHA"
    assert found["test_c.py"]["run_sha"] == _git(repo, "rev-parse", "HEAD")


def test_a_change_to_a_leaf_module_reaches_only_its_importers(repo, tmp_path):
    outputs = tmp_path / "outputs"
    _run(repo, outputs, "2026-01-01_000000_focused_aaaa", {test: "PASS" for test in TESTS})
    (repo / "scripts" / "b.py").write_text("import a\nY = 1\n", encoding="utf-8")
    found = _assess(repo, outputs)
    assert [found[name]["status"] for name in ("test_a.py", "test_b.py", "test_c.py")] == [ledger.CARRIED, ledger.RERUN, ledger.CARRIED]


@pytest.mark.parametrize("path, text, expected", [
    ("md-instructions/Notes.md", "edited doc\n", {"test_a.py": "carried", "test_b.py": "carried", "test_c.py": "carried"}),
    ("files/test-files/data.txt", "other fixture\n", {"test_a.py": "rerun", "test_b.py": "rerun", "test_c.py": "rerun"}),
    ("files/tests/conftest.py", "# changed\n", {"test_a.py": "rerun", "test_b.py": "rerun", "test_c.py": "rerun"}),
    ("files/dev-work/verification-gate/verification.json", '{"x": 1}\n', {"test_a.py": "carried", "test_b.py": "carried", "test_c.py": "rerun"}),
], ids=["a document reaches nothing", "an unbounded data change reaches everything", "shared test infrastructure reaches everything",
        "a routed gate file reaches its self-tests"])
def test_non_python_changes_follow_the_policy_and_widen_when_unbounded(repo, tmp_path, path, text, expected):
    outputs = tmp_path / "outputs"
    _run(repo, outputs, "2026-01-01_000000_focused_aaaa", {test: "PASS" for test in TESTS})
    (repo / path).write_text(text, encoding="utf-8")
    found = _assess(repo, outputs)
    names = {ledger.CARRIED: "carried", ledger.CURRENT: "carried", ledger.RERUN: "rerun"}
    assert {name: names[entry["status"]] for name, entry in found.items()} == expected, found


def test_failures_missing_runs_environment_and_unreconstructable_trees_never_count_as_passed(repo, tmp_path):
    outputs = tmp_path / "outputs"
    _run(repo, outputs, "2026-01-01_000000_focused_aaaa", {"files/tests/test_a.py": "FAIL", "files/tests/test_b.py": "PASS"})
    found = _assess(repo, outputs)
    assert found["test_a.py"]["status"] == ledger.FAIL and found["test_c.py"]["status"] == ledger.NOT_RUN
    assert _assess(repo, outputs, environment={**ENV, "ffmpeg": "9.1"})["test_b.py"]["status"] == ledger.RERUN
    dirty = tmp_path / "dirty-outputs"
    _run(repo, dirty, "2026-01-02_000000_focused_bbbb", {"files/tests/test_b.py": "PASS"}, record=False, dirty=True)
    assert _assess(repo, dirty)["test_b.py"]["status"] == ledger.RERUN
    clean = tmp_path / "clean-outputs"
    _run(repo, clean, "2026-01-03_000000_focused_cccc", {"files/tests/test_b.py": "PASS"}, record=False)
    assert _assess(repo, clean)["test_b.py"]["status"] == ledger.CURRENT, "a clean legacy run is rebuilt from its commit"
    assert ledger.worst([ledger.CURRENT, ledger.NOT_RUN]) == ledger.NOT_RUN
    assert ledger.worst([ledger.CARRIED, ledger.RERUN, ledger.CURRENT]) == ledger.RERUN


def test_the_latest_run_decides_and_the_rerun_plan_names_exactly_what_is_not_current(repo, tmp_path):
    outputs = tmp_path / "outputs"
    _run(repo, outputs, "2026-01-01_000000_focused_aaaa", {test: "FAIL" for test in TESTS})
    _run(repo, outputs, "2026-01-02_000000_focused_bbbb", {"files/tests/test_a.py": "PASS"})
    (repo / "scripts" / "c.py").write_text("X = 4\n", encoding="utf-8")
    found = _assess(repo, outputs)
    assert found["test_a.py"]["status"] == ledger.CARRIED and found["test_a.py"]["run"] == "2026-01-02_000000_focused_bbbb"
    assert found["test_b.py"]["status"] == ledger.FAIL
    plan = ledger.rerun_plan(list(found.values()), "macos")
    assert plan == ["files/dev-work/verification-gate/verify.py --mode focused --platform macos "
                    "--test files/tests/test_b.py --test files/tests/test_c.py"]
