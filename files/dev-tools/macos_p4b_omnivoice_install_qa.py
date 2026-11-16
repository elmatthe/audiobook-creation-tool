"""Dev-only (macOS P4B): the REAL OmniVoice installer's tampered-download, cancel, failure and repair paths on this Mac,
in a disposable sandbox copy of the app. Never shipped; never imported by the application.

    .venv/bin/python -I -B files/dev-tools/macos_p4b_omnivoice_install_qa.py prepare
    .venv/bin/python -I -B files/dev-tools/macos_p4b_omnivoice_install_qa.py run
    .venv/bin/python -I -B files/dev-tools/macos_p4b_omnivoice_install_qa.py remove

Run from the repository root with the app's own interpreter. **Why a sandbox.** The production engine of this checkout
is installed and proved; breaking it to watch a repair would cost the owner a reinstall. So the installer is exercised
in ``files/dev-work/macos-p4b/install-qa/repo`` (ignored): a copy of this working tree's tracked files, an APFS clone of
the app's ``.venv`` without its engines (the parent the engine is built inside), and APFS clones (``clonefile(2)``: no
extra disk, independent copies) of the pinned wheels (from the P4A folder) and of the pinned model (from this
checkout's production model folder). Every source byte is hashed against the production manifest first. Nothing is
downloaded: every consent below is derived from a plan whose download total must be 0, and the opener is never given a
network. The sandbox's own code is imported (``sandbox/scripts`` first on ``sys.path``), so its ``repo_root`` is the
sandbox; it is run with this checkout's interpreter, whose base Python lies outside the sandbox.

**run** walks one engine through every state the installer can leave, each step through
``optional_setup.plan`` -> ``optional_setup_protocol.consent_fields`` -> ``RealAcquirer.acquire`` exactly as Install &
Continue does, and records the plan, the outcome, the receipt, the engine's assessed state, the wheel cache and any
process left behind:

  T0  a tampered wheel in the cache: the plan no longer counts it as verified (it would be downloaded again); restored.
  S0  fresh install, Cancel while pip installs: cancelled; the receipt says ``creating``; the engine is ``incomplete``;
      the verified wheels are kept; no pip or Python left running.
  S1  repair (its own consent scope), Cancel while the proof loads the model: cancelled; the environment is complete
      but unproved (no receipt): ``unchecked``; nothing recorded ready.
  S2  adoption of that environment: proved on this Mac's configured device and recorded, nothing downloaded or rebuilt.
  S3  damage (one installed package's record removed): ``broken``; repair downloads nothing, moves the old
      environment aside (kept), rebuilds, proves, records ready and only then discards the wheels.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path.cwd()
BOX = ROOT / "files" / "dev-work" / "macos-p4b" / "install-qa"
SANDBOX = BOX / "repo"
P4A_WHEELS = ROOT / "files" / "dev-work" / "omnivoice-feasibility" / "wheels"
CLONE_NOFOLLOW, CLONE_NOOWNERCOPY = 0x0001, 0x0002


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 22), b""):
            digest.update(block)
    return digest.hexdigest()


def clone(source: Path, target: Path) -> None:
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    libc.clonefile.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32)
    target.parent.mkdir(parents=True, exist_ok=True)
    if libc.clonefile(os.fsencode(source), os.fsencode(target), CLONE_NOFOLLOW | CLONE_NOOWNERCOPY) != 0:
        error = ctypes.get_errno()
        raise OSError(error, f"clonefile failed ({os.strerror(error)})", str(target))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True, default=str), encoding="utf-8")


def sandbox_modules():
    """The sandbox's own production modules (its repo_root is the sandbox)."""
    sys.path.insert(0, str(SANDBOX / "scripts"))
    from shared import optional_setup_protocol as proto
    from tts import omnivoice_runtime as ov
    from tts import omnivoice_setup as ovs
    from tts import optional_setup, optional_setup_health
    from tts.optional_setup_acquire import RealAcquirer

    assert ov.repo_root().resolve() == SANDBOX.resolve(), ov.repo_root()
    return proto, ov, ovs, optional_setup, optional_setup_health, RealAcquirer


def cmd_prepare(args) -> int:
    if sys.platform != "darwin":
        raise SystemExit("Apple Silicon Mac only")
    if SANDBOX.exists():
        raise SystemExit(f"{SANDBOX} exists; run remove first")
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.split(b"\0")
    copied = 0
    for raw in filter(None, listed):
        rel = os.fsdecode(raw)
        source = ROOT / rel
        if not source.is_file() or source.is_symlink():
            continue  # an owner-deleted tracked file stays absent in the sandbox too
        target = SANDBOX / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    # The parent environment, without any engine: an APFS clone of every file, links kept as links.
    (SANDBOX / ".venv").mkdir(parents=True)
    for entry in (ROOT / ".venv").iterdir():
        if entry.name == "engines":
            continue
        subprocess.run(["cp", "-c", "-R", "-P", str(entry), str(SANDBOX / ".venv" / entry.name)], check=True)
    sys.path.insert(0, str(SANDBOX / "scripts"))
    from tts import omnivoice_runtime as ov  # the sandbox's own

    placed = {"wheels": 0, "model": 0, "bytes": 0}
    cache = ov.ensure_runtime_dir(ov.wheel_cache_dir())
    for wheel in ov.wheels():
        source = P4A_WHEELS / wheel.filename
        if source.stat().st_size != wheel.size or sha256(source) != wheel.sha256:
            raise SystemExit(f"{source} is not its pinned bytes")
        clone(source, cache / wheel.filename)
        placed["wheels"] += 1
        placed["bytes"] += wheel.size
    production_model = ROOT / ov.model_dir().relative_to(SANDBOX)
    for name, entry in sorted(ov.model_spec()["files"].items()):
        source = production_model.joinpath(*name.split("/"))
        if source.stat().st_size != entry["size"] or sha256(source) != entry["sha256"]:
            raise SystemExit(f"{source} is not its pinned bytes")
        target = ov.model_dir().joinpath(*name.split("/"))
        ov.ensure_runtime_dir(target.parent)
        clone(source, target)
        placed["model"] += 1
        placed["bytes"] += entry["size"]
    record = {"sandbox": str(SANDBOX.relative_to(ROOT)), "tracked_files_copied": copied, "cloned": placed,
              "method": "clonefile(2), hashed against the sandbox's production manifest first"}
    write_json(BOX / "prepare.json", record)
    print(json.dumps(record, indent=1))
    return 0


def leftovers() -> list[str]:
    rows = subprocess.run(["ps", "-axo", "pid,command"], capture_output=True, text=True).stdout.splitlines()
    return [r for r in rows if str(SANDBOX) in r and "ps -axo" not in r]


def cmd_run(args) -> int:
    proto, ov, ovs, optional_setup, health, RealAcquirer = sandbox_modules()
    steps: dict = {}

    def facts():
        return health.facts(SANDBOX, [proto.OMNIVOICE], probe_hardware=True, cancel_check=lambda: False)

    def plan():
        return optional_setup.plan_to_json(optional_setup.plan([proto.OMNIVOICE], facts=facts()))

    def component(plan_json):
        entry = next(c for c in plan_json["components"] if c["id"] == proto.OMNIVOICE)
        return {k: entry.get(k) for k in ("state", "action", "consent_scope", "acquirable", "units")}

    def state() -> dict:
        return {"engine": ov.assess_engine().state, "receipt": ov.read_receipt(), "model_recorded": ov.model_recorded(),
                "wheels_cached": sorted(p.name for p in ov.wheel_cache_dir().glob("*.whl")).__len__()
                if ov.wheel_cache_dir().is_dir() else 0,
                "set_aside": sorted(p.name for p in ov.set_aside_root().glob("*")) if ov.set_aside_root().is_dir()
                else []}

    def acquire(name: str, *, cancel_when=None) -> dict:
        plan_json = plan()
        downloads = plan_json["totals"]["download"]["bytes"]
        row = {"plan": component(plan_json), "plan_download_bytes": downloads,
               "plan_disk_bytes": plan_json["totals"].get("disk", {}).get("bytes"),
               "acquire_units": plan_json["acquire_units"], "before": state()}
        if downloads != 0:
            row["outcome"] = "NOT RUN: the plan would download; this QA never downloads"
            steps[name] = row
            return row
        consent = proto.Consent(proto.new_token(), **{k: (tuple(v) if isinstance(v, list) else v)
                                                       for k, v in proto.consent_fields(plan_json).items()})
        events: list[dict] = []
        flag = {"at": None}

        def progress(event: dict) -> None:
            events.append(event)
            if cancel_when is not None and flag["at"] is None and cancel_when(event):
                # Cancel shortly after the stage started, while it is really running.
                threading.Timer(args.cancel_delay, lambda: flag.__setitem__("at", time.monotonic())).start()

        acquirer = RealAcquirer(python=Path(sys.executable))
        began = time.monotonic()
        try:
            report = acquirer.acquire(plan_json, consent, progress=progress,
                                      cancel_check=lambda: flag["at"] is not None)
            row["outcome"] = repr(report)
        except BaseException as exc:  # noqa: BLE001 - recorded
            row["outcome"] = f"{type(exc).__name__}: {exc}"
        ended = time.monotonic()
        row["seconds"] = round(ended - began, 1)
        row["cancel_to_return_s"] = None if flag["at"] is None else round(ended - flag["at"], 2)
        row["network_fetches"] = [getattr(o, "fetched", None) for o in acquirer.openers]
        row["progress_tail"] = [e.get("message") or e.get("step") for e in events][-12:]
        time.sleep(0.5)
        row["after"] = state()
        row["processes_left"] = leftovers()
        steps[name] = row
        print(name, row["outcome"][:160], row["after"]["engine"], row["after"]["receipt"].get("stage"),
              row["cancel_to_return_s"], row["processes_left"], flush=True)
        return row

    # T0: one cached wheel no longer its pinned bytes is not counted as verified.
    wheel = ov.wheels()[0]
    path = ov.wheel_cache_dir() / wheel.filename
    original = path.read_bytes()
    before = plan()["totals"]["download"]["bytes"]
    with open(path, "ab") as handle:
        handle.write(b"tampered")
    after = plan()["totals"]["download"]["bytes"]
    path.unlink()
    clone(P4A_WHEELS / wheel.filename, path)
    restored = sha256(path) == wheel.sha256 and path.read_bytes() == original
    steps["T0-tampered-wheel"] = {"wheel": wheel.filename, "download_bytes_before": before,
                                  "download_bytes_tampered": after, "expected_extra": wheel.size,
                                  "restored": restored, "verdict": "PASS" if (before == 0 and after == wheel.size
                                                                              and restored) else "FAIL"}
    print("T0", steps["T0-tampered-wheel"]["verdict"], before, after, flush=True)

    pip_running = lambda e: "Installing the OmniVoice packages" in str(e.get("message", ""))  # noqa: E731
    proof_running = lambda e: e.get("unit") == "omnivoice-engine" and e.get("step") == "verify"  # noqa: E731
    acquire("S0-install-cancel-during-pip", cancel_when=pip_running)
    acquire("S1-repair-cancel-during-proof", cancel_when=proof_running)
    acquire("S2-adopt")
    # S3: damage -- one installed package's record removed -- then repair.
    site = ov.site_packages(ov.venv_dir())
    victim = sorted(site.glob("soundfile-*.dist-info"))
    if victim:
        shutil.rmtree(victim[0])
    steps["S3-damage"] = {"removed": [p.name for p in victim], "engine_after": ov.assess_engine().state}
    acquire("S3-repair-after-damage")
    write_json(BOX / "run.json", steps)
    expected = {
        "S0-install-cancel-during-pip": ("AcquisitionReport(completed=False", ov.ENGINE_INCOMPLETE),
        "S1-repair-cancel-during-proof": ("AcquisitionReport(completed=False", ov.ENGINE_UNCHECKED),
        "S2-adopt": ("AcquisitionReport(completed=True", ov.ENGINE_READY),
        "S3-repair-after-damage": ("AcquisitionReport(completed=True", ov.ENGINE_READY),
    }
    verdicts = {}
    for name, (outcome, engine) in expected.items():
        row = steps[name]
        cancelled_ok = "completed=False" not in outcome or "detail='cancelled'" in str(row.get("outcome", ""))
        verdicts[name] = "PASS" if (str(row.get("outcome", "")).startswith(outcome) and cancelled_ok
                                    and row["after"]["engine"] == engine
                                    and not row["processes_left"] and row["plan_download_bytes"] == 0) else "FAIL"
    verdicts["T0-tampered-wheel"] = steps["T0-tampered-wheel"]["verdict"]
    verdicts["S3-damage-detected"] = "PASS" if steps["S3-damage"]["engine_after"] == ov.ENGINE_BROKEN else "FAIL"
    write_json(BOX / "verdicts.json", verdicts)
    print(json.dumps(verdicts, indent=1))
    return 0 if all(v == "PASS" for v in verdicts.values()) else 1


def cmd_remove(args) -> int:
    if leftovers():
        raise SystemExit("a process still runs from the sandbox; nothing removed")
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    print("removed", SANDBOX.relative_to(ROOT))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    p = sub.add_parser("run")
    p.add_argument("--cancel-delay", type=float, default=2.0)
    sub.add_parser("remove")
    args = parser.parse_args(argv)
    return {"prepare": cmd_prepare, "run": cmd_run, "remove": cmd_remove}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
