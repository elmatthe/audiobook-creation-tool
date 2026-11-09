"""Native negative controls: real windows and real refusals. A guard that has never refused anything proves nothing.

Each proves that something the journeys rely on really happens: input stops when the foreground is elsewhere, a covered or disabled
target is not clicked, a dead input path is noticed, a second run cannot share the desktop, a desktop that is not the input desktop is
BLOCKED, and the forced-landing arm can see the very crash it is looking for. They use a small target of their own, so they say nothing
about ACT, and they pass only when the refusal itself was seen.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from adapters.windows.app_session import AppSession
from journeys.common import Context, native, oracle, scenario, wait_until

GATE_DIR = Path(__file__).resolve().parents[1]
TARGET = GATE_DIR / "adapters" / "windows" / "control_target.py"
EXIT_TCL_CRASH = 0x80000003


def _target(context: Context, name: str, **config) -> AppSession:
    counts = context.work / f"{name}-clicks.txt"
    session = AppSession(context.evidence, context.work / name, script=TARGET, name=name,
                         config={"counts_file": str(counts), **config})
    context.sessions.append(session)
    session.counts = counts
    session.start()
    return session


def _clicks(session: AppSession) -> int:
    return int(session.counts.read_text(encoding="ascii")) if session.counts.is_file() else 0


@scenario("control.real-click-reaches-the-target", tool="gate", layers=("native", "control"), tier="control",
          summary="The no-change control for every refusal below: the same click, with nothing wrong, really does arrive")
def arrives(context: Context) -> None:
    session = _target(context, "a")
    before = native.foreground_owner()
    session.click(None, "button")
    wait_until(lambda: _clicks(session) == 1, 5, "the click to arrive")
    context.report.equal("the click arrived exactly once", _clicks(session), 1)
    context.report.check("the target had the foreground", before[1] == session.pid, before)
    facts = session.close_by_user()
    context.report.equal("exit status 0", facts["exit_status"], 0)


@scenario("control.lost-foreground-blocks-input", tool="gate", layers=("native", "control"), tier="control",
          summary="Another window takes the foreground: the click is not sent, the journey is BLOCKED, and neither window received anything")
def lost_foreground(context: Context) -> None:
    first = _target(context, "first", geometry="360x200+80+80")
    second = _target(context, "second", geometry="360x200+520+80")
    context.report.equal("the second window took the foreground", native.foreground_owner()[1], second.pid)
    refused = None
    try:
        first.click(None, "button")
    except native.ForegroundLost as exc:
        refused = str(exc)
    context.report.check("the click was refused as a lost foreground", refused is not None, refused)
    context.report.equal("the intended window received nothing", _clicks(first), 0)
    context.report.equal("the window in front received nothing", _clicks(second), 0)
    if refused is None:
        raise oracle.OracleFailure("the guard let input go to a window that did not have the foreground")


@scenario("control.covered-target-is-refused", tool="gate", layers=("native", "control"), tier="control",
          summary="An always-on-top window lies over the target: the click is refused, and nothing lands on the window on top")
def covered(context: Context) -> None:
    under = _target(context, "under", geometry="360x200+300+300")
    over = _target(context, "over", geometry="560x400+200+200", on_top=True)
    native.acquire_foreground(under.hwnd)
    wait_until(lambda: native.foreground_owner()[0] == under.hwnd, 5, "the lower window to hold the foreground")
    refused = None
    try:
        under.click(None, "button")
    except native.InputRefused as exc:
        refused = str(exc)
    context.report.check("the click was refused because it was covered", refused is not None, refused)
    context.report.equal("the covered window received nothing", _clicks(under), 0)
    context.report.equal("the covering window received nothing", _clicks(over), 0)
    shot = None
    try:
        under.screenshot("must-not-exist")
    except native.ScreenshotRefused as exc:
        shot = str(exc)
    context.report.check("a picture of a covered window is refused, so nothing else can reach evidence", shot is not None, shot)
    if refused is None:
        raise oracle.OracleFailure("the guard clicked a covered target")


@scenario("control.disabled-target-is-refused", tool="gate", layers=("native", "control"), tier="control",
          summary="A disabled control is never clicked as though it were live")
def disabled(context: Context) -> None:
    session = _target(context, "a")
    refused = None
    try:
        session.click(None, "disabled")
    except native.InputRefused as exc:
        refused = str(exc)
    context.report.check("the click was refused", refused is not None and "disabled" in refused, refused)
    context.report.equal("nothing happened", _clicks(session), 0)
    if refused is None:
        raise oracle.OracleFailure("the guard clicked a disabled control")


@scenario("control.dead-input-path-blocks", tool="gate", layers=("native", "control"), tier="control",
          summary="A key press sent to the window never arrives (a handle alone would have said all is well): the session is BLOCKED")
def dead_input(context: Context) -> None:
    refused = None
    try:
        _target(context, "deaf", no_input_mark=True)
    except native.DesktopUnavailable as exc:
        refused = str(exc)
    context.report.check("a session that cannot see its own input is refused", refused is not None and "never arrived" in refused, refused)
    if refused is None:
        raise oracle.OracleFailure("a session started without proving input reaches it")


@scenario("control.second-run-refused-by-the-lease", tool="gate", layers=("control",), tier="control",
          summary="While this run holds the desktop lease, another process asking for it is refused")
def lease(context: Context) -> None:
    probe = ("import sys\n"
             f"sys.path.insert(0, {str(GATE_DIR)!r})\n"
             "from adapters.windows import native_input as n\n"
             "try:\n"
             "    with n.DesktopLease():\n"
             "        print('GRANTED')\n"
             "except n.DesktopUnavailable as e:\n"
             "    print('REFUSED', e)\n")
    done = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True, timeout=60)
    context.report.check("the second run was refused", "REFUSED" in done.stdout and "GRANTED" not in done.stdout, done.stdout + done.stderr[-200:])


@scenario("control.other-desktop-is-blocked", tool="gate", layers=("control",), tier="control",
          summary="A process on a desktop that is not the input desktop, the position a locked or secure session puts it in, reads as not usable")
def other_desktop(context: Context) -> None:
    probe = ("import ctypes, ctypes.wintypes as w, json, sys\n"
             f"sys.path.insert(0, {str(GATE_DIR)!r})\n"
             "from adapters.windows import native_input as n\n"
             "u = n.user32\n"
             "u.CreateDesktopW.restype = w.HANDLE\n"
             "u.CreateDesktopW.argtypes = [w.LPCWSTR, w.LPCWSTR, w.LPVOID, w.DWORD, w.DWORD, w.LPVOID]\n"
             "u.SetThreadDesktop.argtypes = [w.HANDLE]\n"
             "d = u.CreateDesktopW('ACT-control-' + str(__import__('os').getpid()), None, None, 0, 0x10000000, None)\n"
             "assert d, ctypes.get_last_error()\n"
             "assert u.SetThreadDesktop(d), ctypes.get_last_error()\n"
             "s = n.desktop_status()\n"
             "print(json.dumps({'ok': s.ok, 'reason': s.reason, 'thread': s.facts.get('thread_desktop'), 'input': s.facts.get('input_desktop')}))\n")
    done = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True, timeout=60)
    reading = next((line for line in done.stdout.splitlines() if line.startswith("{")), None)
    if reading is None:
        raise oracle.OracleFailure(f"the control did not run: {done.stdout} {done.stderr[-400:]}")
    facts = json.loads(reading)
    context.report.equal("the session reads as not usable", facts["ok"], False)
    context.report.check("and says why", "desktop" in facts["reason"], facts)
    context.report.check("this process's own desktop, the control, still reads usable", native.desktop_status().ok, native.desktop_status().reason)


@scenario("control.forced-landing-sees-the-crash", tool="gate", layers=("native", "control", "shutdown"), tier="control",
          summary="The Phase 2 shape, closed by a real Alt+F4 with one collection forced onto a worker: it must crash with Tcl_AsyncDelete, or the forced arm proves nothing")
def forced_landing(context: Context) -> None:
    record = context.work / "forced.json"
    session = _target(context, "hazard", force_worker_collection=str(record))
    facts = session.close_by_user()
    context.notes["control_exit"] = {key: facts.get(key) for key in ("exited", "exit_hex", "seconds", "orphans")}
    context.report.equal("the process crashed with the wrong-thread breakpoint", facts["exit_status"], EXIT_TCL_CRASH)
    context.report.check("and said why", "Tcl_AsyncDelete" in facts["stderr_tail"], facts["stderr_tail"][-300:])
    context.report.check("no owned process outlived the crash", not facts["orphans"], facts["orphans"])


@scenario("control.act-orphan-seen-without-the-stop", tool="gate", layers=("native", "control", "shutdown"), tier="control",
          summary="The real Maker closed mid-build with the application's stops disabled (the launcher's stop of its media children and the "
                  "supervised step's answer to the panel's close-time Cancel): the orphan FFmpeg must be seen, or the clean closes prove nothing")
def orphan_without_stop(context: Context) -> None:
    from journeys.common import open_tool, wait_for_listbox
    from journeys.shutdown import wait_for_long_encode

    session = context.app(last_tool="m4b_maker", control_no_stop_children=True)
    open_tool(session, "m4b_maker")
    paths = [context.fixtures.path(item) for item in ("track-long-1", "track-long-2", "track-long-3")]
    session.click("m4b_maker", "btn_add_files")
    session.file_dialog(paths, title="Select MP3 files")
    wait_for_listbox(session, "m4b_maker", "track_list", 3)
    session.click("m4b_maker", "btn_build")
    wait_for_long_encode(session, "m4b_maker")
    facts = session.close_by_user()
    context.notes["control_exit"] = {key: facts.get(key) for key in ("exited", "exit_hex", "seconds", "orphans")}
    context.report.equal("the application itself exited cleanly", facts["exit_status"], 0)
    images = [Path(item["image"]).name.lower() for item in facts["orphans"]]
    context.report.check("and FFmpeg was left running, which the journey saw", "ffmpeg.exe" in images, images)


@scenario("control.act-crash-seen-with-the-root-released", tool="gate", layers=("native", "control", "shutdown"), tier="control",
          summary="The real application with every holder of its closed root emptied, its own included: the forced collection must then crash it")
def crash_without_holder(context: Context) -> None:
    from journeys.common import open_tool

    record = context.work / "forced.json"  # written by the application, which may write only below its Low-labelled scratch
    session = context.app(last_tool="cover", force_worker_collection=record, control_release_root=True)
    open_tool(session, "cover")
    session.screenshot("idle")
    facts = session.close_by_user()
    context.notes["control_exit"] = {key: facts.get(key) for key in ("exited", "exit_hex", "seconds", "orphans")}
    context.notes["stderr_tail"] = facts["stderr_tail"][-500:]
    if record.is_file():
        context.notes["forced_collection"] = json.loads(record.read_text(encoding="utf-8"))
    context.report.equal("the process crashed with the wrong-thread breakpoint", facts["exit_status"], EXIT_TCL_CRASH)
    context.report.check("and said why", "Tcl_AsyncDelete" in facts["stderr_tail"], facts["stderr_tail"][-300:])

