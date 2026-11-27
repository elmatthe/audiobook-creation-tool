"""A reviewed synthetic stand-in for a qualification scenario's runner (v0.8.2 Phase 1A-1 R2 positive recipe "scenario-runner").

It stands where scaling/qualify.py stands in a synthetic gate tree. Everything it does beyond the fixed steps of a scenario
run (progress, identity, runs, verdict, exit) comes from ``scenario.json`` beside it, as data in a closed vocabulary: no
code is formatted into this file.

``scenario.json``: {"runs": int, "verdict": null | str | object, "code": int, "before": [operation, ...]}. An operation is
one of: ["unlink", <file in the scenario's output folder>]; ["write", <file in the output folder>, <text>];
["write-identity", <scenario>, <head or null for the measured HEAD>]; ["write-verdict", <object>]; ["touch", <path in the
tree>]; ["write-path", <path in the tree>, <text>]; ["sleep", <seconds, at most 300>]; ["sleeper", <pid file in the tree>]
(a Python child that sleeps 120 s, left behind on purpose).
"""
import json
import subprocess
import sys
import time
from pathlib import Path

out = Path(sys.argv[sys.argv.index("--out") + 1])
data = json.loads((Path(__file__).parent / "scenario.json").read_text(encoding="utf-8"))
out.mkdir(parents=True)
(out / "progress.log").write_text("started\n")
head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
(out / "identity.json").write_text(json.dumps({"scenario": "m4b-scaling", "head": head}))
(out / "runs.json").write_text(json.dumps([{"label": f"run-{n}"} for n in range(data["runs"])]))
for operation in data["before"]:
    kind, *args = operation
    if kind == "unlink":
        (out / args[0]).unlink()
    elif kind == "write":
        (out / args[0]).write_text(args[1])
    elif kind == "write-identity":
        (out / "identity.json").write_text(json.dumps({"scenario": args[0], "head": head if args[1] is None else args[1]}))
    elif kind == "write-verdict":
        (out / "verdict.json").write_text(json.dumps(args[0]))
    elif kind == "touch":
        Path(args[0]).write_text("x")
    elif kind == "write-path":
        Path(args[0]).write_text(args[1])
    elif kind == "sleep":
        time.sleep(args[0])
    elif kind == "sleeper":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        Path(args[0]).write_text(str(child.pid), encoding="ascii")
verdict = data["verdict"]
if isinstance(verdict, str):
    (out / "verdict.json").write_text(verdict)
elif verdict is not None:
    (out / "verdict.json").write_text(json.dumps(verdict))
sys.exit(data["code"])
