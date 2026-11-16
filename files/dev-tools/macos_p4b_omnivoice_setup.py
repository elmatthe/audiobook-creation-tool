"""Dev-only (macOS P4B): adopt the P4A OmniVoice bytes into this checkout's production locations, then install the engine
through ACT's own consented optional-voice installer. Never shipped; never imported by the application.

    <app python> files/dev-tools/macos_p4b_omnivoice_setup.py adoption-plan [--out <json>]
    <app python> files/dev-tools/macos_p4b_omnivoice_setup.py adopt --consent <token> [--record <json>]
    <app python> files/dev-tools/macos_p4b_omnivoice_setup.py install-plan [--out <json>]
    <app python> files/dev-tools/macos_p4b_omnivoice_setup.py install --download-bytes <n> [--record <json>]

Run from the repository root with the app's own interpreter (``.venv/bin/python``).

**Why.** The P4A experiment acquired and verified the exact files the production Mac manifest now pins (86 wheels of
``tts/omnivoice_manifest.json``'s ``darwin_arm64`` set, and the 11 model files of its pinned snapshot) into the ignored
``files/dev-work/omnivoice-feasibility/``. Downloading 3.5 GB again would buy nothing. The P4A consent covered only that
disposable experiment, so placing those bytes where the production app looks is its own owner decision, bound to a
token.

**adoption-plan** (read-only). For every pinned file: the P4A source, the production destination
(``omnivoice_runtime.wheel_cache_dir`` / ``model_dir``), the pinned size and SHA-256, and the destination's state. The
plan's canonical JSON hashes to the **adoption token**. Nothing is written except ``--out``.

**adopt --consent <token>.** The plan is made again and must hash to the token (anything that changed since -- a
manifest, a source, a destination -- needs a new token). Each source is hashed and must be its pinned bytes; it is then
placed with ``clonefile(2)`` (APFS copy-on-write: no extra disk, and the two files are independent from then on) under a
temporary name in a folder made by ``omnivoice_runtime.ensure_runtime_dir`` (no link anywhere on the way), hashed again
where it landed, and renamed into place without replacing anything. A destination already holding the pinned bytes is
left as it is; one holding anything else stops the adoption. Sources are only read. No record the installer owns (the
wheel record, the model verification record, the receipt) is written here: the production installer makes each of them
after its own checks.

**install-plan / install.** ``optional_setup.plan(["omnivoice"])`` -- what Install & Continue shows -- is printed. With
``install`` a consent is derived from that same plan (``optional_setup_protocol.consent_fields``, what confirming the
window does) and spent once on ``optional_setup_acquire.RealAcquirer``, which records the model, builds
``.venv/engines/omnivoice`` offline from the verified wheels, proves it on this Mac's configured device and only then
writes the receipt. ``--download-bytes`` must equal the plan's download total: the owner's approval of an amount binds.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "scripts"))

from shared import optional_setup_protocol as proto  # noqa: E402
from tts import omnivoice_runtime as ov  # noqa: E402

P4A = ROOT / "files" / "dev-work" / "omnivoice-feasibility"
P4A_TOKEN = "7932d4ef5b3ed0e531b958b9729f1de77ce27de37c755de290d5d9b896f62f4c"
CLONE_NOFOLLOW, CLONE_NOOWNERCOPY = 0x0001, 0x0002


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 22), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return Path(os.path.relpath(path, ROOT)).as_posix()


def rows() -> list[dict]:
    """Every file to adopt: source, destination, pinned size and SHA-256 (from the PRODUCTION manifest)."""
    if sys.platform != "darwin" or not ov.platform_supported():
        raise SystemExit("adoption is for an Apple Silicon Mac only")
    out = []
    for wheel in ov.wheels():
        out.append({"kind": "wheel", "name": wheel.filename, "source": relative(P4A / "wheels" / wheel.filename),
                    "destination": relative(ov.wheel_cache_dir() / wheel.filename), "size": wheel.size,
                    "sha256": wheel.sha256})
    spec = ov.model_spec()
    p4a_model = P4A / "model" / spec["repo"].replace("/", "--") / spec["revision"]
    for name, entry in sorted(spec["files"].items()):
        out.append({"kind": "model", "name": name, "source": relative(p4a_model.joinpath(*name.split("/"))),
                    "destination": relative(ov.model_dir().joinpath(*name.split("/"))), "size": entry["size"],
                    "sha256": entry["sha256"]})
    return out


def destination_state(row: dict) -> str:
    path = ROOT / row["destination"]
    if not os.path.lexists(path):
        return "absent"
    if path.is_symlink() or not path.is_file():
        return "not-a-file"
    if path.stat().st_size != row["size"]:
        return "different"
    return "identical" if sha256(path) == row["sha256"] else "different"


def make_plan() -> dict:
    plan_rows = rows()
    for row in plan_rows:
        source = ROOT / row["source"]
        row["source_present"] = source.is_file() and not source.is_symlink() and source.stat().st_size == row["size"]
        row["destination_state"] = destination_state(row)
    return {"schema": "act-macos-p4b-omnivoice-adoption", "version": 1, "method": "apfs-clonefile",
            "p4a_acquisition_token": P4A_TOKEN, "model": {"repo": ov.model_spec()["repo"],
                                                          "revision": ov.model_spec()["revision"],
                                                          "manifest_sha256": ov.model_manifest_sha256()},
            "packages_sha256": ov.packages_sha256(), "rows": plan_rows,
            "totals": {"files": len(plan_rows), "bytes": sum(r["size"] for r in plan_rows),
                       "to_place": sum(1 for r in plan_rows if r["destination_state"] == "absent"),
                       "already_identical": sum(1 for r in plan_rows if r["destination_state"] == "identical"),
                       "blocking": sum(1 for r in plan_rows if r["destination_state"] in ("different", "not-a-file")
                                       or not r["source_present"])}}


def token_of(plan: dict) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def clone(source: Path, target: Path) -> None:
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    libc.clonefile.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32)
    if libc.clonefile(os.fsencode(source), os.fsencode(target), CLONE_NOFOLLOW | CLONE_NOOWNERCOPY) != 0:
        error = ctypes.get_errno()
        raise OSError(error, f"clonefile failed ({os.strerror(error)}); nothing was copied instead", str(target))


def adopt(consent: str) -> dict:
    plan = make_plan()
    if token_of(plan) != consent:
        raise SystemExit("the adoption plan is not the one the token was given for; run adoption-plan again")
    if plan["totals"]["blocking"]:
        raise SystemExit("the plan has a missing source or a destination holding other bytes; nothing was adopted")
    record = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "token": consent, "rows": []}
    for row in plan["rows"]:
        source, target = ROOT / row["source"], ROOT / row["destination"]
        entry = {"name": row["name"], "kind": row["kind"], "before": row["destination_state"]}
        if row["destination_state"] == "identical":
            entry["action"] = "kept (already the pinned bytes)"
            record["rows"].append(entry)
            continue
        if sha256(source) != row["sha256"]:
            raise SystemExit(f"{row['source']} is not its pinned bytes; stopped (nothing further adopted)")
        folder = ov.ensure_runtime_dir(target.parent)  # refuses a link anywhere from the runtime folder down
        part = folder / f".{target.name}.adopt-{os.getpid()}"
        if os.path.lexists(part):
            os.unlink(part)
        clone(source, part)
        try:
            if sha256(part) != row["sha256"]:
                raise SystemExit(f"{row['destination']} did not land as its pinned bytes; stopped")
            if os.path.lexists(target):
                raise SystemExit(f"{row['destination']} appeared while adopting; stopped")
            os.link(part, target)  # no-clobber publication (APFS): fails rather than replace
        finally:
            if os.path.lexists(part):
                os.unlink(part)
        entry.update(action="cloned", sha256=row["sha256"], size=row["size"])
        record["rows"].append(entry)
    record["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    record["after"] = make_plan()["totals"]
    return record


def facts_for_omnivoice():
    from tts import optional_setup_health

    return optional_setup_health.facts(ROOT, [proto.OMNIVOICE], probe_hardware=True, cancel_check=lambda: False)


def install_plan() -> dict:
    from tts import optional_setup

    return optional_setup.plan_to_json(optional_setup.plan([proto.OMNIVOICE], facts=facts_for_omnivoice()))


def install(download_bytes: int) -> dict:
    from tts.optional_setup_acquire import RealAcquirer

    plan_json = install_plan()
    total = plan_json["totals"]["download"]["bytes"]
    if total != download_bytes:
        raise SystemExit(f"the plan would download {total} bytes, not the approved {download_bytes}; nothing was done")
    if not plan_json["acquire_units"]:
        return {"plan": plan_json, "acquisition": "nothing to acquire"}
    consent = proto.Consent(proto.new_token(), **{k: (tuple(v) if isinstance(v, list) else v)
                                                   for k, v in proto.consent_fields(plan_json).items()})
    events: list[dict] = []
    began = time.monotonic()
    acquirer = RealAcquirer(python=Path(sys.executable))
    report = acquirer.acquire(plan_json, consent, progress=events.append, cancel_check=lambda: False)
    return {"plan": plan_json, "consent": consent.to_json(), "seconds": round(time.monotonic() - began, 1),
            "report": repr(report), "fetched": [getattr(o, "fetched", None) for o in acquirer.openers],
            "progress_tail": events[-40:], "receipt": ov.read_receipt(), "engine": ov.assess_engine().state,
            "model": ov.model_status(), "after_plan": install_plan()["components"]}


def write(path, data) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1, sort_keys=True, default=str), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("adoption-plan")
    p.add_argument("--out", type=Path)
    p = sub.add_parser("adopt")
    p.add_argument("--consent", required=True)
    p.add_argument("--record", type=Path)
    p = sub.add_parser("install-plan")
    p.add_argument("--out", type=Path)
    p = sub.add_parser("install")
    p.add_argument("--download-bytes", type=int, required=True)
    p.add_argument("--record", type=Path)
    args = parser.parse_args(argv)
    if args.command == "adoption-plan":
        plan = make_plan()
        write(args.out, {**plan, "token": token_of(plan)})
        print(json.dumps({"token": token_of(plan), **plan["totals"]}, indent=1))
    elif args.command == "adopt":
        record = adopt(args.consent)
        write(args.record, record)
        print(json.dumps(record["after"], indent=1))
    elif args.command == "install-plan":
        plan_json = install_plan()
        write(args.out, plan_json)
        print(json.dumps({"acquire_units": plan_json["acquire_units"], "totals": plan_json["totals"],
                          "components": [c for c in plan_json["components"] if c["id"] == proto.OMNIVOICE]},
                         indent=1, default=str))
    else:
        result = install(args.download_bytes)
        write(args.record, result)
        print(json.dumps({k: result.get(k) for k in ("seconds", "engine", "model", "report")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
