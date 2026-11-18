"""Setup journeys: the real first-run window, and Clear Downloaded Data from the click to the next launch (v0.7.2 Phase 8, ACT72-055).

Each runs a **disposable copy** of the application: the committed ``scripts/`` tree and the root files, as an extracted download has
them. The application takes every folder it owns from where its own code is, so the copy is the only installation a journey here can
create, refuse, log into or delete from. This checkout's environment, FFmpeg, models and settings are never the target, and the
runner's own before-and-after digest of the real ``files/runtime-data`` holds every journey to that.

  * ``setup.first-run-refuses-a-folder-too-deep``: the real first-run window with the real ``run_setup``. The copy sits in a folder
    whose path is too long for Windows, which is the product's own reason to refuse, so the failure is real and nothing is scripted:
    Begin Setup, the native "Setup did not complete" box, Open log folder, Close, exit status 1, and nothing installed.
  * ``setup.first-run-choices-and-cancel``: the five voice choices as the window really shows them (OmniVoice the fifth since v0.8.0),
    a choice changed by a real click, the window at its smallest size, then Cancel: exit status 2 and nothing created.
  * ``setup.clear-downloaded-data``: Preferences, the real dialog and its confirmation by real clicks; the application closes itself;
    the real helper process deletes exactly what was ticked, in the copy; the next launch shows the result once.

What these do not show: a real base installation (downloads; the ``fresh-windows`` qualification), display scaling other than this
desktop's, or macOS -- except ``setup.clear-downloaded-data``, which has a macOS counterpart (v0.8.0 P5): the same journey through the
in-process macOS driver on a disposable copy in a Mac's layout, held first to an isolation preflight computed by the copy's own code
(``helpers/cleanup_journey.py``; nothing is launched unless it passes) and judged on byte-level digests afterwards. The first-run
journeys stay Windows-only until their own P5 checkpoints.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from helpers import cleanup_journey
from helpers import scratch as scratch_store
from journeys.common import AppSession, Context, expect_clean_close, native, scenario, wait_until

GATE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = GATE_DIR.parents[2]
SETUP_LAUNCHER = GATE_DIR / "adapters" / "windows" / "setup_launcher.py"
ROOT_FILES = ("config.toml", "README.md", "Setup_and_Run-audiobook-creation-tool.bat")
SETUP_TITLE = "Audiobook Creation Tool — Setup"
#: The first-run window's five choices, in order, with the defaults the owner approved: Kokoro on, the rest off. OmniVoice is the
#: fifth (v0.8.0), off. Kept here on purpose, not read from bootstrap: this is what the window must show, checked against what it does.
#: (The path limits, by contrast, come from the copy's own bootstrap.app_path_limits() through the launcher's record.)
CHOICES = (("Kokoro voices", True), ("Chatterbox Turbo voices", False), ("Qwen3 CustomVoice voices (Aiden, Ryan)", False),
           ("Qwen3 Cloned Voices (six bundled voices)", False), ("OmniVoice — Six Cloned Voices", False))


def windows_units(path: Path) -> int:
    """A path's length as Windows counts it (UTF-16 code units: a character beyond U+FFFF counts twice), worked out here
    independently of the application's own long_paths.windows_length, which the launcher records."""
    return len(str(path).encode("utf-16-le")) // 2


# --------------------------------------------------------------------------- #
# The disposable copy
# --------------------------------------------------------------------------- #
def make_copy(root: Path) -> Path:
    """The committed application, as an extracted download has it: every tracked file under ``scripts/`` and the root files. Nothing
    untracked, no environment, no data. Made by this driver, below the scenario's Low-labelled scratch, so the application can write
    into it and into nothing else."""
    listed = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--", "scripts"], capture_output=True, check=True).stdout
    names = [name for name in listed.decode("utf-8").split("\0") if name]
    if len(names) < 100:
        raise RuntimeError(f"git listed only {len(names)} tracked files under scripts/")
    for name in [*names, *ROOT_FILES]:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / name, target)
    return root


def listing(root: Path) -> dict[str, int]:
    """Every file below ``root`` with its size; folders appear by their files, and an empty folder as ``name/``."""
    found: dict[str, int] = {}
    for folder, folders, files in os.walk(root):
        relative = Path(folder).relative_to(root)
        for name in files:
            found[(relative / name).as_posix()] = (Path(folder) / name).stat().st_size
        if not folders and not files and str(relative) != ".":
            found[relative.as_posix() + "/"] = 0
    return found


def read_record(path: Path) -> list[dict]:
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return []


# --------------------------------------------------------------------------- #
# Finding what a person sees
# --------------------------------------------------------------------------- #
def shown(session: AppSession, *, cls: str | None = None, toplevel: str | None = None) -> list[dict]:
    """Every widget on screen now, optionally of one class and one window, read on the application's own Tk thread."""
    return [item for item in session.client.call("tree")["widgets"]
            if item.get("viewable") and (cls is None or item["class"] == cls) and (toplevel is None or item.get("toplevel") == toplevel)]


def one(session: AppSession, cls: str, text: str, *, toplevel: str | None = None, prefix: bool = False) -> dict:
    matches = [item for item in shown(session, cls=cls, toplevel=toplevel)
               if (item.get("text", "").startswith(text) if prefix else item.get("text") == text)]
    if len(matches) != 1:
        raise native.InputRefused(f"{len(matches)} {cls} widgets read {text!r}; on screen: "
                                  f"{[item.get('text') for item in shown(session, cls=cls, toplevel=toplevel)]}")
    return matches[0]


def wait_for(session: AppSession, cls: str, text: str, *, timeout: float = 30, toplevel: str | None = None, prefix: bool = False) -> dict:
    def found():
        matches = [item for item in shown(session, cls=cls, toplevel=toplevel)
                   if (item.get("text", "").startswith(text) if prefix else item.get("text") == text)]
        return matches[0] if len(matches) == 1 else None

    return wait_until(found, timeout, f"a {cls} reading {text!r}")


def toplevel_window(session: AppSession, title: str, *, timeout: float = 20) -> tuple[int, str]:
    """An application window of its own (not a native message box), by its title: its handle, brought to the front, and its Tk path."""
    hwnd = wait_until(lambda: next((item["hwnd"] for item in native.windows_of(session.pid)
                                    if item["class"] == "TkTopLevel" and item["title"] == title), None), timeout, f"the window {title!r}")
    if not native.acquire_foreground(hwnd):
        raise native.ForegroundLost(f"the window {title!r} could not take the foreground; {native.foreground_owner()} has it")
    path = wait_until(lambda: next((item["path"] for item in session.client.call("toplevels")["toplevels"]
                                    if item["class"] == "Toplevel" and item["title"] == title), None), timeout,
                      f"the Tk window titled {title!r}")
    session.settle()
    return hwnd, path


def click(session: AppSession, target: dict) -> None:
    session.click_path(target["path"])


def start_setup(context: Context, copy: Path, name: str) -> tuple[AppSession, Path]:
    record = context.work / f"{name}-record.jsonl"
    session = AppSession(context.evidence, context.work / name, script=SETUP_LAUNCHER,
                         config={"app_root": str(copy), "record": str(record)}, name=name)
    context.sessions.append(session)
    session.start()
    return session, record


def clean_exit(context: Context, facts: dict, *, label: str, status: int) -> None:
    report = context.report
    report.check(f"{label}: the process exited", facts["exited"], f"after {facts['seconds']} s")
    report.equal(f"{label}: exit status", facts["exit_status"], status)
    report.check(f"{label}: no window remains", not facts["windows_after"], facts["windows_after"])
    report.check(f"{label}: no owned process remains", not facts["orphans"], facts["orphans"])
    tail = facts["stderr_tail"]
    report.check(f"{label}: no Tcl or interpreter fatal error",
                 not any(marker in tail for marker in ("Tcl_AsyncDelete", "Fatal Python error", "wrong thread", "Traceback")), tail[-400:])
    context.notes.setdefault("exits", []).append({key: value for key, value in facts.items() if key != "stderr_tail"})


# --------------------------------------------------------------------------- #
# The first-run window
# --------------------------------------------------------------------------- #
@scenario("setup.first-run-refuses-a-folder-too-deep", tool="setup", layers=("native",), tier="adverse", budget=240,
          summary="The real first-run window and the real run_setup on a copy whose folder path is too long for Windows: Begin Setup, the "
                  "native failure box, Open log folder, Close; exit status 1 and nothing installed")
def first_run_refusal(context: Context) -> None:
    report = context.report
    # 150 characters: refused whether or not Windows long paths are on (the app's limits are 123 and 87 since v0.8.0), and short
    # enough that the copy's own deepest file (54 more) still fits below 259.
    base = context.work / "too-deep"
    copy = make_copy(base / ("x" * max(1, 150 - len(str(base)) - len("\\app") - 1)) / "app")
    before = listing(copy)
    session, record = start_setup(context, copy, "setup")
    started = wait_until(lambda: next((item for item in read_record(record) if item["kind"] == "started"), None), 10, "the launcher's record")
    report.equal("the window under test is setting up the copy and nothing else", Path(started["app_root"]), copy)
    length = started["path_length"]
    report.equal("the copy's folder length, counted in Windows units by the application and here", length, windows_units(copy))
    limits = started["limits"]
    limit = limits["long_paths"] if started["long_paths"] else limits["default"]
    report.check("the copy's folder path really is too long here, and would be either way", length > max(limits.values()),
                 {"length": length, "limits": limits, "long_paths": started["long_paths"], "limit": limit})

    report.equal("the window is the setup window", session.client.call("window")["title"], SETUP_TITLE)
    boxes = shown(session, cls="TCheckbutton")
    report.check("the five voice choices, in order", len(boxes) == len(CHOICES) and all(box["text"].startswith(label)
                                                                                       for box, (label, _default) in zip(boxes, CHOICES)),
                 [box["text"] for box in boxes])
    session.screenshot("first-run-intro")
    click(session, one(session, "TButton", "Begin Setup"))

    said = session.answer_dialog("OK", title="Setup did not complete", timeout=60)
    body = " ".join(said["body"])
    report.check("the failure box gives the real reason", "too long for Windows" in body and "Nothing was installed" in body, body[:400])
    report.check("and the real figures", f"({length} characters; it must be {limit} or fewer here)" in body, body[:400])

    open_log = wait_for(session, "TButton", "Open log folder")
    close = one(session, "TButton", "Close")
    log_text = shown(session, cls="Text")[0].get("content", "")
    report.check("the live log shows the same reason", "too long for Windows" in log_text, log_text[-300:])
    report.check("Begin Setup is no longer offered", not [b for b in shown(session, cls="TButton") if b.get("text") == "Begin Setup"])
    session.screenshot("first-run-refused")

    click(session, open_log)
    asked = wait_until(lambda: [item for item in read_record(record) if item["kind"] == "open-folder"], 10, "the request to open the log folder")
    report.equal("Open log folder asks for the copy's own log folder, once", [Path(item["path"]) for item in asked],
                 [copy / "files" / "runtime-data" / "logs"])

    watch = session.exit_watch()
    click(session, close)
    clean_exit(context, session.wait_for_exit(watch), label="Close after a failed setup", status=1)
    events = read_record(record)
    report.equal("setup's own exit code", [item["code"] for item in events if item["kind"] == "exit"], [1])
    report.check("the application was never started after a failed setup", not [item for item in events if item["kind"] == "launch-gui"])
    report.check("nothing reached the real file manager", not [item for item in events if item["kind"] == "startfile"])

    after = listing(copy)
    added = sorted(set(after) - set(before))
    report.check("nothing was installed: the only new files are setup's own log", bool(added) and
                 all(name.startswith("files/runtime-data/logs/setup_") for name in added), added)
    report.check("no file of the copy was changed", {name: size for name, size in after.items() if name in before} == before)
    for absent in (".venv", "files/bin", "files/runtime-data/python-packages", "files/runtime-data/models"):
        report.check(f"no {absent}", not (copy / absent).exists())
    written = "".join((copy / name).read_text(encoding="utf-8", errors="replace") for name in added)
    report.check("the log on disk holds the reason too", "too long for Windows" in written, written[-300:])


@scenario("setup.first-run-choices-and-cancel", tool="setup", layers=("native", "visual"), tier="geometry", budget=240,
          summary="The real first-run window's five voice choices and their defaults, one changed by a real click, every control on screen "
                  "at the window's smallest size, then Cancel: exit status 2 and nothing created")
def first_run_cancel(context: Context) -> None:
    report = context.report
    copy = make_copy(context.work / "copy" / "app")
    before = listing(copy)
    session, record = start_setup(context, copy, "setup")
    report.equal("the window is the setup window", session.client.call("window")["title"], SETUP_TITLE)

    def choices() -> list[tuple[str, bool]]:
        return [(box["text"], bool(box.get("selected"))) for box in shown(session, cls="TCheckbutton")]

    found = choices()
    report.equal("five choices", len(found), len(CHOICES))
    for (label, default), (text, selected) in zip(CHOICES, found):
        report.check(f"{label}: offered with its approved default ({'on' if default else 'off'})",
                     text.startswith(label) and selected is default, (text, selected))
    report.check("each optional download states its size", all("(up to " in text for text, _selected in found), [t for t, _s in found])
    session.screenshot("first-run-choices")

    click(session, one(session, "TCheckbutton", CHOICES[1][0], prefix=True))
    wait_until(lambda: choices()[1][1] is True, 5, "the Chatterbox choice to be ticked")
    click(session, one(session, "TCheckbutton", CHOICES[0][0], prefix=True))
    wait_until(lambda: choices()[0][1] is False, 5, "the Kokoro choice to be cleared")
    report.equal("a real click changes one choice and no other", [selected for _text, selected in choices()],
                 [False, True, False, False, False])

    for size in ((660, 600), (760, 680)):
        native.resize_client(session.hwnd, *size)
        wait_until(lambda: tuple(native.client_size(session.hwnd)) == size, 8, f"the window to reach {size}")
        session.settle()
        window = session.client.call("window")
        for item in [*shown(session, cls="TCheckbutton"), *shown(session, cls="TButton")]:
            inside = (window["x"] <= item["x"] and window["y"] <= item["y"] and item["x"] + item["width"] <= window["x"] + window["width"]
                      and item["y"] + item["height"] <= window["y"] + window["height"])
            report.check(f"at {size[0]}x{size[1]}: {item['text'][:28]!r} is wholly on screen", inside,
                         {key: item[key] for key in ("x", "y", "width", "height")})
        session.screenshot(f"first-run-{size[0]}x{size[1]}")

    watch = session.exit_watch()
    click(session, one(session, "TButton", "Cancel"))
    clean_exit(context, session.wait_for_exit(watch), label="Cancel before setup", status=2)
    events = read_record(record)
    report.equal("setup's own exit code says cancelled, not failed", [item["code"] for item in events if item["kind"] == "exit"], [2])
    report.check("nothing was started", not [item for item in events if item["kind"] in ("launch-gui", "open-folder", "startfile")])
    after = listing(copy)
    report.check("nothing was created or changed in the copy but an empty log", {n: s for n, s in after.items() if n in before} == before
                 and all(name.startswith("files/runtime-data/logs/") for name in set(after) - set(before)), sorted(set(after) - set(before)))
    report.check("no environment was begun", not (copy / ".venv").exists())


# --------------------------------------------------------------------------- #
# Clear Downloaded Data
# --------------------------------------------------------------------------- #
#: (id, label on its row, what a person ticks here). Application logs is left unticked, so "only what was ticked" is part of the proof.
ASSETS = (("virtual_environment", ".venv", True), ("portable_binaries", "files/bin", True),
          ("downloaded_models", "files/runtime-data/models", True), ("application_logs", "files/runtime-data/logs", False))


def seed_downloaded_data(copy: Path) -> dict[str, bytes]:
    """Stand-in downloaded data in each of the four places the catalog names, plus things beside them that must survive."""
    files = {
        ".venv/pyvenv.cfg": b"home = C:\\nowhere\n",
        ".venv/Scripts/python.exe": b"not a real interpreter",
        ".venv/Lib/site-packages/sample/__init__.py": b"VALUE = 1\n",
        "files/bin/ffmpeg.exe": b"not a real ffmpeg",
        "files/bin/ffprobe.exe": b"not a real ffprobe",
        "files/runtime-data/models/huggingface/hub/models--sample--voice/blobs/0001": b"m" * 4096,
        "files/runtime-data/logs/session_2026-01-01.log": b"an earlier session's log\n",
        # Not in the catalog: each must still be there afterwards, byte for byte.
        "files/runtime-data/nltk_data/tokenizers/sample.txt": b"sentence data stays",
        "files/runtime-data/python-packages/sample.whl": b"the package store stays",
        "files/Cloned-Voice-Uploads/Sample Voice.wav": b"RIFF a reference recording stays",
        "files/keep-me.txt": b"an unrelated file stays",
    }
    for name, data in files.items():
        target = copy / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return files


@scenario("setup.clear-downloaded-data", tool="setup", layers=("native",), tier="journey", budget=420,
          summary="Clear Downloaded Data on a disposable copy: Preferences, the real dialog and its confirmation by real clicks, the "
                  "application closing itself, the real helper deleting exactly what was ticked, and the result shown at the next launch")
def clear_downloaded_data(context: Context) -> None:
    if sys.platform == "darwin":
        return clear_downloaded_data_macos(context)
    report = context.report
    copy = make_copy(context.work / "copy" / "app")
    seeded = seed_downloaded_data(copy)
    bystander = make_copy(context.work / "bystander" / "app")
    seed_downloaded_data(bystander)
    bystander_before = scratch_store.tree_digest(bystander)
    code_before = scratch_store.tree_digest(copy / "scripts")
    state = copy / "files" / "runtime-data" / "maintenance"

    # app_launcher refuses to start unless the application it imported is this copy's own, so a session that starts is the copy.
    session = context.app(name="app", app_root=str(copy))
    session.click(None, "preferences_button")
    _hwnd, preferences = toplevel_window(session, "Preferences & Data")
    click(session, one(session, "TButton", "Clear Downloaded Data", toplevel=preferences, prefix=True))
    _hwnd, dialog = toplevel_window(session, "Clear Downloaded Data")

    rows = shown(session, cls="TCheckbutton", toplevel=dialog)
    report.equal("four items, none ticked when the dialog opens", [bool(row.get("selected")) for row in rows], [False] * 4)
    names = [row["text"] for row in rows]
    report.check("each item has a name of its own", len(set(names)) == 4 and all(names), names)
    review = one(session, "TButton", "Review Selected Data…", toplevel=dialog)
    report.check("nothing can be reviewed until something is ticked", review["disabled"], review)
    for row, (_asset, _folder, ticked) in zip(rows, ASSETS):
        if ticked:
            click(session, row)
    wait_until(lambda: [bool(row.get("selected")) for row in shown(session, cls="TCheckbutton", toplevel=dialog)] ==
               [ticked for _a, _f, ticked in ASSETS], 5, "the three ticks")
    session.screenshot("clear-downloaded-data", window=_hwnd)
    click(session, wait_until(lambda: (lambda b: None if b["disabled"] else b)(one(session, "TButton", "Review Selected Data…", toplevel=dialog)),
                              10, "Review Selected Data to become available"))

    confirm_hwnd, confirm = toplevel_window(session, "Confirm clearing downloaded data")
    message = " ".join(item.get("text", "") for item in shown(session, cls="TLabel", toplevel=confirm))
    ticked_names = [name for name, (_a, _f, ticked) in zip(names, ASSETS) if ticked]
    report.check("the confirmation names each ticked item and not the one left alone",
                 all(name in message for name in ticked_names) and names[3] not in message, message[:600])
    report.check("nothing has been touched while the question is open", all((copy / name).exists() for name in seeded))
    report.check("no request exists before the confirmation", not (state / "cleanup-request.json").exists())
    session.screenshot("clear-downloaded-data-confirm", window=confirm_hwnd)

    watch = session.exit_watch()
    click(session, one(session, "TButton", "Clear 3 Selected Items and Close", toplevel=confirm))
    facts = session.wait_for_exit(watch, timeout=90)
    report.check("the application closed itself", facts["exited"], f"after {facts['seconds']} s")
    report.equal("with exit status 0", facts["exit_status"], 0)
    report.check("and left no window", not facts["windows_after"], facts["windows_after"])
    context.notes.setdefault("exits", []).append({key: value for key, value in facts.items() if key != "stderr_tail"})

    # The helper is the application's own detached process. It outlives the window on purpose, and it is the only thing that may.
    result_file = state / "cleanup-result.json"
    wait_until(result_file.is_file, 120, "the helper's result")
    wait_until(lambda: not session.job.pids(), 60, "the helper to end by itself")
    result = json.loads(result_file.read_text(encoding="utf-8"))
    outcomes = {item["asset_id"]: item["status"] for item in result["outcomes"]}
    report.equal("the helper reports exactly the three ticked items, each removed", outcomes,
                 {asset: "removed" for asset, _folder, ticked in ASSETS if ticked})
    report.check("the request was consumed before anything was deleted", (state / "cleanup-request.consumed.json").is_file()
                 and not (state / "cleanup-request.json").exists())

    report.check("the environment folder is gone", not (copy / ".venv").exists())
    for folder in ("files/bin", "files/runtime-data/models"):
        report.check(f"{folder} is kept, empty", (copy / folder).is_dir() and not any((copy / folder).iterdir()),
                     sorted(p.name for p in (copy / folder).iterdir()) if (copy / folder).is_dir() else "missing")
    survivors = [name for name in seeded if not name.startswith((".venv/", "files/bin/", "files/runtime-data/models/"))]
    report.check("everything that was not ticked is still there, byte for byte",
                 all((copy / name).read_bytes() == seeded[name] for name in survivors), survivors)
    report.equal("the application's own code was not touched", scratch_store.tree_digest(copy / "scripts"), code_before)
    report.equal("a second installation beside it was not touched", scratch_store.tree_digest(bystander), bystander_before)

    relaunch = context.app(name="relaunch", app_root=str(copy))
    result_hwnd, shown_result = toplevel_window(relaunch, "Downloaded data cleanup")
    text = " ".join(item.get("text", "") for item in shown(relaunch, cls="TLabel", toplevel=shown_result))
    report.check("the next launch names each item that was cleared and not the one left alone",
                 all(name in text for name in ticked_names) and names[3] not in text, text[:600])
    relaunch.screenshot("cleanup-result", window=result_hwnd)
    click(relaunch, one(relaunch, "TButton", "Continue", toplevel=shown_result))
    wait_until(lambda: not [item for item in native.windows_of(relaunch.pid) if item["title"] == "Downloaded data cleanup"], 10,
               "the result window to close")
    report.check("the result is shown once: it is retired on disk", (state / "cleanup-result.presented.json").is_file()
                 and not result_file.exists())
    native.acquire_foreground(relaunch.hwnd)
    expect_clean_close(context, relaunch, label="close after the result")


# --------------------------------------------------------------------------- #
# Clear Downloaded Data on macOS (v0.8.0 P5)
# --------------------------------------------------------------------------- #
def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _process_line(pid: int) -> str:
    """``pid pgid command`` as the kernel has it now (``ps``), or '' when the process is gone. Read, never acted on."""
    done = subprocess.run(["/bin/ps", "-ww", "-o", "pid=,pgid=,command=", "-p", str(int(pid))], capture_output=True, text=True, timeout=10)
    return done.stdout.strip()


def clear_downloaded_data_macos(context: Context) -> None:
    """The Windows journey's steps through the in-process macOS driver, on a disposable copy in a Mac's layout.

    Before anything is launched, the copy's own code is asked where it would clean, with which helper and on which interpreter, and
    every answer must lie inside the copy (the interpreter outside it and outside every cleanup target of the real checkout), with no
    link in the copy but the two the journey seeded; otherwise the scenario stops BLOCKED with nothing started. Afterwards every entry
    of the copy is compared byte for byte, and the real helper is identified by its acknowledgement, its spawn record and the kernel's
    own command line: the copy's ``cleanup_worker.py`` on the interpreter the preflight named, in a session of its own."""
    from adapters.macos import containment

    report = context.report
    work = Path(os.path.realpath(context.work))
    copy = make_copy(work / "copy" / "app")
    outside = work / "outside"
    seeded = cleanup_journey.seed(copy, outside)
    bystander = make_copy(work / "bystander" / "app")
    cleanup_journey.seed(bystander, work / "bystander-outside")
    state = copy / "files" / "runtime-data" / "maintenance"
    protected = cleanup_journey.protected_locations(REPO_ROOT)

    # -- the isolation preflight: nothing is launched or clicked unless every answer is the copy's own ------------------------- #
    probe_env = {key: value for key, value in os.environ.items()
                 if key not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "ACT_STARTUP_NOTICE")}
    probe_env.update(PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(work))
    facts = cleanup_journey.copy_facts(copy, env=probe_env)
    problems = cleanup_journey.isolation_problems(facts, copy=copy, scratch=work, real_root=REPO_ROOT, protected=protected,
                                                  outside=outside, links=cleanup_journey.find_links(copy))
    protected_before = cleanup_journey.protected_state(protected, scratch_store.tree_digest)
    preflight = {"copy": str(copy), "scratch": str(work), "real_root": str(REPO_ROOT), "copy_facts": facts, "problems": problems,
                 "protected": {label: str(path) for label, path in protected.items()}, "protected_before": protected_before,
                 "seeded": sorted(seeded), "links": cleanup_journey.find_links(copy)}
    (context.evidence / "isolation-preflight.json").write_text(json.dumps(preflight, indent=1), encoding="utf-8")
    context.notes["isolation_preflight"] = {"problems": problems, "interpreter": facts.get("interpreter"),
                                            "coordinator_script": facts.get("coordinator_script")}
    report.check("isolation preflight: the copy's own code names only the copy (targets, state, helper; interpreter outside it)",
                 not problems, problems[:6])
    if problems:
        raise containment.ContainmentUnavailable(f"the isolation preflight failed before anything was launched: {problems[:4]}")
    interpreter, helper = facts["interpreter"], facts["coordinator_script"]
    bystander_before = cleanup_journey.content_digest(bystander)
    outside_before = cleanup_journey.content_digest(outside)
    names = facts["display_names"]

    # -- the real application, on the copy --------------------------------------------------------------------------------------- #
    # app_launcher refuses to start unless the application it imported is this copy's own, so a session that starts is the copy.
    session = context.app(name="app", app_root=str(copy))
    report.check("no cleanup request or result exists before the dialog", not state.exists() or not any(state.iterdir()),
                 sorted(p.name for p in state.iterdir()) if state.exists() else [])
    before = cleanup_journey.content_digest(copy)
    session.click(None, "preferences_button")
    preferences_hwnd, preferences = toplevel_window(session, "Preferences & Data")
    session.screenshot("preferences", window=preferences_hwnd)
    click(session, one(session, "TButton", "Clear Downloaded Data", toplevel=preferences, prefix=True))
    dialog_hwnd, dialog = toplevel_window(session, "Clear Downloaded Data")

    rows = shown(session, cls="TCheckbutton", toplevel=dialog)
    report.equal("four items, none ticked when the dialog opens", [bool(row.get("selected")) for row in rows], [False] * 4)
    by_asset = {}
    for asset, display, _folder, _ticked in cleanup_journey.MAC_ASSETS:
        matching = [row for row in rows if row.get("text", "").startswith(display)]
        report.check(f"the {display!r} row is offered once, as the copy's catalog names it", len(matching) == 1 and names.get(asset) == display,
                     [row.get("text") for row in rows])
        if matching:
            by_asset[asset] = matching[0]
    report.check("every row can be ticked", all(not row.get("disabled") for row in rows), rows)
    review = one(session, "TButton", "Review Selected Data…", toplevel=dialog)
    report.check("nothing can be reviewed until something is ticked", review["disabled"], review)
    for asset in cleanup_journey.SELECTED:
        click(session, by_asset[asset])
    wanted = [row["path"] for asset in cleanup_journey.SELECTED for row in [by_asset[asset]]]
    wait_until(lambda: sorted(row["path"] for row in shown(session, cls="TCheckbutton", toplevel=dialog) if row.get("selected"))
               == sorted(wanted), 5, "exactly the three ticks")
    session.screenshot("clear-downloaded-data", window=dialog_hwnd)
    click(session, wait_until(lambda: (lambda b: None if b["disabled"] else b)(one(session, "TButton", "Review Selected Data…", toplevel=dialog)),
                              10, "Review Selected Data to become available"))

    confirm_hwnd, confirm = toplevel_window(session, "Confirm clearing downloaded data")
    message = " ".join(item.get("text", "") for item in shown(session, cls="TLabel", toplevel=confirm))
    ticked_names = [display for asset, display, _f, ticked in cleanup_journey.MAC_ASSETS if ticked]
    report.check("the confirmation names each ticked item and not the one left alone",
                 all(name in message for name in ticked_names) and "Application logs" not in message, message[:600])
    report.check("the confirmation speaks a Mac's words: OmniVoice, never Qwen3", "OmniVoice" in message and "Qwen3" not in message,
                 message[:600])
    report.check("the confirmation offers Cancel beside the destructive button",
                 bool([b for b in shown(session, cls="TButton", toplevel=confirm) if b.get("text") == "Cancel"]))
    during = cleanup_journey.content_digest(copy)
    touched = sorted(name for name, digest in before.items()
                     if not name.startswith(cleanup_journey.VOLATILE_PREFIXES) and during.get(name) != digest)
    report.check("nothing has been touched while the question is open", not touched, touched[:6])
    report.check("no request exists before the confirmation", not (state / "cleanup-request.json").exists())
    session.screenshot("clear-downloaded-data-confirm", window=confirm_hwnd)

    watch = session.exit_watch()
    click(session, one(session, "TButton", "Clear 3 Selected Items and Close", toplevel=confirm))
    accepted = wait_until(lambda: _read_json(state / "cleanup-accepted.json"), 60, "the cleanup helper's acknowledgement")
    coordinator = int(accepted["coordinator_process_id"])
    line = _process_line(coordinator)  # alive: it waits for the application to exit, and the application has not been reaped yet
    spawned = [item for item in session.job.records() if item.get("pid") == coordinator]
    request = _read_json(state / "cleanup-request.json") or _read_json(state / "cleanup-request.consumed.json") or {}
    facts_exit = session.wait_for_exit(watch, timeout=90)
    context.notes.setdefault("exits", []).append({key: value for key, value in facts_exit.items() if key != "stderr_tail"})
    context.notes["coordinator"] = {"pid": coordinator, "ps": line, "spawn_record": spawned, "request": request}
    report.check("the application closed itself", facts_exit["exited"], f"after {facts_exit['seconds']} s")
    report.equal("with exit status 0", facts_exit["exit_status"], 0)
    report.check("and left no window", not facts_exit["windows_after"], facts_exit["windows_after"])
    report.check("no Tk call from a worker thread", not facts_exit["tk_off_thread"], facts_exit["tk_off_thread"][:5])
    report.check("the only owned process outliving the window is the acknowledged helper",
                 all(item.get("pid", item.get("pgid")) == coordinator for item in facts_exit["orphans"]), facts_exit["orphans"])
    parts = line.split(None, 2)
    report.check("the helper is the copy's own cleanup_worker.py on the preflight's interpreter, for this request",
                 len(parts) == 3 and int(parts[0]) == coordinator and parts[2].startswith(f"{interpreter} {helper} --run --request-id ")
                 and parts[2].endswith(str(request.get("request_id"))), line)
    report.check("the application started it, and it leads a session of its own (detached by design)",
                 len(spawned) == 1 and spawned[0].get("pgid") == coordinator and len(parts) == 3 and int(parts[1]) == coordinator, spawned)
    report.equal("the request names the application under test and exactly the three ticked items",
                 (request.get("process_id"), request.get("asset_ids")), (session.pid, list(cleanup_journey.SELECTED)))

    result_file = state / "cleanup-result.json"
    wait_until(result_file.is_file, 120, "the helper's result")
    wait_until(lambda: not session.job.pids(), 60, "the helper to end by itself")
    report.check("no owned process or process group remains", not session.job.pids() and not session._occupied_groups(),
                 {"pids": session.job.pids(), "groups": session._occupied_groups()})
    result = json.loads(result_file.read_text(encoding="utf-8"))
    outcomes = {item["asset_id"]: item["status"] for item in result["outcomes"]}
    report.equal("the helper reports exactly the three ticked items, each removed", outcomes, {asset: "removed" for asset in cleanup_journey.SELECTED})
    report.check("the request was consumed before anything was deleted", (state / "cleanup-request.consumed.json").is_file()
                 and not (state / "cleanup-request.json").exists())
    log = (state / "cleanup-coordinator.log").read_text(encoding="utf-8") if (state / "cleanup-coordinator.log").is_file() else ""
    report.check("the helper's own log, in the copy, is this helper's: accepted, removed, recorded",
                 f"(pid {coordinator})" in log and f"accepted request {request.get('request_id')}" in log and "result recorded" in log, log[-600:])

    after = cleanup_journey.content_digest(copy)
    pinned = [name for name in seeded if name.startswith(cleanup_journey.VOLATILE_PREFIXES)]
    outcome = cleanup_journey.outcome_problems(before, after, pinned=pinned)
    report.check("only the ticked items were removed: every other entry is byte-identical", not outcome, outcome[:6])
    report.equal("the helper held this copy's own engine lease: exactly its five empty locks appeared, in the copy",
                 sorted(name for name in set(after) - set(before) if name in cleanup_journey.LEASE_LOCKS
                        and after[name] == cleanup_journey.EMPTY_FILE), sorted(cleanup_journey.LEASE_LOCKS))
    report.check("the environment folder is gone, with its links (removed as links)", not (copy / ".venv").exists()
                 and not any((copy / link).is_symlink() for link in cleanup_journey.LINKS))
    for folder in ("files/bin", "files/runtime-data/models"):
        report.check(f"{folder} is kept, empty", (copy / folder).is_dir() and not any((copy / folder).iterdir()),
                     sorted(p.name for p in (copy / folder).iterdir()) if (copy / folder).is_dir() else "missing")
    report.check("what the links pointed at, outside the copy, is untouched",
                 not cleanup_journey.tree_problems("the links' sentinel", outside_before, cleanup_journey.content_digest(outside)))
    report.check("a second installation beside it is byte-identical",
                 not cleanup_journey.tree_problems("the bystander", bystander_before, cleanup_journey.content_digest(bystander)))

    relaunch = context.app(name="relaunch", app_root=str(copy))
    result_hwnd, shown_result = toplevel_window(relaunch, "Downloaded data cleanup")
    text = " ".join(item.get("text", "") for item in shown(relaunch, cls="TLabel", toplevel=shown_result))
    report.check("the next launch names each item that was cleared and not the one left alone",
                 all(name in text for name in ticked_names) and "Application logs" not in text, text[:600])
    relaunch.screenshot("cleanup-result", window=result_hwnd)
    click(relaunch, one(relaunch, "TButton", "Continue", toplevel=shown_result))
    wait_until(lambda: not [item for item in native.windows_of(relaunch.pid) if item["title"] == "Downloaded data cleanup"], 10,
               "the result window to close")
    report.check("the result is shown once: it is retired on disk", (state / "cleanup-result.presented.json").is_file()
                 and not result_file.exists())
    native.acquire_foreground(relaunch.hwnd)
    expect_clean_close(context, relaunch, label="close after the result")

    protected_after = cleanup_journey.protected_state(protected, scratch_store.tree_digest)
    report.equal("the real checkout's environment, FFmpeg, models, logs, settings, code and outputs are unchanged",
                 protected_after, protected_before)
    (context.evidence / "cleanup-outcome.json").write_text(json.dumps({
        "before": before, "after": after, "outcome_problems": outcome, "result": result, "coordinator": context.notes["coordinator"],
        "protected_after": protected_after}, indent=1, default=str), encoding="utf-8")
