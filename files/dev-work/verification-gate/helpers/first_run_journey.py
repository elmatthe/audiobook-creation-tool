"""What ``setup.first-run-choices-and-cancel`` judges on macOS, as pure functions (v0.8.0 P5-F, macOS counterpart).

The journey (``journeys/setup.py``) opens the real first-run window of a disposable copy and cancels it before Begin Setup; everything
it decides about isolation, the roster the window shows, what a click changed, the window's geometry, what the process did and what
changed on disk is decided here, from facts it gathered, so the same rules are held to negative controls in
``files/tests/test_macos_p5_first_run_choices.py`` without a desktop.

  * :func:`isolation_problems` -- before anything is launched: the copy's own code says its root and every folder setup would write
    are the copy's, the interpreter is the app's own base Python outside the copy and every real cleanup target, and the copy holds no
    link at all.
  * :func:`roster_problems` / :func:`selection_problems` / :func:`unrelated_problems` -- what the window shows (exactly Kokoro and
    OmniVoice, Kokoro ticked, the approved estimates and descriptions, the OmniVoice licensing disclosure, nothing about an engine a
    Mac does not offer) and what a click changed (the one box, and nothing else).
  * :func:`geometry_problems` / :func:`text_clip_problems` -- at one window size, every control and every description is wholly
    inside the window, nothing overlaps, and every label has the room its text asked for (no line cut at an edge).
  * :func:`activity_problems`, :func:`exit_problems`, :func:`leftover_problems` -- no install, folder, launch, connection or child
    process; the cancellation status, distinct from success and from failure; no window, worker, helper or group left.
  * :func:`outcome_problems` -- the copy is byte-identical but for one dated setup log, and nothing of an installation exists.
  * :func:`entry_problems` -- a PASS the journey reports must carry every named check and every named picture.

The helpers shared with the cleanup counterpart (digests, links, protected locations) are ``helpers/cleanup_journey.py``'s own.
Nothing here starts a process other than the copy's own read-only probe, or reads outside the paths it is handed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from helpers.cleanup_journey import _inside, _reaches, _same, content_digest, find_links, protected_locations, protected_state, tree_problems

__all__ = ["APPROVED", "CANCELLED_STATUS", "REQUIRED_CHECKS", "REQUIRED_PICTURES", "activity_problems", "content_digest", "copy_facts",
           "entry_problems", "exit_problems", "find_links", "geometry_problems", "isolation_problems", "leftover_problems",
           "outcome_problems", "protected_locations", "protected_state", "roster_findings", "roster_problems", "selection_problems", "text_clip_problems", "tree_problems",
           "unrelated_problems", "window_signature"]

#: The first-run roster a Mac offers, as the owner approved it (P4C, 2026-11-16: Kokoro checked, OmniVoice unchecked; recorded in
#: ``files/dev-work/macos-p4c/smoke/wizard-record.json``). Kept here on purpose, not read from bootstrap: this is what the window must
#: show, checked against what it does. A change to an estimate or a description is a deliberate edit here, with the owner's approval.
APPROVED = (
    {"component": "kokoro", "label": "Kokoro voices", "estimate": "344.7 MB", "default": True,
     "note_has": ("Natural English voices", "this computer"), "note_lacks": ("NVIDIA", "Windows")},
    {"component": "omnivoice", "label": "OmniVoice — Six Cloned Voices", "estimate": "3.5 GB", "default": False,
     "note_has": ("Apple Silicon", "NON-COMMERCIAL", "CC-BY-NC", "audio tokenizer has its own licence",
                  "full terms are shown before anything is downloaded"), "note_lacks": ("NVIDIA", "Windows")},
)
#: Nothing in the window may name an engine, or a platform, that a Mac does not offer here.
ABSENT_WORDS = ("chatterbox", "qwen", "nvidia", "windows")
#: ``setup_exit_code``: 0 completed, 1 failed (or closed mid-install), 2 closed before Begin Setup. The journey expects the last.
CANCELLED_STATUS = 2
#: The only thing the window may write into the copy: its own dated setup log (opened on first use; none is needed to cancel).
SETUP_LOG = re.compile(r"^files/runtime-data/logs/setup_\d{4}-\d{2}-\d{2}\.log$")
#: What the log may say. A cancelled setup never reaches a step, so nothing here may name one.
LOG_FORBIDDEN = ("pip install", "Creating the private", "Downloading", "Installing", "Collecting", "ffmpeg download", "SHA-256 verified")
#: Entries whose appearance would mean an installation, or any application state, began.
INSTALL_MARKS = (".venv", "files/bin", "files/runtime-data/python", "files/runtime-data/python-packages", "files/runtime-data/models",
                 "files/runtime-data/nltk_data", "files/runtime-data/optional-setup", "files/runtime-data/omnivoice",
                 "files/runtime-data/qwen3", "files/runtime-data/settings.json", "files/runtime-data/ffmpeg-state.json")
#: What the record of the window may hold: it started, and it exited. Anything else is an action the journey never authorized.
ALLOWED_EVENTS = ("started", "exit")

#: What a PASS must show, by a word each name contains (each must be there and ok), and the pictures it must carry.
REQUIRED_CHECKS = ("isolation preflight", "the real first-run window", "exactly two choices", "approved estimates", "licensing disclosure",
                   "no engine a Mac does not offer", "default", "a real click changes", "restored to their defaults",
                   "wholly on screen", "no text is cut", "Cancel before Begin Setup", "cancelled, not failed", "nothing was started",
                   "no owned process", "copy is byte-identical", "second installation", "real checkout")
REQUIRED_PICTURES = ("first-run-choices", "first-run-both-ticked", "first-run-660x600", "first-run-760x680", "first-run-900x700")


# --------------------------------------------------------------------------------------------------------------------- #
#  The copy's own word, before anything runs
# --------------------------------------------------------------------------------------------------------------------- #
_PROBE = r"""
import json, sys
root = sys.argv[1]
sys.path.insert(0, root + "/scripts")
import tkinter
from shared import bootstrap, engine_policy
facts = {
    "platform": sys.platform, "probe_interpreter": sys.executable, "probe_is_a_venv": sys.prefix != sys.base_prefix,
    "tk_version": tkinter.TkVersion, "repo_root": str(bootstrap.REPO_ROOT), "bootstrap_module": str(bootstrap.__file__),
    "mutable": {"virtual_environment": str(bootstrap.VENV_DIR), "portable_binaries": str(bootstrap.BIN_DIR),
                "runtime_data": str(bootstrap.RESOURCES_DIR), "logs": str(bootstrap.LOGS_DIR), "app_python": str(bootstrap.APP_PYTHON)},
    "choices": [[c, label, bool(default), note] for c, label, default, note in bootstrap.OPTIONAL_CHOICES],
    "estimates": bootstrap.optional_estimates(),
    "status": {"succeeded": bootstrap.setup_exit_code(started=True, done=True, ok=True),
               "failed": bootstrap.setup_exit_code(started=True, done=True, ok=False),
               "cancelled_before_begin": bootstrap.setup_exit_code(started=False, done=False, ok=False)},
    "cancelled_constant": bootstrap.EXIT_SETUP_CANCELLED,
    "offered": [c for c in ("kokoro", "chatterbox", "qwen3-customvoice", "qwen3-base", "omnivoice")
                if engine_policy.component_offered(c, "darwin")],
}
print(json.dumps(facts))
"""


def copy_facts(copy: Path, *, python: str | Path | None = None, env: dict | None = None) -> dict:
    """What the copy's own code says about where setup would write and what it would offer: run as a child on the interpreter the
    window will run on, reading only (``-I -B``: no bytecode, no environment). Raises on any failure."""
    done = subprocess.run([str(python or sys.executable), "-I", "-B", "-c", _PROBE, str(copy)], capture_output=True, text=True,
                          timeout=120, env=env, cwd=str(copy))
    if done.returncode != 0:
        raise RuntimeError(f"the copy's own probe failed ({done.returncode}): {done.stderr[-1500:]}")
    return json.loads(done.stdout.strip().splitlines()[-1])


#: Where each mutable path of the copy must be, relative to the copy (what ``bootstrap.py`` says its layout is).
MUTABLE = {"virtual_environment": ".venv", "portable_binaries": "files/bin", "runtime_data": "files/runtime-data",
           "logs": "files/runtime-data/logs", "app_python": "files/runtime-data/python/bin/python3.12"}


def isolation_problems(facts: dict, *, copy: Path, scratch: Path, real_root: Path, protected: dict[str, Path], interpreter: Path,
                       links: dict[str, str]) -> list[str]:
    """Every reason the copy is not provably the only installation the journey can make setup write into, or the window not provably
    running on the app's own interpreter. Empty means the journey may launch it. ``links`` is :func:`find_links` of the copy: a copy
    holds no link at all, so none can lead out of it."""
    problems: list[str] = []
    copy, scratch, real_root, interpreter = Path(copy), Path(scratch), Path(real_root), Path(interpreter)
    if facts.get("platform") != "darwin":
        problems.append(f"the window would run as {facts.get('platform')!r}, not as a Mac")
    if not _inside(scratch, copy):
        problems.append(f"the copy {copy} is not inside the gate's scratch {scratch}")
    if _reaches(real_root, scratch) or _reaches(real_root, copy) or _reaches(copy, real_root):
        problems.append(f"the copy {copy} or its scratch overlaps the real checkout {real_root}")
    if os.path.realpath(copy) != str(copy):
        problems.append(f"the copy's own path goes through a link ({copy} is really {os.path.realpath(copy)})")
    if not _same(facts.get("repo_root", ""), copy):
        problems.append(f"the copy's code says its root is {facts.get('repo_root')}, not {copy}")
    if not _same(facts.get("bootstrap_module", ""), copy / "scripts" / "shared" / "bootstrap.py"):
        problems.append(f"the setup code that would run is {facts.get('bootstrap_module')}, not the copy's own bootstrap.py")
    mutable = facts.get("mutable", {})
    for name, relative in MUTABLE.items():
        path = mutable.get(name)
        if not isinstance(path, str):
            problems.append(f"{name}: the copy's code named no folder ({path})")
            continue
        if not _same(path, copy / relative) or not _inside(copy, Path(path)):
            problems.append(f"{name}: {path} is not the copy's own {relative}")
        if os.path.realpath(path) != os.path.join(os.path.realpath(copy), *relative.split("/")):
            problems.append(f"{name}: {path} is reached through a link")
        if _reaches(real_root, Path(path)):
            problems.append(f"{name}: {path} is inside the real checkout")
        for label, real in protected.items():
            if _reaches(Path(path), real) or _reaches(real, Path(path)):
                problems.append(f"{name}: {path} reaches the real {label} ({real})")
    # The interpreter: the app's own base Python (where a first run runs, files/runtime-data/python), outside the copy and outside every
    # folder a cleanup or a setup could remove, and not a virtual environment.
    base = real_root / "files" / "runtime-data" / "python"
    if not interpreter.is_file():
        problems.append(f"the interpreter {interpreter} does not exist")
    if os.path.abspath(interpreter) != str(interpreter) or not str(interpreter).startswith(str(base) + os.sep):
        problems.append(f"the interpreter {interpreter} is not the app's own base Python under {base}")
    if _reaches(copy, interpreter):
        problems.append(f"the interpreter {interpreter} is inside the copy, which setup writes into")
    for key in ("environment", "portable_binaries", "models", "logs"):
        real = protected.get(key)
        if real is not None and _reaches(real, interpreter):
            problems.append(f"the interpreter {interpreter} is inside the real {key}, a cleanup target")
    for name, path in mutable.items():
        if isinstance(path, str) and _reaches(Path(path), interpreter):
            problems.append(f"the interpreter {interpreter} is inside {name} of the copy")
    if facts.get("probe_interpreter") != str(interpreter):
        problems.append(f"the copy's probe ran on {facts.get('probe_interpreter')}, not the interpreter the window will use")
    if facts.get("probe_is_a_venv"):
        problems.append("the interpreter is a virtual environment, which a first run never runs on")
    for relative, text in sorted(links.items()):
        problems.append(f"the copy holds a link before anything runs: {relative} -> {text}")
    return problems


# --------------------------------------------------------------------------------------------------------------------- #
#  What the window shows
# --------------------------------------------------------------------------------------------------------------------- #
def _row_notes(boxes: list[dict], labels: list[dict]) -> list[str]:
    """For each check box, the description label placed directly below it (the nearest one lower down, above the next box)."""
    notes = []
    for index, box in enumerate(boxes):
        below = [label for label in labels if label["y"] > box["y"] and (index + 1 == len(boxes) or label["y"] < boxes[index + 1]["y"])]
        notes.append(min(below, key=lambda label: label["y"])["text"] if below else "")
    return notes


def roster_findings(boxes: list[dict], labels: list[dict], *, facts: dict | None = None) -> dict[str, list[str]]:
    """``boxes`` and ``labels`` are what is on screen (each with ``text``, ``y``; a box with ``selected``). Exactly the approved
    macOS roster, in order, with its estimates, descriptions and licensing disclosure, and no word about anything else, by aspect:
    ``choices`` (which, how many, in what order), ``estimates``, ``defaults``, ``descriptions`` (including OmniVoice's licensing
    disclosure) and ``absent`` (a word about an engine or platform a Mac does not offer). ``facts`` (the copy's probe), when given,
    must agree with what the window shows."""
    found: dict[str, list[str]] = {"choices": [], "estimates": [], "defaults": [], "descriptions": [], "absent": []}
    boxes = sorted(boxes, key=lambda item: item["y"])
    if len(boxes) != len(APPROVED):
        found["choices"].append(f"the window offers {len(boxes)} voice choices, not {len(APPROVED)}: {[box['text'] for box in boxes]}")
    notes = _row_notes(boxes, labels)
    for index, approved in enumerate(APPROVED):
        if index >= len(boxes):
            found["choices"].append(f"the approved choice {approved['label']!r} is not offered")
            continue
        box, note = boxes[index], notes[index]
        if not box["text"].startswith(approved["label"]):
            found["choices"].append(f"choice {index + 1} reads {box['text']!r}, the approved roster says {approved['label']!r}")
        if not box["text"].endswith(f"(up to {approved['estimate']})"):
            found["estimates"].append(f"{approved['label']}: reads {box['text']!r}, the approved estimate is (up to {approved['estimate']})")
        if bool(box.get("selected")) is not approved["default"]:
            found["defaults"].append(f"{approved['label']} is {'ticked' if box.get('selected') else 'unticked'} by default; "
                                     f"the approved default is {'ticked' if approved['default'] else 'unticked'}")
        for phrase in approved["note_has"]:
            if phrase not in note:
                found["descriptions"].append(f"{approved['label']}: its description lacks {phrase!r}: {note[:160]!r}")
        for phrase in approved["note_lacks"]:
            if phrase.lower() in note.lower():
                found["descriptions"].append(f"{approved['label']}: its description names {phrase!r}, which a Mac does not have: {note[:160]!r}")
    shown = " ".join([box["text"] for box in boxes] + [label["text"] for label in labels]).lower()
    for word in ABSENT_WORDS:
        if word in shown:
            found["absent"].append(f"the window names {word!r}, which a Mac's first run does not offer")
    if facts is not None:
        components = [row[0] for row in facts.get("choices", [])]
        if components != [item["component"] for item in APPROVED]:
            found["choices"].append(f"the copy's own code offers {components}, not {[item['component'] for item in APPROVED]}")
        if facts.get("offered") != ["kokoro", "omnivoice"]:
            found["choices"].append(f"the copy's engine policy offers {facts.get('offered')} to a Mac")
        estimates = facts.get("estimates", {})
        for approved in APPROVED:
            if estimates.get(approved["component"]) != approved["estimate"]:
                found["estimates"].append(f"the copy's own estimate for {approved['component']} is {estimates.get(approved['component'])!r}, "
                                          f"not the approved {approved['estimate']!r}")
    return found


def roster_problems(boxes: list[dict], labels: list[dict], *, facts: dict | None = None) -> list[str]:
    """Every finding of :func:`roster_findings`, in one list."""
    return [line for lines in roster_findings(boxes, labels, facts=facts).values() for line in lines]


def selection_problems(observed: list[bool], expected: list[bool], *, step: str) -> list[str]:
    """After a click: the boxes are exactly as expected (the clicked one changed, the other did not)."""
    return [] if list(observed) == list(expected) else [f"{step}: the boxes read {list(observed)}, expected {list(expected)}"]


def window_signature(widgets: list[dict]) -> list[tuple]:
    """Everything on screen that a voice choice must not change: each widget's path, class, text, disabled flag and whether it is shown.
    A check box's ticked state is deliberately not in it: that is what a click is for."""
    return sorted((item["path"], item["class"], item.get("text", ""), bool(item.get("disabled")), bool(item.get("viewable")))
                  for item in widgets if item.get("viewable"))


def unrelated_problems(before: list[tuple], after: list[tuple], *, step: str) -> list[str]:
    """A click on a voice choice changed no other control: no widget appeared, vanished, was disabled or enabled, or changed its words."""
    if before == after:
        return []
    gone, new = [item for item in before if item not in after], [item for item in after if item not in before]
    return [f"{step}: unrelated controls changed; gone {[item[1:3] for item in gone[:4]]}, new {[item[1:3] for item in new[:4]]}"]


# --------------------------------------------------------------------------------------------------------------------- #
#  Geometry at one window size
# --------------------------------------------------------------------------------------------------------------------- #
def _box(item: dict) -> tuple[int, int, int, int]:
    return item["x"], item["y"], item["x"] + item["width"], item["y"] + item["height"]


def geometry_problems(window: dict, widgets: list[dict], *, size: tuple[int, int], tolerance: int = 1) -> list[str]:
    """At ``size``: the window is that size; every control (check box, button) and every text label shown is wholly inside it; each
    control can be used (shown, enabled); no two of them overlap. ``widgets`` are the viewable check boxes, buttons and labels."""
    problems: list[str] = []
    if abs(window["width"] - size[0]) > tolerance or abs(window["height"] - size[1]) > tolerance:
        problems.append(f"the window is {window['width']}x{window['height']}, not {size[0]}x{size[1]}")
    left, top, right, bottom = window["x"], window["y"], window["x"] + window["width"], window["y"] + window["height"]
    controls = [item for item in widgets if item["class"] in ("TCheckbutton", "TButton")]
    if len(controls) < 4:
        problems.append(f"only {len(controls)} controls are on screen (two voice choices, Begin Setup and Cancel are expected)")
    for item in widgets:
        x0, y0, x1, y1 = _box(item)
        if item["width"] <= 1 or item["height"] <= 1:
            problems.append(f"{item.get('text', '')[:28]!r} has no size")
        elif x0 < left or y0 < top or x1 > right or y1 > bottom:
            problems.append(f"{item.get('text', '')[:28]!r} ({item['class']}) reaches outside the window: {_box(item)} in {(left, top, right, bottom)}")
        if item["class"] in ("TCheckbutton", "TButton") and (not item.get("viewable") or item.get("disabled")):
            problems.append(f"{item.get('text', '')[:28]!r} cannot be used (shown={item.get('viewable')}, disabled={item.get('disabled')})")
    for index, first in enumerate(widgets):
        for second in widgets[index + 1:]:
            a, b = _box(first), _box(second)
            if min(a[2], b[2]) - max(a[0], b[0]) > tolerance and min(a[3], b[3]) - max(a[1], b[1]) > tolerance:
                problems.append(f"{first.get('text', '')[:24]!r} overlaps {second.get('text', '')[:24]!r}")
    return problems


def text_clip_problems(labels: list[dict], *, tolerance: int = 1) -> list[str]:
    """Each label got the room its text asked for. ``labels`` carry what a label asked for (``reqwidth``, ``reqheight``: the widest line
    and the lines it laid out) and what it got (``width``, ``height``). A label given less width than its widest line loses the end of
    that line at its right edge; given less height, it loses a line. The picture review judges a wrapped label on height only, so a line
    cut at the right edge (a licence sentence at the window's minimum size) is found here and nowhere else."""
    problems = []
    for label in labels:
        short_by_width, short_by_height = label["reqwidth"] - label["width"], label["reqheight"] - label["height"]
        if short_by_width > tolerance:
            problems.append(f"{label['text'][:36]!r} asked for {label['reqwidth']} px and got {label['width']}: the end of its widest line "
                            f"is cut by {short_by_width} px (wrap at {label.get('wraplength')})")
        if short_by_height > tolerance:
            problems.append(f"{label['text'][:36]!r} asked for {label['reqheight']} px of height and got {label['height']}: "
                            f"a line is cut by {short_by_height} px")
    return problems


# --------------------------------------------------------------------------------------------------------------------- #
#  What the process did
# --------------------------------------------------------------------------------------------------------------------- #
def activity_problems(events: list[dict], children: list[dict]) -> list[str]:
    """No base environment, optional voice, model, repair, package download or launch: the window's own record holds only that it
    started and that it exited, and it never started a child process."""
    problems: list[str] = []
    kinds = [event.get("kind") for event in events]
    for event in events:
        if event.get("kind") not in ALLOWED_EVENTS:
            problems.append(f"the window recorded {event.get('kind')!r}: {json.dumps({k: v for k, v in event.items() if k != 'at'})[:160]}")
    if kinds.count("started") != 1 or kinds.count("exit") != 1:
        problems.append(f"the window's record is {kinds}, expected one start and one exit")
    for child in children:
        problems.append(f"the window started a child process: {child.get('program')} (pid {child.get('pid')})")
    return problems


def exit_problems(facts: dict, events: list[dict], *, status_map: dict | None = None, expected: int = CANCELLED_STATUS) -> list[str]:
    """The cancellation status, from the process itself and from production's own record of it, distinct from a completed installation
    (0) and from a failed setup (1)."""
    problems: list[str] = []
    if not facts.get("exited"):
        return ["the setup process did not exit"]
    status = facts.get("exit_status")
    if status != expected:
        problems.append(f"the process exited with status {status}, the cancellation status is {expected}")
    if status in (0, 1):
        problems.append(f"status {status} is the status of a {'completed installation' if status == 0 else 'failed setup'}, not a cancellation")
    recorded = [event.get("code") for event in events if event.get("kind") == "exit"]
    if recorded != [expected]:
        problems.append(f"the window's own record of its exit is {recorded}, expected {[expected]}")
    if status_map is not None:
        if len({status_map.get("succeeded"), status_map.get("failed"), status_map.get("cancelled_before_begin")}) != 3:
            problems.append(f"production's statuses are not distinct: {status_map}")
        if status_map.get("cancelled_before_begin") != expected:
            problems.append(f"production maps a cancel before Begin Setup to {status_map.get('cancelled_before_begin')}, not {expected}")
    return problems


def leftover_problems(facts: dict, *, still_running: list[int], occupied_groups: list[int], processes: list[str]) -> list[str]:
    """No window, owned process, worker, helper, process group or Tk call from a worker thread remains; no process anywhere has this
    copy's folder in its command line (``processes``, the kernel's own list, read once after the exit)."""
    problems: list[str] = []
    if facts.get("windows_after"):
        problems.append(f"a window remains: {facts['windows_after']}")
    if facts.get("orphans"):
        problems.append(f"an owned process remains: {facts['orphans']}")
    if still_running:
        problems.append(f"processes the window started still run: {still_running}")
    if occupied_groups or facts.get("groups_occupied"):
        problems.append(f"a process group the window owned is occupied: {occupied_groups or facts.get('groups_occupied')}")
    if facts.get("tk_off_thread"):
        problems.append(f"a worker thread called Tk: {facts['tk_off_thread'][:3]}")
    tail = facts.get("stderr_tail", "")
    if any(marker in tail for marker in ("Tcl_AsyncDelete", "Fatal Python error", "wrong thread", "Traceback")):
        problems.append(f"the process printed a fatal error: {tail[-300:]}")
    for line in processes:
        problems.append(f"a process still names the copy: {line[:200]}")
    return problems


# --------------------------------------------------------------------------------------------------------------------- #
#  What changed on disk
# --------------------------------------------------------------------------------------------------------------------- #
def outcome_problems(before: dict[str, str], after: dict[str, str], *, log_texts: dict[str, str] | None = None) -> list[str]:
    """The copy is byte-identical but for at most one dated setup log (the window's own), whose words name no step. Nothing of an
    installation exists. ``log_texts`` is the content of each new log, by relative name."""
    problems: list[str] = []
    for name, digest in sorted(before.items()):
        if name not in after:
            problems.append(f"an entry of the copy was removed: {name}")
        elif after[name] != digest:
            problems.append(f"an entry of the copy changed: {name}")
    new = sorted(set(after) - set(before))
    logs = [name for name in new if SETUP_LOG.match(name)]
    for name in new:
        if name in logs:
            continue
        if name.endswith("/") and after[name] == "dir" and any(log.startswith(name) for log in logs):
            continue  # the empty-looking parent of the log, which the digest names only while it is empty
        problems.append(f"something new appeared in the copy: {name}")
    if len(logs) > 1:
        problems.append(f"more than one setup log appeared: {logs}")
    for name in logs:
        text = (log_texts or {}).get(name)
        if text is None:
            problems.append(f"the new setup log {name} was not read")
            continue
        for word in LOG_FORBIDDEN:
            if word.lower() in text.lower():
                problems.append(f"the setup log {name} names a step ({word!r}): {text[-200:]!r}")
    for mark in INSTALL_MARKS:
        if any(name == mark or name.startswith(mark + "/") for name in after):
            problems.append(f"{mark} exists in the copy: an installation or application state began")
    return problems


# --------------------------------------------------------------------------------------------------------------------- #
#  A reported PASS must carry its evidence
# --------------------------------------------------------------------------------------------------------------------- #
def entry_problems(entry: dict) -> list[str]:
    """What the journey's report entry must hold for the PASS to stand: every named check present and ok, and every named picture
    captured. The acceptance judge re-reads the pictures themselves; this is what the journey must have done at all."""
    problems: list[str] = []
    checks = entry.get("checks", [])
    for needle in REQUIRED_CHECKS:
        matching = [check for check in checks if needle in check.get("name", "")]
        if not matching:
            problems.append(f"no check names {needle!r}")
        elif not all(check.get("ok") for check in matching):
            problems.append(f"a check naming {needle!r} failed: {[c['name'] for c in matching if not c.get('ok')][:2]}")
    shots = {shot.get("name"): shot for shot in entry.get("screenshots", [])}
    for name in REQUIRED_PICTURES:
        shot = shots.get(f"{name}.png")
        if shot is None:
            problems.append(f"no picture {name}")
        elif not shot.get("captured") or shot.get("review") != "PASS":
            problems.append(f"picture {name} was not captured or did not pass review: {shot.get('review')}")
    return problems
