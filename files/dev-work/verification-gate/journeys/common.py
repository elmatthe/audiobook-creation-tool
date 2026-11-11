"""What every journey shares: the registry, the scenario's context, and the small verbs a person performs in any tool.

A journey is deterministic Python run by a script, with no model anywhere in the loop. Each one starts its own isolated instance from a
known state, drives it with real input, and judges the output only through ``helpers/media_oracle.py`` and its own direct reads.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from adapters.windows import app_session, native_input as native
from adapters.windows.app_session import AppSession, JourneyTimeout, wait_until
from helpers import media_fixtures, media_oracle as oracle

TERMINAL = {"SUCCEEDED", "CANCELLED", "COMPLETED_WITH_FAILURES", "FAILED"}
#: The sidebar key, and the control that shows a tool has really finished building.
TOOLS = {"tts": "go_btn", "mp3_tool": "btn_write_id3", "m4b_converter": "btn_convert", "m4b_maker": "btn_build", "m4b_metadata": "btn_save",
         "cover": "btn_convert"}
OUTPUT_SLUGS = {"tts": "TTS-Audiobook", "mp3_tool": "MP3-Tool", "m4b_converter": "M4B-Converter", "m4b_maker": "M4B-Maker",
                "m4b_metadata": "M4B-Metadata", "cover": "Cover-Image"}
DEFAULT_JOB_SECONDS = 120


@dataclass(frozen=True)
class Scenario:
    id: str
    tool: str
    layers: tuple[str, ...]
    tier: str
    summary: str
    run: Callable
    budget_seconds: int = 240
    applicable: Callable | None = None


SCENARIOS: dict[str, Scenario] = {}


def scenario(identifier: str, *, tool: str, layers: tuple[str, ...], tier: str, summary: str, budget: int = 240, applicable=None):
    """Register a journey. Its id is what coverage.json and verification.json name, so it is frozen once it exists."""

    def register(function):
        if identifier in SCENARIOS:
            raise ValueError(f"duplicate scenario {identifier}")
        SCENARIOS[identifier] = Scenario(identifier, tool, tuple(layers), tier, summary, function, budget, applicable)
        return function

    return register


@dataclass
class Context:
    """One scenario's own folders and tools. ``evidence`` is inside the run and kept; ``work`` is scratch and disposable."""

    id: str
    evidence: Path
    work: Path
    tools: oracle.Toolchain
    fixtures: media_fixtures.FixtureSet
    report: oracle.Report = field(default_factory=oracle.Report)
    sessions: list[AppSession] = field(default_factory=list)
    notes: dict = field(default_factory=dict)

    @property
    def output_base(self) -> Path:
        return self.work / "out"

    def app(self, *, last_tool: str = "tts", name: str = "app", replay: dict | None = None, settings: dict | None = None,
            force_worker_collection: Path | None = None, **extra) -> AppSession:
        config = {"output_base": str(self.output_base), "last_tool": last_tool, "settings": settings or {}, **extra}
        if replay:
            config["replay"] = replay
        if force_worker_collection:
            config["force_worker_collection"] = str(force_worker_collection)
        session = AppSession(self.evidence, self.work / name, config=config, name=name)
        self.sessions.append(session)
        session.start()
        return session

    def source_hashes(self, paths: list[Path]) -> dict[str, str]:
        return {str(path): oracle._sha256(path) for path in paths}

    def require_unchanged(self, before: dict[str, str]) -> None:
        for path, digest in before.items():
            self.report.check(f"source untouched: {Path(path).name}", oracle._sha256(Path(path)) == digest)

    def run_dir(self, tool: str, number: int = 1) -> Path:
        return self.output_base / f"{OUTPUT_SLUGS[tool]}-Outputs" / f"{OUTPUT_SLUGS[tool]}-{number}"


def open_tool(session: AppSession, tool: str, *, primary: str | None = None) -> None:
    """A physical click on the tool's own sidebar button, then wait until its real panel is on screen."""
    if session.read(None, "current_key") != tool:
        session.click(None, f"buttons[{tool}]")
    wait_until(lambda: session.read(None, "current_key") == tool, 45, f"{tool} to be the selected tool")
    key = primary or TOOLS[tool]
    wait_until(lambda: session.widget(tool, key).get("viewable"), 45, f"{tool}'s {key} to be on screen")
    session.settle()


def unexpected_dialog(session: AppSession) -> dict | None:
    for dialog in native.native_dialogs_of(session.pid):
        return {**dialog, "body": [c["title"] for c in native.child_controls(dialog["hwnd"]) if c["class"] == "Static"]}
    return None


def wait_for_job(session: AppSession, tool: str, *, timeout: float = DEFAULT_JOB_SECONDS, states=TERMINAL) -> str:
    """Until the run reaches a terminal state. A message box nobody expected stops the wait at once, naming itself."""

    def reached():
        dialog = unexpected_dialog(session)
        if dialog:
            raise oracle.OracleFailure(f"an unexpected dialog appeared during {tool}'s run: {dialog['title']!r} {dialog['body']}")
        state = session.read(tool, "jobs.state")
        return state if state in states else None

    return wait_until(reached, timeout, f"{tool}'s run to reach {sorted(states)}", poll=0.1)


def log_text(session: AppSession, tool: str, pane: str = "summary_text") -> str:
    return session.widget(tool, f"log.{pane}").get("content", "")


def expect_clean_close(context: Context, session: AppSession, *, label: str = "close") -> dict:
    """Nothing hides here: the exit status is the interpreter's own, and an owned process that outlives it is an orphan."""
    facts = session.close_by_user()
    report = context.report
    report.check(f"{label}: the process exited", facts["exited"], f"after {facts['seconds']} s")
    report.check(f"{label}: exit status 0", facts["exit_status"] == 0, facts["exit_hex"])
    report.check(f"{label}: no window remains", not facts["windows_after"], facts["windows_after"])
    report.check(f"{label}: no owned process remains", not facts["orphans"], facts["orphans"])
    tail = facts["stderr_tail"]
    report.check(f"{label}: no Tcl or interpreter fatal error", not any(marker in tail for marker in
                                                                        ("Tcl_AsyncDelete", "Fatal Python error", "wrong thread")), tail[-400:])
    context.notes.setdefault("exits", []).append({key: value for key, value in facts.items() if key != "stderr_tail"})
    return facts


def resize_and_check(session: AppSession, context: Context, tool: str, keys: list[str], size: tuple[int, int]) -> None:
    """A real window-manager resize, then the window wholly inside its monitor's work area and every named control fully inside the
    client area. Size and overlap alone do not prove on-screen, and neither does a control inside a window that is itself partly hidden."""
    native.resize_client(session.hwnd, *size)
    wait_until(lambda: tuple(native.client_size(session.hwnd)) == size, 8, f"the client area to reach {size}")
    session.settle()
    client, area = native.client_on_screen(session.hwnd), native.work_area(session.hwnd)
    context.report.check(f"{tool} at {size[0]}x{size[1]}: the whole client area is inside the desktop's work area",
                         area[0] <= client[0] and area[1] <= client[1] and client[2] <= area[2] and client[3] <= area[3],
                         {"client": list(client), "work_area": list(area)})
    window = session.client.call("window")
    for key in keys:
        widget = session.widget(tool, key)
        inside = (widget.get("viewable") and window["x"] <= widget["x"] and window["y"] <= widget["y"]
                  and widget["x"] + widget["width"] <= window["x"] + window["width"]
                  and widget["y"] + widget["height"] <= window["y"] + window["height"])
        context.report.check(f"{tool} at {size[0]}x{size[1]}: {key} is on screen", inside,
                             {k: widget.get(k) for k in ("x", "y", "width", "height", "viewable")})


def wait_for_listbox(session: AppSession, tool: str, key: str, count: int, *, timeout: float = 30) -> list:
    def enough():
        items = session.widget(tool, key).get("items", [])
        return items if len(items) >= count else None

    return wait_until(enough, timeout, f"{key} to list {count} item(s)")


__all__ = ["AppSession", "Context", "JourneyTimeout", "Scenario", "SCENARIOS", "TERMINAL", "app_session", "expect_clean_close",
           "log_text", "native", "open_tool", "oracle", "media_fixtures", "resize_and_check", "scenario", "time", "unexpected_dialog",
           "wait_for_job", "wait_for_listbox", "wait_until"]
