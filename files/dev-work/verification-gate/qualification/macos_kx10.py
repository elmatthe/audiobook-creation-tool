#!/usr/bin/env python3
"""macos-kx10 (P1B closeout): KX-10's behavioural contract, automated -- SIGKILL of the application during a real M4B Maker encode.

    verify.py --mode qualification --platform macos --scenario macos-kx10

The former owner checklist asked for Force Quit (the Force Quit window, or Activity Monitor) during an M4B Maker build. What
Force Quit does to a process is SIGKILL: no signal handler, no ``atexit``, no Tk close path runs. This scenario does exactly
that to exactly the application process -- found by pid *and* kernel start time, never by name -- and checks what must
follow:

  1. a first instance builds Book One and closes; its M4B is the "already completed output" that must stay byte-identical;
  2. a second instance starts a real, bounded build of a longer Book Two; once an FFmpeg child of this application has been
     encoding for a full second (the spawn record and the kernel agree), the application is killed;
  3. every process the application started (FFmpeg, the containment guardian) must be gone within 5 s, by identity, and no
     process group it owned may be occupied;
  4. no M4B may exist under a final name except Book One's, and Book One's bytes are unchanged;
  5. a third instance on the same data starts cleanly and closes cleanly; what it does with Book Two's private staging is
     recorded as found (recovered, reported, or left in place -- D11b cross-process recovery is deferred, ACT72-076).

Not exercised: the Force Quit window itself (opening it, choosing the app); its effect on the process is the SIGKILL above.
Nothing outside this application's own process tree is signalled.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qualification import common, macos_common  # noqa: E402

NAME = "macos-kx10"
TOOL = "m4b_maker"
BOUND_SECONDS = 5.0


def _final_m4bs(root: Path) -> list[Path]:
    return sorted(item for item in root.rglob("*.m4b") if ".work" not in item.parts and not item.name.startswith(".")) if root.exists() else []


def _staging(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(str(item.relative_to(root)) for item in root.rglob("*")
                  if ".work" in item.parts or item.name.startswith(".") or item.suffix in (".part", ".tmp"))


def kx10_case(context) -> None:
    from adapters.macos.app_session import _alive
    from adapters.macos import native_input as native
    from journeys.common import expect_clean_close, log_text, open_tool, oracle, wait_for_job, wait_for_listbox, wait_until
    from journeys.shutdown import wait_for_long_encode
    import child_ownership  # scripts/shared, on the path the macOS session puts it

    report = context.report
    root = context.output_base / "M4B-Maker-Outputs"

    # 1. Book One, finished and closed: the output a later crash must not touch.
    first = context.app(last_tool=TOOL)
    open_tool(first, TOOL)
    first.click(TOOL, "btn_add_files")
    first.file_dialog([context.fixtures.path(item) for item in ("track-1", "track-2", "track-3")], title="Select MP3 files")
    wait_for_listbox(first, TOOL, "track_list", 3)
    first.type_into(TOOL, "book_entries[title]", "Book One")
    first.click(TOOL, "btn_build")
    report.equal("Book One was built", wait_for_job(first, TOOL), "SUCCEEDED")
    book_one = _final_m4bs(root)
    report.equal("one finished M4B before the crash", [item.name for item in book_one], ["Book One.m4b"])
    digest = oracle._sha256(book_one[0]) if book_one else None
    first.screenshot("book-one-finished", tool=TOOL)
    expect_clean_close(context, first, label="book one close")

    # 2. Book Two, a real long build, killed while FFmpeg encodes.
    second = context.app(last_tool=TOOL, name="crashing")
    open_tool(second, TOOL)
    second.click(TOOL, "btn_add_files")
    second.file_dialog([context.fixtures.path(item) for item in ("track-long-1", "track-long-2", "track-long-3")], title="Select MP3 files")
    wait_for_listbox(second, TOOL, "track_list", 3)
    second.type_into(TOOL, "book_entries[title]", "Book Two")
    second.click(TOOL, "btn_build")
    wait_for_long_encode(second, TOOL)
    second.screenshot("encoding", tool=TOOL)
    app_pid, app_start = second.identity
    encoders = [(item["pid"], tuple(item["start"])) for item in second.job.records()
                if item.get("start") and native.image_name(item["pid"]) == "ffmpeg" and _alive((item["pid"], tuple(item["start"])))]
    report.check("the encoder was running when the application was killed", bool(encoders) and second.read(TOOL, "jobs.state") == "RUNNING",
                 {"encoders": encoders, "state": second.read(TOOL, "jobs.state")})
    owned = [(pid, start) for pid, start in second.job.identities() if start and _alive((pid, start))]
    context.notes["kx10"] = {"application": {"pid": app_pid, "start": app_start},
                             "encoders": [[pid, list(start)] for pid, start in encoders],
                             "owned_alive_at_kill": [[pid, list(start)] for pid, start in owned], "staging_before": _staging(root)}
    second.client.close()
    second.client = None
    began = time.monotonic()
    sent = child_ownership.signal_if_same(app_pid, app_start, signal.SIGKILL)
    report.check("SIGKILL went to exactly the application process (pid and kernel start time)", bool(sent), {"pid": app_pid})
    try:
        second.proc.wait(timeout=10)
    except Exception:  # noqa: BLE001 - recorded by the check below
        pass
    report.equal("the application died of SIGKILL", second.proc.returncode, -signal.SIGKILL)
    wait_until(lambda: not any(_alive(identity) for identity in owned) or time.monotonic() - began > BOUND_SECONDS + 1, BOUND_SECONDS + 2,
               "the application's children to end", poll=0.05)
    gone_after = round(time.monotonic() - began, 3)
    survivors = [pid for pid, start in owned if _alive((pid, start))]
    groups = second._occupied_groups()
    report.check("no ACT-owned process survived", not survivors and not groups, {"survivors": survivors, "groups": groups})
    report.check(f"every encoder was gone within {BOUND_SECONDS:.0f} s", not survivors and gone_after <= BOUND_SECONDS, f"{gone_after} s")
    context.notes["kx10"].update(seconds_to_clean=gone_after, staging_after_kill=_staging(root))
    finals = _final_m4bs(root)
    report.equal("no M4B under a final name", [item.name for item in finals], ["Book One.m4b"])
    report.check("the finished book is unchanged", bool(digest) and book_one and oracle._sha256(book_one[0]) == digest)
    report.check("nothing half-made is visible beside Book One", all(".work" in Path(name).parts or Path(name).name.startswith(".")
                                                                     for name in _staging(root)), _staging(root))

    # 3. Relaunch on the same data.
    third = context.app(last_tool=TOOL, name="relaunch")
    open_tool(third, TOOL)
    third.settle()
    third.screenshot("relaunched", tool=TOOL)
    report.check("the relaunch started cleanly", third.read(TOOL, "jobs.state") == "IDLE" and not third.pending_dialogs(),
                 {"state": third.read(TOOL, "jobs.state"), "dialogs": third.pending_dialogs()})
    told = (log_text(third, TOOL) + log_text(third, TOOL, "details_text")).lower()
    left = _staging(root)
    recovery = ("recovered" if not left else "reported" if any(word in told for word in ("staging", "recovered", "left over", "leftover"))
                else "left in place, not reported (ACT72-076: cross-process recovery, D11b, deferred)")
    context.notes["kx10"].update(staging_after_relaunch=left, recovery=recovery)
    report.check("the leftover staging is private: no final name, nothing published", [item.name for item in _final_m4bs(root)] == ["Book One.m4b"],
                 {"recovery": recovery, "left": left[:10]})
    expect_clean_close(context, third, label="relaunch close")
    report.check("the finished book is still unchanged after the relaunch", bool(digest) and oracle._sha256(book_one[0]) == digest)


def main(argv=None) -> int:
    q = common.start(NAME, argv)
    if isinstance(q, int):
        return q

    def body(q):
        q.identity(signal="SIGKILL", bound_seconds=BOUND_SECONDS, force_quit_window_exercised=False)
        entries = macos_common.run_cases(q, [macos_common.Case("kx10", "maker-sigkill", kx10_case, tool="m4b-maker", budget=900)])
        notes = entries[0].get("notes", {}).get("kx10", {}) if entries else {}
        q.log(f"kx10 facts: {notes}")
        (q.root / "kx10.json").write_text(__import__("json").dumps(notes, indent=1, default=str), encoding="utf-8")

    return q.finish(body)


if __name__ == "__main__":
    sys.exit(main())
