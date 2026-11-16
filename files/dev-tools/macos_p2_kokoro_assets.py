"""Dev-only (v0.8.x P2): put the pinned Kokoro-82M model, its nine voices and spaCy's English model in place in one
checkout through ACT's own consented acquisition -- after reusing any byte-identical copy already on this computer.

    <app python> files/dev-tools/macos_p2_kokoro_assets.py --show                 # what would happen; changes nothing
    <app python> files/dev-tools/macos_p2_kokoro_assets.py --acquire --record <json> [--reuse-from <hf snapshot>]

Run it from the checkout that should receive the files (P2 used a disposable worktree, so the owner's own app keeps the
optional voices they left unchecked). Every file is ACT's pinned identity (``tts.model_assets``: repository, commit,
size, SHA-256); the in-tree Hugging Face cache of *this* checkout is the destination.

* **Reuse.** A file named in ``--reuse-from`` (a Hugging Face snapshot folder of the pinned commit) is copied in only if
  it is exactly the pinned size and SHA-256; the copy is hashed again where it lands. The source is only read.
* **The plan and the consent.** The engine's packages are proved to load first (``optional_setup_health.facts``, as the
  setup worker does), then ``optional_setup.plan(["kokoro"])`` -- the plan the setup window shows -- is printed:
  every unit, where it comes from, its size and where it goes. With ``--acquire`` a consent is derived from that same
  plan (``optional_setup_protocol.consent_fields``, what confirming the window does) and spent once on
  ``optional_setup_acquire.RealAcquirer``: only the plan's URLs, a byte budget fixed by the consent, size and SHA-256
  for every file, spaCy's wheel installed offline with ``--require-hashes`` into this interpreter's environment.
* **The record** (``--record``): what was reused, the plan, the acquisition report, and every file's state afterwards.

Nothing here touches settings, receipts of other engines, Chatterbox, Qwen3, OmniVoice or Whisper. Never shipped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "scripts"))

from shared import optional_setup_protocol as proto  # noqa: E402
from tts import model_assets, optional_setup  # noqa: E402
from tts import qwen3_runtime as rt  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def reuse(source: Path) -> list[dict]:
    kokoro = model_assets.kokoro_set()
    target = model_assets.snapshot_dir(kokoro)
    done = []
    for name, (size, sha256) in sorted(kokoro.files.items()):
        state, _detail = model_assets.file_state(kokoro, name)
        candidate = source.joinpath(*name.split("/"))
        row = {"file": name, "size": size, "sha256": sha256, "before": state, "source": str(candidate)}
        if state == model_assets.READY or not candidate.is_file():
            row["reused"] = False
            done.append(row)
            continue
        if os.path.getsize(candidate) != size or _sha256(candidate) != sha256:
            row.update(reused=False, why="the copy here is not the pinned file")
            done.append(row)
            continue
        destination = target.joinpath(*name.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        part = destination.with_name(destination.name + ".reuse-part")
        shutil.copyfile(candidate, part)
        if _sha256(part) != sha256:
            part.unlink()
            raise SystemExit(f"{name}: the copy did not hash to the pinned SHA-256")
        os.replace(part, destination)
        row.update(reused=True, after=model_assets.file_state(kokoro, name)[0])
        done.append(row)
    return done


def show(plan_json: dict) -> list[dict]:
    rows = []
    for unit in plan_json["units"]:
        if unit["id"] not in plan_json["acquire_units"]:
            continue
        rows.append({"unit": unit["id"], "label": unit.get("label"), "source": unit.get("source"),
                     "download": unit["download"], "disk": unit.get("disk")})
    print(json.dumps({"root": str(rt.repo_root()), "kokoro_destination": str(model_assets.snapshot_dir(
        model_assets.kokoro_set())), "spacy_kept_wheel": str(model_assets.spacy_store_dir()),
        "spacy_installs_into": sys.prefix, "components": plan_json["components"], "acquire": rows,
        "totals": plan_json["totals"]}, indent=1, default=str))
    return rows


def install_spacy() -> dict:
    """spaCy's English model into this interpreter's environment, by the acquirer's own means.

    ``RealAcquirer`` refuses an environment outside the checkout it installs for (in the app the two are one tree); a
    worktree runs on its main checkout's ``.venv``, so this step is done here with the same functions: the scoped,
    byte-budgeted opener that allows only the approved URL, ``qwen3_setup.download_file`` (size and SHA-256), and
    ``spacy_store.offline_install_command`` (``--no-index --no-deps --require-hashes``). The wheel is kept in this
    checkout's model store, never the main checkout's."""
    from tts import optional_setup_acquire as acq
    from tts import qwen3_setup

    store = model_assets.spacy_store_dir()
    store.mkdir(parents=True, exist_ok=True)
    wheel = store / model_assets.SPACY_WHEEL_NAME
    opener = acq.ScopedOpener([model_assets.SPACY_WHEEL_URL], None, acq.Budget(model_assets.SPACY_WHEEL_SIZE))
    began = time.monotonic()
    if model_assets.kept_spacy_wheel() is None:
        qwen3_setup.download_file(model_assets.SPACY_WHEEL_URL, wheel, model_assets.SPACY_WHEEL_SIZE,
                                  model_assets.SPACY_WHEEL_SHA256, opener=opener, cancel_check=lambda: False)
    requirement = store / "spacy-english-requirement.txt"
    requirement.write_text(model_assets.spacy_requirement_line(wheel), encoding="utf-8")
    tail: list[str] = []
    code = qwen3_setup.run_command(model_assets.spacy_offline_install_command(Path(sys.executable), requirement),
                                   env=acq._pip_environment(), cwd=store, on_line=tail.append,
                                   cancel_check=lambda: False)
    requirement.unlink()
    return {"seconds": round(time.monotonic() - began, 1), "requested": opener.requested,
            "budget_used": opener.budget.used, "kept": str(model_assets.kept_spacy_wheel()), "pip_exit": code,
            "pip_tail": tail[-8:], "installed": model_assets.installed_version(model_assets.SPACY_ENGLISH),
            "problem": model_assets.spacy_problem(model_assets.installed_version)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--acquire", action="store_true")
    parser.add_argument("--reuse-from", type=Path)
    parser.add_argument("--record", type=Path)
    args = parser.parse_args()
    record: dict = {"root": str(rt.repo_root()), "python": sys.executable, "prefix": sys.prefix,
                    "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if args.acquire and args.reuse_from:
        record["reused"] = reuse(args.reuse_from)
    # What the setup worker does first: prove the engine's packages load (a child process), then plan with that.
    from tts import optional_setup_health

    # The proof runs in the environment this interpreter belongs to (a worktree has no .venv of its own and runs on its
    # main checkout's): ACT's own probe, against that checkout, read-only.
    environment_root = Path(sys.prefix).resolve().parent
    ok, why = optional_setup_health.kokoro_health(environment_root, cancel_check=lambda: False)
    record["health_proof"] = {"environment_root": str(environment_root), "ok": ok, "why": why}
    facts = optional_setup_health.facts(rt.repo_root(), [proto.KOKORO], probe_hardware=False,
                                        cancel_check=lambda: False, health={proto.KOKORO: ok})
    record["health"] = dict(facts.health)
    plan_json = optional_setup.plan_to_json(optional_setup.plan([proto.KOKORO], facts=facts))
    record["plan"] = show(plan_json)
    if args.acquire and plan_json["acquire_units"]:
        from tts.optional_setup_acquire import RealAcquirer

        consent = proto.Consent(proto.new_token(), **{k: (tuple(v) if isinstance(v, list) else v)
                                                       for k, v in proto.consent_fields(plan_json).items()})
        record["consent"] = consent.to_json()
        began = time.monotonic()
        acquirer = RealAcquirer(python=Path(sys.executable))
        report = acquirer.acquire(plan_json, consent, progress=lambda event: None, cancel_check=lambda: False)
        record["acquisition"] = {"seconds": round(time.monotonic() - began, 1), "report": repr(report),
                                 "fetched": [getattr(o, "fetched", None) for o in acquirer.openers]}
    if args.acquire and model_assets.installed_version(model_assets.SPACY_ENGLISH) is None:
        record["spacy_step"] = install_spacy()
    kokoro = model_assets.kokoro_set()
    record["after"] = {name: model_assets.file_state(kokoro, name)[0] for name in sorted(kokoro.files)}
    record["spacy_english"] = model_assets.installed_version(model_assets.SPACY_ENGLISH)
    record["kept_spacy_wheel"] = str(model_assets.kept_spacy_wheel())
    record["after_plan"] = optional_setup.plan_to_json(optional_setup.plan([proto.KOKORO], facts=facts))["components"]
    if args.record:
        args.record.parent.mkdir(parents=True, exist_ok=True)
        args.record.write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"after": record["after"], "spacy_english": record["spacy_english"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
