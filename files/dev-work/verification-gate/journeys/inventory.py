"""Live discovery: the controls a running ACT really shows, read from its widget trees, held against the reviewed index (plan section 7.1).

Static discovery (``helpers/surface_discovery.py``) cannot see a control that a helper builds, a loop multiplies or a state reveals. This
journey opens the real application in an isolated instance and, by real clicks and keys, visits the states where controls are made: the
shell, each of the six tools, Preferences & Data, and each speech engine chosen in the TTS voice list. In each state it reads every widget
below the scope through the observation channel, names each interactive one (``surface_discovery.live_keys``), and compares the union per
scope with ``coverage.json`` ``surfaces.live``. A control nobody mapped, or a mapped control the application no longer shows, fails it.

``control.unmapped-live-control-is-caught`` is its negative control: the same scan of an instance given one extra, unmapped button.
"""

from __future__ import annotations

import json
from pathlib import Path

from helpers import surface_discovery
from journeys.common import TOOLS, Context, expect_clean_close, native, open_tool, scenario, wait_until

GATE_DIR = Path(__file__).resolve().parents[1]
#: One voice family per speech engine, in the order the list shows them. Choosing one is a state of the TTS panel; nothing is synthesised.
ENGINE_FAMILIES = ("Edge", "Kokoro", "Chatterbox", "Qwen3")
SHELL = "launcher"
PROBE_TEXT = "Unmapped probe"


def live_index() -> dict[str, dict[str, str]]:
    coverage = json.loads((GATE_DIR / "coverage.json").read_text(encoding="utf-8"))
    return coverage.get("surfaces", {}).get("live", {})


class Scan:
    """What one instance showed, per scope, over every state visited."""

    def __init__(self, session, context: Context) -> None:
        self.session = session
        self.context = context
        self.seen: dict[str, dict[str, dict]] = {}
        self.states: list[dict] = []

    def take(self, scope: str, state: str) -> None:
        tool = None if scope == SHELL else scope
        widgets = self.session.client.call("surfaces", scope=tool, exclude="containers" if tool is None else None)["widgets"]
        named = surface_discovery.live_keys(widgets)
        for key, item in named.items():
            self.seen.setdefault(scope, {}).setdefault(key, {**item, "first_state": state})
        self.states.append({"scope": scope, "state": state, "widgets": len(widgets), "interactive": len(named),
                            "anonymous": sorted(key for key in named if key.startswith("~"))})

    def dialogs(self) -> list[dict]:
        return [{"title": item["title"], "hwnd": item["hwnd"]} for item in native.native_dialogs_of(self.session.pid)]

    def problems(self, index: dict[str, dict[str, str]], scopes) -> list[str]:
        found: list[str] = []
        for scope in scopes:
            found += surface_discovery.compare_live(index.get(scope, {}), self.seen.get(scope, {}), scope=scope)
        return found

    def save(self, name: str = "live-surfaces.json") -> None:
        record = {"states": self.states, "seen": {scope: {key: {k: item.get(k) for k in ("class", "text", "path", "viewable", "first_state")}
                                                          for key, item in sorted(keys.items())} for scope, keys in self.seen.items()}}
        (self.context.evidence / name).write_text(json.dumps(record, indent=1), encoding="utf-8")


def _open_preferences(scan: Scan) -> None:
    session = scan.session
    before = {item["path"] for item in session.client.call("toplevels")["toplevels"]}
    session.click(None, "preferences_button")
    wait_until(lambda: {item["path"] for item in session.client.call("toplevels")["toplevels"]} - before, 15, "Preferences & Data to open")
    session.settle()
    scan.take(SHELL, "preferences-open")
    # The dialog covers the main window, so its picture is of its own window: the owned top-level that is not the main one.
    dialog = wait_until(lambda: next((item["hwnd"] for item in native.windows_of(session.pid)
                                      if item["class"] == "TkTopLevel" and item["owner"] and item["hwnd"] != session.hwnd), None),
                        10, "the Preferences window")
    session.screenshot("preferences", window=dialog)
    session.key("escape")
    wait_until(lambda: not ({item["path"] for item in session.client.call("toplevels")["toplevels"]} - before), 15, "Preferences & Data to close")
    session.settle()


def _engine_states(scan: Scan) -> None:
    session, report = scan.session, scan.context.report
    values = session.widget("tts", "voice_combo").get("values", [])
    for family in ENGINE_FAMILIES:
        choice = next((value for value in values if value.startswith(family)), None)
        report.check(f"the voice list offers a {family} voice", choice is not None, values[:6])
        if choice is None:
            continue
        session.select_combo("tts", "voice_combo", choice)
        report.equal(f"{family}: no dialog appears from choosing a voice", scan.dialogs(), [])
        scan.take("tts", f"voice-{family.lower()}")
        session.screenshot(f"tts-{family.lower()}")


def run_scan(context: Context, *, inject: dict | None = None) -> Scan:
    session = context.app(**({"inject_control": inject} if inject else {}))
    scan = Scan(session, context)
    scan.take(SHELL, "start")
    for tool in TOOLS:
        open_tool(session, tool)
        scan.take(tool, "opened")
    if inject is None:
        _open_preferences(scan)
        open_tool(session, "tts")
        _engine_states(scan)
    expect_clean_close(context, session)
    return scan


@scenario("inventory.live-surfaces", tool="launcher", layers=("native", "discovery"), tier="inventory", budget=420,
          summary="The shell, six tools, Preferences and each speech engine opened by real input; every interactive widget read live and held "
                  "against the reviewed index in coverage.json")
def live_surfaces(context: Context) -> None:
    index = live_index()
    scan = run_scan(context)
    scan.save()
    scopes = sorted({SHELL, *TOOLS, *index})
    problems = scan.problems(index, scopes)
    context.notes["live_surfaces"] = {scope: len(scan.seen.get(scope, {})) for scope in scopes}
    context.report.check("every live control is in the reviewed index, and every indexed control is still there", not problems, problems[:40])
    context.report.check("each scope showed at least one control", all(scan.seen.get(scope) for scope in (SHELL, *TOOLS)),
                         {scope: len(scan.seen.get(scope, {})) for scope in (SHELL, *TOOLS)})


@scenario("control.unmapped-live-control-is-caught", tool="launcher", layers=("control",), tier="control", budget=180,
          summary="A negative control: one extra button added to the Cover Image panel of a real instance must be reported as a live control "
                  "nobody mapped, and nothing else")
def unmapped_control(context: Context) -> None:
    index = live_index()
    scan = run_scan(context, inject={"tool": "cover", "text": PROBE_TEXT})
    scan.save("live-surfaces-with-probe.json")
    # This instance visits fewer states than the full scan, so indexed controls of the states it skips are absent here by design; what is
    # judged is the other direction, the one this control exists for.
    unmapped = [item for item in scan.problems(index, [SHELL, *TOOLS]) if "nobody has mapped" in item]
    caught = [item for item in unmapped if PROBE_TEXT in item]
    context.report.check("the injected button was seen as unmapped", len(caught) == 1, unmapped[:10])
    context.report.check("and it is the only unmapped control: a clean index otherwise", unmapped == caught, unmapped[:10])
