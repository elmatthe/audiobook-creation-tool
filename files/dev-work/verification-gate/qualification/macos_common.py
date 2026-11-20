"""What the darwin P1B scenarios share (owner's revised acceptance, 2026-11-15): cases run exactly as journeys are.

Each case is a function of a ``journeys.common.Context`` -- an isolated application instance, real fixtures, the in-process
driver, real pictures -- run by the acceptance runner's own ``run_one`` (so tear-down, orphan checks and evidence are the
journeys'), but never registered as a journey: the scenario set Windows shares is unchanged. Every check a case makes
becomes a check of the scenario under the case's family, and each case is one recorded run. A desktop, toolchain or
containment prerequisite that is missing makes the scenario BLOCKED, never a pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE_DIR = HERE.parent
sys.path.insert(0, str(GATE_DIR))

import acceptance_runner  # noqa: E402
from qualification import common  # noqa: E402


class Case:
    def __init__(self, family: str, name: str, run, *, tool: str, tier: str = "journey", summary: str = "", budget: int = 600) -> None:
        self.family, self.name, self.run_function, self.tool, self.tier = family, name, run, tool, tier
        self.summary, self.budget = summary or name, budget


def run_cases(q: common.Scenario, cases: list[Case]) -> list[dict]:
    """Run each case as a journey is run; return the runner's entries (the evidence lives below ``q.root / 'cases'``)."""
    if sys.platform != "darwin":
        raise common.Blocked("a macOS scenario")
    from adapters.macos import containment, native_input as native
    from helpers import media_fixtures, media_oracle as oracle
    from journeys.common import Scenario

    status = native.desktop_status()
    if not status.ok:
        raise common.Blocked(f"no logged-in Aqua session: {status.reason}")
    try:
        tools = oracle.pinned_toolchain(common.REPO_ROOT)
        manifest = media_fixtures.load_manifest(GATE_DIR / "fixtures" / "manifest.json")
    except (oracle.ToolchainUnavailable, oracle.FixtureInvalid) as exc:
        raise common.Blocked(f"{type(exc).__name__}: {exc}") from None
    evidence, scratch = q.root / "cases", q.root / "w"
    evidence.mkdir()
    scratch.mkdir()
    try:
        q.check("containment: a session's process group ends with it", bool(containment.preflight(scratch / "containment")))
    except containment.ContainmentUnavailable as exc:
        raise common.Blocked(f"ContainmentUnavailable: {exc}") from None
    entries = []
    with native.DesktopLease():
        for index, case in enumerate(cases):
            scenario = Scenario(f"{case.family}.{case.name}", case.tool, ("native", "media"), case.tier, case.summary, case.run_function,
                                case.budget)
            q.log(f"case {scenario.id}: start")
            entry = acceptance_runner.run_one(scenario, evidence_root=evidence, scratch_root=scratch, tools=tools, manifest=manifest,
                                              index=index)
            entries.append(entry)
            (evidence / scenario.id / "entry.json").write_text(json.dumps(entry, indent=1, default=str), encoding="utf-8")
            q.runs.append({"label": scenario.id, "exit": 0 if entry["status"] == "PASS" else 1, "ended": "exited",
                           "seconds": entry.get("seconds"), "folder": f"cases/{scenario.id}"})
            for check in entry.get("checks", []):
                q.check(f"{case.family} / {check['name']}", check.get("ok"), check.get("detail", ""))
            q.check(f"{case.family} / {case.name}: the case ended PASS", entry["status"] == "PASS", entry.get("reason", ""))
            survivors = [item for item in entry.get("teardown", []) if item.get("survivors")]
            q.check(f"{case.family} / {case.name}: nothing it started survived", not survivors, survivors)
            q.log(f"case {scenario.id}: {entry['status']} {entry.get('reason', '')[:300]}")
    return entries
