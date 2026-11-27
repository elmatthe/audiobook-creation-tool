"""A reviewed synthetic stand-in for the acceptance runner (v0.8.2 Phase 1A-1 R2 positive recipe "scripted-acceptance-runner").

It stands where acceptance_runner.py stands in a synthetic gate tree and writes what its validated data file
(``scripted.json`` beside it; helpers/routine_context.py validates it) tells it to. Only these exact bytes are the recipe.
"""
import argparse, json, os, sys, time
from pathlib import Path
parser = argparse.ArgumentParser()
for name in ("report", "token", "evidence", "scratch"):
    parser.add_argument("--" + name)
parser.add_argument("--only", action="append", default=[])
args = parser.parse_args()
script = json.loads((Path(__file__).parent / "scripted.json").read_text(encoding="utf-8"))
if script.get("hang"):
    time.sleep(120)
if script.get("no_report"):
    sys.exit(script.get("exit", 0))
evidence = Path(args.evidence)
entries = []
for identifier in args.only:
    folder = evidence / identifier
    (folder / "screenshots").mkdir(parents=True)
    (folder / "app-actions.jsonl").write_text("{}", encoding="utf-8")
    (folder / "screenshots" / "done.png").write_bytes(bytes.fromhex("89504e470d0a1a0a") + bytes(32))
    entry = {"id": identifier, "tool": "mp3-tool", "layers": ["native", "media"], "tier": "journey", "status": "PASS", "reason": "", "seconds": 1.0,
             "checks": [{"name": "output", "ok": True, "detail": ""}], "outputs": [{"name": "a.mp3", "bytes": 1, "sha256": "ab"}],
             "fixtures": [{"id": "t", "kind": "mp3-track", "validation": [{"name": "decodes", "ok": True}]}],
             "screenshots": [{"name": "done.png", "path": identifier + "/screenshots/done.png"}], "native_inputs": 3, "sessions": ["app"], "notes": {}}
    entry.update(script.get("entry", {}))
    entries.append(entry)
report = {"schema_version": 1, "token": script.get("token", args.token), "registered": script.get("registered", args.only), "scenarios": entries,
          "finished": True, "unknown": [], "runtime_before": {"a": 1}, "runtime_after": script.get("after", {"a": 1}),
          "dialog_history": {"preflight": {"verdict": "contained"}, "before": 0, "after": 0, "added": {}}}
report.update(script.get("report", {}))
Path(args.report).write_text(json.dumps(report), encoding="utf-8")
sys.exit(script.get("exit", 0))
