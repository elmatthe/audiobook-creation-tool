"""Pilot calibration for the Plan 01 evaluation (dev-only).

A small, clearly labelled technical run that establishes the common Qwen profile (device, dtype,
attention, chunk ceiling, join) before any comparison recording exists: a preset on the short
passage, an English Dylan smoke check, an Aiden pass over the complete long passage for duration and
generation-cap headroom, and one transcript-conditioned clone once a transcript is owner-approved.

Pilot output lives under ``runs/<id>/pilot/`` with its own manifest and is never listed in the
comparison index. A technically fine pilot says nothing about quality.
"""
from __future__ import annotations

import json

import qwen_eval_cli as cli
import qwen_eval_core as core


def pilot_rows(clone_reference: str) -> list[dict]:
    def preset(name: str, suite: str) -> dict:
        row = core.long_row(core.GROUP_QWEN_PRESET, name)
        row.update(row_id=f"pilot-qwen-preset-{name.lower()}-{suite}", suite="pilot", display=f"{name}-{suite}",
                   out_folder="pilot/presets")
        return row

    clone = core.long_row(core.GROUP_QWEN_CLONE, clone_reference)
    clone.update(row_id=f"pilot-qwen-clone-{clone_reference.lower()}-short", suite="pilot",
                 display=f"{clone_reference}-clone-short", reference_name=clone_reference,
                 out_folder="pilot/clones")
    def baseline(row_id: str, folder: str, **extra) -> dict:
        row = next(r for r in core.short_rows() if r["row_id"] == row_id)
        row.update(row_id=f"pilot-{row_id}-short", suite="pilot", out_folder=folder, **extra)
        row["display"] = f"{row['display']}-short"
        return row

    return [preset("Aiden", "short"), preset("Dylan", "short"), preset("Aiden", "long"), clone,
            baseline("kokoro-am_michael", "pilot/kokoro"),
            baseline("chatterbox-female-1", "pilot/chatterbox", reference_name="Female-1")]


def stage_pilot(run: "cli.Run", selector: str = "all", max_chars: int | None = None) -> int:
    profile = cli.load_profile(run)
    if max_chars:
        profile = dict(profile, max_chars=max_chars)
    if not run.dry_run:
        cli.save_profile(run, profile, {"note": "pilot profile; final common profile recorded after calibration"})
    snapshot = cli.reference_snapshot()
    approved = [n for n, _ in core.REFERENCE_VOICE_IDS
                if cli.approved_transcript(run, n, snapshot[n]["sha256"])[0]]
    rows = pilot_rows(approved[0] if approved else core.REFERENCE_VOICE_IDS[0][0])
    manifest = core.Manifest(run.dir / "pilot" / "manifest.jsonl")
    manifest.declare(rows, save=not run.dry_run)
    wanted = set(cli.selected_groups(selector))
    plan = {
        "short": [r for r in rows if r["row_id"].endswith("-short") and r["group"] == core.GROUP_QWEN_PRESET],
        "long": [r for r in rows if r["row_id"].endswith("-long")],
        "clone": [r for r in rows if r["group"] == core.GROUP_QWEN_CLONE],
    }
    for name, suite_text, mode in (("short", "pilot-short", "custom_voice"), ("long", "pilot-long", "custom_voice"),
                                   ("clone", "pilot-short", "clone")):
        subset = [manifest.get(r["row_id"]) for r in plan[name] if r["group"] in wanted]
        if subset:
            cli.run_qwen_group(run, subset, mode=mode, suite_text=suite_text, profile=profile, manifest=manifest,
                               snapshot=snapshot, label=f"pilot-{name}")
    for engine in (core.GROUP_KOKORO, core.GROUP_CHATTERBOX):
        subset = [manifest.get(r["row_id"]) for r in rows if r["group"] == engine and engine in wanted]
        if subset:
            cli.run_root_group(run, subset, engine=engine, suite_text="pilot-short", profile=profile,
                               manifest=manifest, snapshot=snapshot, label=f"pilot-{engine}")
    lines = ["# Pilot summary (technical calibration only)", "",
             f"Profile: `{json.dumps({k: profile[k] for k in ('dtype', 'attn', 'device', 'max_chars', 'gap_ms', 'end_silence_ms')})}`", "",
             "| Row | Status | Audible s | Gen s | RTF | Peak alloc MiB | Max cap headroom | Warnings |",
             "|---|---|---|---|---|---|---|---|"]
    for row in manifest.rows.values():
        timing = row.get("timing") or {}
        headroom = max((c.get("cap_headroom") or 0 for c in row.get("chunk_results") or []), default=0)
        lines.append(f"| {row['row_id']} | {row['status']}{': ' + row['status_reason'][:80] if row['status_reason'] else ''} | "
                     f"{timing.get('audible_s', '-')} | {timing.get('gen_s', '-')} | {timing.get('rtf', '-')} | "
                     f"{timing.get('peak_alloc_mib', '-')} | {headroom} | {len(row.get('warnings') or [])} |")
    if not run.dry_run:
        core.atomic_write_text(run.dir / "pilot" / "PILOT-SUMMARY.md", "\n".join(lines) + "\n")
        cli.say(f"pilot summary: {run.dir / 'pilot' / 'PILOT-SUMMARY.md'}")
    return 0
