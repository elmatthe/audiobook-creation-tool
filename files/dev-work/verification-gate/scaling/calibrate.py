"""Calibrate the continuous route's minimum saving (v0.7.2 Phase 7B; run once, before final qualification).

The threshold only chooses which of two byte-identical routes a book takes, so it is purely a speed choice. The route
saves the seeking route's repeated prefix decoding (P, every chapter's start added up) and costs a pipe for the whole
book (about 1.4 decodes' worth per second of book, measured; ``m4b_continuous.PREFIX_PER_BOOK_SECOND`` = 2.0 rounds it
up) plus a fixed cost per book (the decoder and the packet scan). So books are ordered by the estimated saving
S = P - 2.0 x D (D the book's duration), and the threshold is the smallest S at which the route is measurably not slower.
The books are the representative small books Phase 7A named (10 chapters of 1.5 s, 10 of 6.6 s), their neighbours, and
books of a few long chapters (2, 3, 5, 7 and 12 chapters of a 10 to 20 minute book), where P is small for their length.

**The rule is fixed here, before any measurement of this version, and is not adjusted afterwards** (two earlier attempts
ordered books by P alone; the second's partial data showed a 3-chapter 10-minute book 24 % slower with P above 600 s, so
P alone does not predict the cost, and they were stopped before any threshold was taken from them):

1. Each book runs three arms per repetition, in rotating order: legacy (seeking route), continuous, and legacy again as
   a same-session control. Every output must equal the pinned reference digest; any difference stops the calibration.
2. ``break_even`` is the smallest calibration S such that every calibration book with an S of that or more has a
   continuous median wall time no greater than its legacy median and a continuous median process-tree CPU no greater
   than its legacy median.
3. ``threshold = max(600, 2 x break_even rounded up to a whole minute)``. The factor of two and the 600 s floor are the
   conservative margin: a book is moved to the new route only where it is measurably not slower, with room for machines
   slower to start processes than this one. If no calibration book qualifies, the result is BLOCKED for the owner.

    python calibrate.py --ffmpeg <ffmpeg.exe> --out <folder inside the repository's ignored evidence> [--reps 10]

Writes ``calibration.json`` and ``calibration.md`` into ``--out``; produced MP3s are deleted after hashing.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402
import recipe  # noqa: E402

BOOKS = ["small2_600000", "small3_200000", "small5_120000", "scale10", "small10_3000", "small10_4500", "route10",
         "small10_9000", "small10_13500", "small10_20000", "small7_86000", "small15_9000", "small20_9000",
         "small12_50000"]
PER_BOOK_SECOND = 2.0
ARMS = ["legacy", "continuous", "legacy2"]
FLOOR_SECONDS = 600.0


def threshold_from(rows: list[dict]) -> tuple[float | None, float | None]:
    """(break_even, threshold) by the rule in the module docstring; (None, None) when no book qualifies."""
    ordered = sorted(rows, key=lambda row: row["saved_seconds"])
    for index, row in enumerate(ordered):
        if all(other["wall_ratio"] <= 1.0 and other["cpu_ratio"] <= 1.0 for other in ordered[index:]):
            break_even = row["saved_seconds"]
            return break_even, max(FLOOR_SECONDS, 60.0 * math.ceil(2.0 * break_even / 60.0))
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--reps", type=int, default=8)
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    log_file = root / "progress.log"

    def log(message: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {message}"
        with open(log_file, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)

    reference = common.load_reference()
    pair = common.ffmpeg_pair(args.ffmpeg)
    build = common.pinned_build(reference, pair)
    if build is None:
        log("BLOCKED: this FFmpeg pair is not one the reference was pinned on")
        return 2
    books = {name: common.ensure_fixture(name, build, pair, log) for name in BOOKS}
    hashes = {name: common.sha256(path) for name, path in books.items()}
    runs: list[dict] = []
    for rep in range(args.reps):
        for offset, name in enumerate(BOOKS):
            arms = ARMS[(rep + offset) % 3:] + ARMS[:(rep + offset) % 3]
            for arm in arms:
                label = f"{name}-{arm}-{rep + 1}"
                record = common.bench(root, label, [books[name]], pair,
                                      route="legacy" if arm.startswith("legacy") else "continuous", timeout=900)
                results = record.get("results")
                if results is None:
                    log(f"FAILED run {label}: exit {record['exit']} {record['stderr'][-400:]}")
                    return 1
                digest = common.output_digest(results["files"])
                pinned = build["outputs"][f"{name}/split/preserve/q2"]["digest"]
                if digest != pinned or results["outcome"]["states"] != ["SUCCEEDED"]:
                    log(f"FAILED run {label}: outputs {digest[:12]} != pinned {pinned[:12]} or {results['outcome']['states']}")
                    return 1
                if any(source["sha256"] != hashes[name] for source in results["sources"]):
                    log(f"FAILED run {label}: the source changed")
                    return 1
                took = [d["continuous"] for d in results["route"]["decisions"]]
                if took != [arm == "continuous"]:
                    log(f"FAILED run {label}: route {took} was not the one asked for")
                    return 1
                common.remove_outputs(record)
                job = results["job"]
                runs.append({"book": name, "arm": arm, "rep": rep + 1, "load_before_pct": record["load_before_pct"],
                             "wall_s": results["timing"]["first_attempt_s"],
                             "cpu_s": job["run_user_s"] + job["run_kernel_s"],
                             "scan_s": results["timing"]["scan_s"], "processes": job["run_processes"],
                             "peak_job_commit": job["after_run"]["peak_job_commit"],
                             "hb_max_s": results["heartbeat"]["max_s"]})
                log(f"{label}: {runs[-1]['wall_s']:.3f} s wall, {runs[-1]['cpu_s']:.2f} s CPU, load {record['load_before_pct']} %")
    rows = []
    for name in BOOKS:
        def med(arm, key, name=name):
            return statistics.median(r[key] for r in runs if r["book"] == name and r["arm"] == arm)
        row = {"book": name, "prefix_seconds": recipe.prefix_seconds(name),
               "saved_seconds": recipe.saved_seconds(name, PER_BOOK_SECOND),
               "chapters": build["fixtures"][name]["chapters"], "duration_s": build["fixtures"][name]["probed_duration"],
               **{f"{arm}_wall_s": med(arm, "wall_s") for arm in ARMS}, **{f"{arm}_cpu_s": med(arm, "cpu_s") for arm in ARMS},
               "scan_s": med("continuous", "scan_s")}
        row["wall_ratio"] = row["continuous_wall_s"] / row["legacy_wall_s"]
        row["cpu_ratio"] = row["continuous_cpu_s"] / row["legacy_cpu_s"]
        row["noise"] = abs(row["legacy2_wall_s"] / row["legacy_wall_s"] - 1.0)
        rows.append(row)
    break_even, threshold = threshold_from(rows)
    verdict = {"rule": __doc__.split("**The rule is fixed here")[1].split("    python calibrate.py")[0].strip(),
               "pair": pair, "reps": args.reps, "rows": rows, "break_even_prefix_seconds": break_even,
               "threshold_seconds": threshold, "status": "PASS" if threshold is not None else "BLOCKED", "runs": runs}
    (root / "calibration.json").write_text(json.dumps(verdict, indent=1), encoding="utf-8")
    lines = ["# Continuous-route threshold calibration", "",
             f"FFmpeg {pair['version']} ({pair['ffmpeg_sha256'][:12]}); {args.reps} repetitions per arm, interleaved.", "",
             "| Book | Chapters | Duration | Prefix s | Saving S | Legacy wall | Continuous wall | Ratio | Legacy CPU | Continuous CPU | CPU ratio | A-vs-A noise | Scan |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['book']} | {r['chapters']} | {r['duration_s']:.1f} | {r['prefix_seconds']:.0f} | {r['saved_seconds']:.0f} | "
                     f"{r['legacy_wall_s']:.3f} | {r['continuous_wall_s']:.3f} | {r['wall_ratio']:.3f} | "
                     f"{r['legacy_cpu_s']:.2f} | {r['continuous_cpu_s']:.2f} | {r['cpu_ratio']:.3f} | {r['noise']:.3f} | "
                     f"{r['scan_s']:.3f} |")
    lines += ["", f"break_even = {break_even} s of estimated saving; threshold = {threshold} s ({verdict['status']})."]
    (root / "calibration.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"break_even {break_even}, threshold {threshold}")
    return 0 if threshold is not None else 2


if __name__ == "__main__":
    sys.exit(main())
