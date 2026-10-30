"""optional_setup_client.py — what the first-run wizard and Install & Continue call to plan and install voices.

v0.7.0 release. One small, GUI-independent client over the existing optional-setup protocol
(``shared.optional_setup_protocol``): it writes a request, starts the contained setup worker in the app's own ``.venv``
(``WorkerRun``: Job Object, one terminal result), forwards its events, honours a cancel, and returns the result. It also
turns a plan into the disclosure a person reads before agreeing, and the consent their **Install** click gives.

The flow every caller follows (owner Option B, 2026-10-27):

1. :func:`plan` -- a read-only worker run for the chosen components: what is ready, what is missing or damaged, and
   exactly what installing would download, reuse and occupy. Nothing is acquired.
2. :func:`disclosure` -- that plan as text, plus which choices cannot be installed now and why.
3. Only after a live click on the final *Install* button: :func:`install` with :func:`consent_for` of that same plan.
   The worker re-plans, refuses unless its fresh plan has exactly the terms that were shown, spends the consent once,
   acquires within the byte budget it fixes, proves the result, and answers once.

Standard library only (the first-run wizard imports it before the app's environment exists); starting a worker imports
the app's process-containment module on demand, exactly as ``WorkerRun`` does.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Iterable, Optional

from shared import optional_setup_protocol as proto

#: A plan run probes Kokoro/Chatterbox (bounded at 300 s each by the health module) and reads the disk.
PLAN_TIMEOUT_S = 15 * 60
#: An install can fetch about 14 GB; a slow connection gets most of a day. Cancel is always available.
INSTALL_TIMEOUT_S = 20 * 3600

#: Readiness states a consent can act on (install / repair).
ACQUIRABLE = (proto.MISSING, proto.DAMAGED)


class SetupUnavailable(Exception):
    """The worker could not be started at all (no app environment yet, containment refused, ...)."""


def run(repo_root: Path, action: str, components: Iterable[str], *, consent: Optional[proto.Consent] = None,
        on_event: Optional[Callable[[dict], None]] = None, cancelled: Callable[[], bool] = lambda: False,
        timeout_s: float = PLAN_TIMEOUT_S, poll_s: float = 0.2) -> dict:
    """Run one worker request to its terminal result (a ``proto.make_result`` dict). Never raises for an outcome."""
    root = Path(repo_root)
    session = proto.new_token()
    try:
        request = proto.new_request(action, components, session=session, consent=consent,
                                    probe_hardware=action == proto.ACTION_PLAN)
        path = proto.write_request(root, request)
        spec = proto.worker_launch(root, path, session)
        worker = proto.WorkerRun(root, spec, request, on_event=on_event)
        worker.start()
    except Exception as exc:  # noqa: BLE001 - reported to the person, never a crash of the wizard
        raise SetupUnavailable(str(exc)) from exc
    deadline = time.monotonic() + timeout_s
    while worker.process.poll() is None:
        if cancelled():
            return worker.stop()
        if time.monotonic() >= deadline:
            return worker.wait(0)
        time.sleep(poll_s)
    return worker.wait(30)


def plan(repo_root: Path, components: Iterable[str], **kwargs) -> dict:
    return run(repo_root, proto.ACTION_PLAN, components, **kwargs)


def install(repo_root: Path, shown_plan: dict, consent: proto.Consent, **kwargs) -> dict:
    kwargs.setdefault("timeout_s", INSTALL_TIMEOUT_S)
    return run(repo_root, proto.ACTION_INSTALL, consent.components, consent=consent, **kwargs)


def consent_for(shown_plan: dict) -> proto.Consent:
    """The consent a person gives by confirming *shown_plan* (fresh id; terms derived exactly as the worker checks)."""
    fields = proto.consent_fields(shown_plan)
    return proto.Consent(proto.new_token(), fields["plan_context"], tuple(fields["components"]), fields["scopes"],
                         tuple(fields["units"]), tuple(fields["unknown_units"]), fields["download_bytes"],
                         fields["acquisition_fingerprint"])


def estimate_texts(components: Iterable[str]) -> dict:
    """``{component: "4.9 GB"}``: the pre-venv estimate of each choice on its own (manifest figures only; the planner's
    estimate reads no model, probes nothing and opens no connection). Imported lazily: it is not needed to run a worker.
    """
    from tts import optional_setup
    out = {}
    for component in components:
        data = optional_setup.plan_to_json(optional_setup.estimate([component]))
        out[component] = figure_text(data["totals"]["download"])
    return out


# --------------------------------------------------------------------------- #
# Reading a plan
# --------------------------------------------------------------------------- #
def format_bytes(count: Optional[int]) -> str:
    if count is None:
        return "unknown"
    for unit, size in (("GB", 10**9), ("MB", 10**6), ("KB", 10**3)):
        if count >= size:
            return f"{count / size:.1f} {unit}"
    return f"{count} bytes"


def figure_text(figure: Optional[dict]) -> str:
    if not figure or figure.get("bytes") is None:
        return "unknown"
    prefix = "about " if figure.get("basis") == proto.APPROXIMATE else ""
    return prefix + format_bytes(figure["bytes"])


def selected(shown_plan: dict) -> list[dict]:
    return [c for c in shown_plan["components"] if c["selected"]]


def acquirable(shown_plan: dict) -> tuple[str, ...]:
    """The chosen components this plan can install or repair."""
    return tuple(c["id"] for c in selected(shown_plan) if c["readiness"] in ACQUIRABLE)


def ready(shown_plan: dict) -> tuple[str, ...]:
    return tuple(c["id"] for c in selected(shown_plan) if c["readiness"] == proto.READY)


def blocked(shown_plan: dict) -> list[tuple[str, str]]:
    """``(label, why)`` for each chosen component that can neither be used nor installed now."""
    return [(c["label"], c.get("reason") or c["readiness"]) for c in selected(shown_plan)
            if c["readiness"] not in ACQUIRABLE + (proto.READY,)]


def needs_install(shown_plan: dict) -> bool:
    return bool(acquirable(shown_plan)) and bool(shown_plan.get("acquire_units"))


def disclosure(shown_plan: dict) -> str:
    """The plan as the text a person reads before choosing Install: per component, the totals and the limits."""
    units = {u["id"]: u for u in shown_plan["units"]}
    lines: list[str] = []
    for comp in selected(shown_plan):
        state = comp["readiness"]
        if state == proto.READY:
            lines.append(f"{comp['label']}: already installed and working - nothing to download.")
            continue
        if state not in ACQUIRABLE:
            lines.append(f"{comp['label']}: cannot be installed now ({comp.get('reason') or state}).")
            continue
        verb = "Repair" if state == proto.DAMAGED else "Install"
        lines.append(f"{comp['label']}: {verb} - download {figure_text(comp.get('download'))}.")
        for unit_id in comp["units"]:
            unit = units.get(unit_id)
            if unit is None or unit_id not in shown_plan.get("acquire_units", ()):
                continue
            shared = " (shared by both Qwen3 choices; fetched once)" if len(unit["components"]) > 1 else ""
            if unit_id.startswith("kokoro-voice:"):
                continue  # the nine small voice files are summed in the component line
            lines.append(f"    - {unit['label']}: {figure_text(unit['download'])}{shared}")
    totals = shown_plan["totals"]
    lines.append("")
    lines.append(f"Total download: {figure_text(totals['download'])}.  Disk space used: {figure_text(totals['disk'])}"
                 f" (plus {figure_text(totals['temp'])} temporary).")
    if totals.get("reused", {}).get("bytes"):
        lines.append(f"Reused from files already on this computer: {figure_text(totals['reused'])}.")
    hardware = shown_plan.get("hardware") or {}
    if any(c["id"].startswith("qwen3") for c in selected(shown_plan)) and hardware.get("qwen3"):
        lines.append(hardware["qwen3"])
    lines.append("Downloads come only from the pinned sources this version was tested with; every file is checked "
                 "by size and SHA-256. Nothing is downloaded until you choose Install, and Cancel keeps what is "
                 "already working.")
    return "\n".join(lines)


def result_text(result: dict) -> str:
    """One readable sentence for a terminal result."""
    state = result.get("state")
    if state == proto.SUCCEEDED:
        return "Installed and checked: " + ", ".join(proto.LABELS[c] for c in result.get("verified", ())) + "."
    error = result.get("error") or {}
    message = error.get("message") or state or "unknown problem"
    if state == proto.CANCELLED_STATE:
        return "Cancelled. Anything already working was kept. " + message
    return message


def progress_text(event: dict) -> tuple[str, Optional[float]]:
    """A worker event as ``(line, fraction-or-None)`` for a progress display."""
    kind = event.get("kind")
    payload = event.get("payload") or {}
    if kind == "progress":
        done, total = payload.get("done") or 0, payload.get("total") or 0
        message = payload.get("message") or payload.get("step") or ""
        if total:
            return f"{message} ({format_bytes(done)} of {format_bytes(total)})", min(1.0, done / total)
        return message, None
    if kind == "started":
        return "Checking what is already on this computer...", None
    if kind == "plan":
        return "Plan confirmed by the installer.", None
    return "", None
