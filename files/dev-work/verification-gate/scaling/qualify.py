"""The m4b-scaling qualification scenario (v0.7.2 Phase 7B): the Converter's split route at scale, against frozen budgets.

Run by ``verify.py --mode qualification --scenario m4b-scaling`` (or directly, for development, into an ignored folder):

    python qualify.py --out <run folder>/qualification [--ffmpeg <ffmpeg.exe>]

It never runs as part of a routine gate. It takes roughly three hours of machine time and about 1 GB of ignored fixture
cache, and should run in a quiet session: wall times are compared within the session (production and candidate
interleaved), and process-tree CPU is reported beside them because it is far less sensitive to other load.

**Identity.** The exact FFmpeg/ffprobe pair is hashed and must be one ``reference.json`` was pinned on; otherwise the
result is BLOCKED (byte identity is pinned per build). The Python, the Git HEAD and the code's own digest are recorded.
Every fixture is checked against its pinned SHA-256 before use and every run checks the source is unchanged after.

**Containment.** ``--out`` must be a new folder inside the repository's ignored gate outputs. Each run is a separate
``bench_run.py`` process that proves, before anything is converted, that the application's configured output base
resolves inside its own run folder, and refuses otherwise. The owner's Downloads output tree is compared before and after
the whole qualification. Produced MP3s are hashed, then deleted; ``results.json`` of every run is kept.

**Budgets** (Phase 7A record section 8, approved for Phase 7B, frozen here; never moved after a failed run):

* T1  6 h / 48 chapters, cover, Preserve: median wall and process-tree CPU both at least 2.0x faster.
* T1b 1,000 short chapters, cover, Preserve: median wall at least 1.8x, CPU at least 2.0x faster.
* T2  below the threshold (the minimum estimated saving, m4b_continuous.MIN_SAVED_PREFIX_SECONDS) the seeking route is
      chosen and outputs are unchanged; above it, representative small books are no more than 10 % slower (median wall)
      beyond the measured same-session legacy-vs-legacy noise.
* T3  6 h and 12 h books: per-chapter wall time slope at most 0.1 s per hour of prefix; last-quarter / first-quarter median
      at most 1.15.
* T4  audio held by the route at most 1 MiB at any moment; no PCM on disk; peak job commit within the seeking route's
      peak plus the decoder process's own peak plus that 1 MiB.
* T5  peak staged bytes no higher than the seeking route's.
* T6  UI heartbeat p99 at most 0.25 s in every continuous run, and no stall over 2 s in one.
* T7  Cancel during a late chapter settles within 2 s with every owned process stopped and reaped.
* T8  every output of every case equals the pinned reference digest; ineligible books take the seeking route.

The 12-hour book is measured three times and its ratio is reported; no throughput budget applies to it.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402
import recipe  # noqa: E402

MIB = 1 << 20
NEEDED = ["route10", "scale10", "scale100", "scale500", "scale1000", "long6_48", "long12_24", "noelst", "mono22k",
          "s48k", "r96k", "small2_600000", "small3_200000", "small5_120000", "small10_3000", "small10_4500",
          "small10_9000", "small10_13500", "small10_20000", "small7_86000", "small15_9000", "small20_9000",
          "small12_50000"]
CALIBRATION_BOOKS = ["small2_600000", "small3_200000", "small5_120000", "scale10", "small10_3000", "small10_4500",
                     "route10", "small10_9000", "small10_13500", "small10_20000", "small7_86000", "small15_9000",
                     "small20_9000", "small12_50000"]


class Qualification:
    def __init__(self, root: Path, pair: dict, build: dict, threshold: float, per_book_second: float,
                 python: str) -> None:
        self.root = root
        self.pair = pair
        self.build = build
        self.threshold = threshold
        self.per_book_second = per_book_second
        self.python = python
        self.runs: list[dict] = []
        self.checks: list[dict] = []
        self.books: dict[str, Path] = {}
        self.hashes: dict[str, str] = {}
        self.progress = root / "progress.log"

    # ------------------------------------------------------------------ bookkeeping
    def log(self, message: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
        with open(self.progress, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)

    def check(self, name: str, ok: bool, detail: str, **facts) -> bool:
        self.checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail, **facts})
        self.log(f"check {name}: {'PASS' if ok else 'FAIL'} - {detail}")
        return ok

    def pinned(self, name: str, mode="split", metadata="preserve") -> str | None:
        entry = self.build["outputs"].get(f"{name}/{mode}/{metadata}/q2")
        return None if entry is None else entry["digest"]

    # ------------------------------------------------------------------ one run
    def run(self, case: str, name: str, route: str, *, extra=(), mode="split", metadata="preserve",
            expect_continuous: bool | None = None, expect_states=("SUCCEEDED",), timeout=3600.0) -> dict | None:
        label = f"{case}-{len(self.runs) + 1:03d}"
        record = common.bench(self.root, label, [self.books[name]], self.pair, route=route, timeout=timeout,
                              extra=extra, mode=mode, metadata=metadata, python=self.python)
        results = record.get("results")
        summary = {"label": label, "case": case, "book": name, "route": route, "mode": mode, "metadata": metadata,
                   "extra": list(extra), "exit": record["exit"], "load_before_pct": record["load_before_pct"]}
        if results is None:
            summary["error"] = record["stderr"][-1500:] or record["stdout"][-600:]
            self.runs.append(summary)
            self.check(f"run:{label}", False, f"{case} {name} {route}: the harness produced no results "
                                              f"(exit {record['exit']}): {summary['error'][-300:]}")
            return None
        digest = common.output_digest(results["files"]) if results["files"] else None
        decisions = results["route"]["decisions"]
        job = results["job"]
        decoder_peaks = [d for d in results["decoders"]]
        summary.update({
            "states": results["outcome"]["states"], "digest": digest, "files": len(results["files"]),
            "max_file_bytes": max((f["bytes"] for f in results["files"]), default=0),
            "continuous": [d["continuous"] for d in decisions], "reasons": [d["reason"] for d in decisions],
            "wall_s": results["timing"]["first_attempt_s"], "retry_s": results["timing"]["retry_s"],
            "cancel_to_settled_s": results["timing"]["cancel_to_settled_s"],
            "cpu_s": job["run_user_s"] + job["run_kernel_s"], "processes": job["run_processes"],
            "active_after": job["active_after"], "peak_job_commit": job["after_run"]["peak_job_commit"],
            "peak_staged_bytes": results["disk"]["peak_staged_bytes"], "write_bytes": job["run_write_bytes"],
            "heartbeat": results["heartbeat"], "stalls_over_1s": len(results["stall_diagnostics"]),
            "decoders": decoder_peaks, "alive_at_settle": results["outcome"]["alive_at_settle"],
            "alive_at_settle_retry": results["outcome"]["alive_at_settle_retry"],
            "killed": results["outcome"]["killed"], "outputs_while_paused": results["timing"]["outputs_while_paused"],
            "failures": results["outcome"]["failures"], "load_during_pct": results["timing"]["machine_load_pct_during"],
            "scan_s": results["timing"]["scan_s"], "containment": results["containment"],
            "segments": [{"start": s["start"], "wall_s": s["wall_s"], "attempt": s["attempt"],
                          "decoder_wait_s": s.get("decoder_wait_s"), "encoder_wait_s": s.get("encoder_wait_s")}
                         for s in results["segments"]],
            "sources_unchanged": all(s["sha256"] == s["sha256_before"] == self.hashes[name] for s in results["sources"]),
            "environment": results["environment"],
        })
        if results["stall_diagnostics"]:
            summary["stall_diagnostics"] = results["stall_diagnostics"]
        self.runs.append(summary)
        problems = []
        if tuple(summary["states"]) != tuple(expect_states):
            problems.append(f"states {summary['states']} != {list(expect_states)}")
        # A whole-book run asks no route question at all (the route is a split-only choice): no decision is the answer.
        expected_route = [] if mode == "whole" else [expect_continuous]
        if expect_continuous is not None and summary["continuous"] != expected_route:
            problems.append(f"route {summary['continuous']} ({summary['reasons']}) != {expected_route}")
        if not summary["sources_unchanged"]:
            problems.append("a source changed")
        contained = results["containment"]
        if contained["reservations_refused"] or contained["unexpected_entries"]:
            problems.append(f"containment {contained['reservations_refused']} {contained['unexpected_entries']}")
        if summary["alive_at_settle"] or summary["alive_at_settle_retry"]:
            problems.append(f"children alive at settle {summary['alive_at_settle']} {summary['alive_at_settle_retry']}")
        if summary["active_after"] != 1:
            problems.append(f"{summary['active_after']} processes still in the job after the run")
        if problems:
            self.check(f"run:{label}", False, f"{case} {name} {route}: " + "; ".join(problems))
        common.remove_outputs(record)
        self.log(f"{label} {case} {name} {route}: {summary['states']} {summary['wall_s']} s wall, "
                 f"{summary['cpu_s']:.1f} s CPU, route {summary['continuous']}, digest {str(digest)[:12]}, "
                 f"hb max {summary['heartbeat']['max_s']}, load {summary['load_before_pct']} %")
        return summary

    def identical(self, summary: dict | None, name: str, *, mode="split", metadata="preserve") -> bool:
        pinned = self.pinned(name, mode, metadata)
        ok = summary is not None and pinned is not None and summary["digest"] == pinned
        if summary is not None:
            summary["identical_to_reference"] = ok
        return ok

    # ------------------------------------------------------------------ the cases
    def compatibility(self) -> None:
        """T8 and the below-threshold half of T2: every route and mode against the pinned production outputs."""
        cases = [
            ("route10", "auto", "split", "preserve", False),     # below the threshold: the seeking route
            ("scale10", "auto", "split", "preserve", False),
            ("route10", "continuous", "split", "preserve", True),
            ("route10", "continuous", "split", "replace", True),
            ("route10", "continuous", "split", "strip", True),
            ("route10", "auto", "whole", "preserve", False),     # whole book never takes the route
            ("noelst", "continuous", "split", "preserve", True),
            ("mono22k", "continuous", "split", "preserve", True),
            ("s48k", "continuous", "split", "preserve", True),
            ("r96k", "continuous", "split", "preserve", False),  # a rate LAME does not take: always the seeking route
            ("scale100", "auto", "split", "preserve", True),
            ("scale500", "auto", "split", "preserve", True),
        ]
        for name, route, mode, metadata, continuous in cases:
            summary = self.run("compat", name, route, mode=mode, metadata=metadata, expect_continuous=continuous,
                               timeout=1800)
            self.check(f"T8:{name}:{mode}:{metadata}:{route}", self.identical(summary, name, mode=mode, metadata=metadata),
                       f"outputs {None if summary is None else str(summary['digest'])[:16]} vs pinned "
                       f"{str(self.pinned(name, mode, metadata))[:16]}; route continuous={continuous} expected")

    def small_books(self, reps: int) -> None:
        """T2 above the threshold: representative small books, interleaved with a same-session legacy control."""
        def saving(name):
            return recipe.saved_seconds(name, self.per_book_second)

        # A book within a second of the threshold could fall either side on its probed (not planned) duration.
        above = [name for name in CALIBRATION_BOOKS if saving(name) >= self.threshold + 1.0]
        below = [name for name in CALIBRATION_BOOKS if saving(name) < self.threshold - 1.0]
        for name in below:
            summary = self.run("t2-below", name, "auto", expect_continuous=False, timeout=900)
            self.check(f"T2:below:{name}", self.identical(summary, name),
                       f"estimated saving {saving(name):.0f} s < {self.threshold:.0f} s: seeking route, outputs unchanged")
        above.append("scale100")  # a 150-second book of 100 chapters: small, and well above any threshold
        for name in above:
            arms = {"legacy": [], "auto": [], "legacy2": []}
            for rep in range(reps):
                order = ["legacy", "auto", "legacy2"]
                order = order[rep % 3:] + order[:rep % 3]
                for arm in order:
                    summary = self.run("t2-above", name, "legacy" if arm.startswith("legacy") else "auto",
                                       expect_continuous=(arm == "auto"), timeout=900)
                    if summary is not None and self.identical(summary, name):
                        arms[arm].append(summary)
                    else:
                        self.check(f"T8:t2:{name}", False, f"{arm} run not identical to the reference")
            if not all(len(v) == reps for v in arms.values()):
                self.check(f"T2:above:{name}", False, "not every run completed identically")
                continue
            legacy = statistics.median(s["wall_s"] for s in arms["legacy"])
            once = statistics.median(s["wall_s"] for s in arms["auto"])
            control = statistics.median(s["wall_s"] for s in arms["legacy2"])
            noise = abs(control / legacy - 1.0)
            ratio = once / legacy
            self.check(f"T2:above:{name}", ratio <= 1.10 + noise,
                       f"estimated saving {saving(name):.0f} s: continuous median {once:.3f} s vs legacy {legacy:.3f} s "
                       f"(ratio {ratio:.3f}; legacy-vs-legacy noise {noise:.3f}; limit {1.10 + noise:.3f})",
                       legacy_s=legacy, continuous_s=once, control_s=control, ratio=ratio, noise=noise)

    def throughput(self, name: str, reps: int, budget_id: str | None, wall_min: float | None,
                   cpu_min: float | None) -> dict:
        arms = {"legacy": [], "auto": []}
        for rep in range(reps):
            for arm in (("legacy", "auto") if rep % 2 == 0 else ("auto", "legacy")):
                summary = self.run(f"tput-{name}", name, arm, expect_continuous=(arm == "auto"), timeout=4 * 3600)
                identical = self.identical(summary, name)
                self.check(f"T8:{name}:{arm}:{rep + 1}", identical, "outputs equal the pinned reference" if identical
                           else "outputs differ from the pinned reference")
                if summary is not None and identical:
                    arms[arm].append(summary)
        out = {"book": name, "reps": reps, "complete": all(len(v) == reps for v in arms.values())}
        if not out["complete"]:
            if budget_id:
                self.check(budget_id, False, f"{name}: not every run completed identically")
            return out
        for key in ("wall_s", "cpu_s"):
            out[f"legacy_{key}"] = statistics.median(s[key] for s in arms["legacy"])
            out[f"continuous_{key}"] = statistics.median(s[key] for s in arms["auto"])
            out[f"{key}_speedup"] = out[f"legacy_{key}"] / out[f"continuous_{key}"]
        out["runs"] = {arm: [s["label"] for s in values] for arm, values in arms.items()}
        out["arms"] = arms
        if budget_id:
            ok = out["wall_s_speedup"] >= wall_min and out["cpu_s_speedup"] >= cpu_min
            self.check(budget_id, ok, f"{name}: median wall {out['legacy_wall_s']:.1f} -> {out['continuous_wall_s']:.1f} s "
                                      f"({out['wall_s_speedup']:.2f}x, need {wall_min}x); CPU {out['legacy_cpu_s']:.1f} -> "
                                      f"{out['continuous_cpu_s']:.1f} s ({out['cpu_s_speedup']:.2f}x, need {cpu_min}x)",
                       **{k: v for k, v in out.items() if k not in ("arms", "runs")})
        else:
            self.log(f"{name}: wall {out['wall_s_speedup']:.2f}x, CPU {out['cpu_s_speedup']:.2f}x (reported, no budget)")
        return out

    def slope_and_quarters(self, tput: dict) -> None:
        """T3 on the continuous runs: no per-chapter cost growth with position."""
        name = tput["book"]
        for summary in tput.get("arms", {}).get("auto", []):
            points = [(s["start"] / 3600.0, s["wall_s"]) for s in summary["segments"] if s["attempt"] == 0]
            n = len(points)
            mean_x = sum(x for x, _ in points) / n
            mean_y = sum(y for _, y in points) / n
            slope = (sum((x - mean_x) * (y - mean_y) for x, y in points)
                     / sum((x - mean_x) ** 2 for x, _ in points))
            walls = [y for _, y in points]
            quarter = max(1, n // 4)
            ratio = statistics.median(walls[-quarter:]) / statistics.median(walls[:quarter])
            self.check(f"T3:{name}:{summary['label']}", slope <= 0.1 and ratio <= 1.15,
                       f"slope {slope:.3f} s per hour of prefix (limit 0.1); last/first quarter median {ratio:.3f} "
                       "(limit 1.15)", slope=slope, quarter_ratio=ratio)
        for summary in tput.get("arms", {}).get("legacy", [])[:1]:
            points = [(s["start"] / 3600.0, s["wall_s"]) for s in summary["segments"] if s["attempt"] == 0]
            mean_x = sum(x for x, _ in points) / len(points)
            mean_y = sum(y for _, y in points) / len(points)
            slope = (sum((x - mean_x) * (y - mean_y) for x, y in points) / sum((x - mean_x) ** 2 for x, _ in points))
            self.log(f"{name}: the seeking route's slope for comparison: {slope:.3f} s per hour of prefix")

    def resources(self, tputs: list[dict]) -> None:
        """T4 and T5 from the throughput runs."""
        for tput in tputs:
            arms = tput.get("arms")
            if not arms:
                continue
            legacy_peak = max(s["peak_job_commit"] for s in arms["legacy"])
            # Sampled every 0.5 s, so a sampled peak can miss the real one. Both routes stage exactly the same files in the
            # same passes (the audio pass's MP3, then the cover pass's copy beside it), so the seeking route's real peak is
            # at least two copies of its largest chapter; the larger of that and what was sampled is its peak.
            legacy_staged = max(max(s["peak_staged_bytes"] for s in arms["legacy"]),
                                2 * max(s["max_file_bytes"] for s in arms["legacy"]))
            legacy_writes = max(s["write_bytes"] for s in arms["legacy"])
            for summary in arms["auto"]:
                decoder = summary["decoders"][0] if summary["decoders"] else {}
                buffered = decoder.get("peak_buffered", 0)
                decoder_peak = decoder.get("peak_commit") or 0
                envelope = legacy_peak + decoder_peak + MIB
                self.check(f"T4:{tput['book']}:{summary['label']}",
                           0 < buffered <= MIB and summary["peak_job_commit"] <= envelope
                           and summary["write_bytes"] <= legacy_writes * 1.05,
                           f"audio held {buffered} bytes (limit {MIB}); job peak {summary['peak_job_commit'] / 1e6:.1f} MB vs "
                           f"seeking {legacy_peak / 1e6:.1f} MB + decoder {decoder_peak / 1e6:.1f} MB + 1 MiB = "
                           f"{envelope / 1e6:.1f} MB; disk writes {summary['write_bytes'] / 1e6:.0f} MB vs seeking "
                           f"{legacy_writes / 1e6:.0f} MB (no PCM spool)",
                           buffered=buffered, peak=summary["peak_job_commit"], envelope=envelope)
                self.check(f"T5:{tput['book']}:{summary['label']}", summary["peak_staged_bytes"] <= legacy_staged,
                           f"peak staged {summary['peak_staged_bytes']} bytes vs seeking route {legacy_staged}")

    def cancels(self) -> None:
        """T7: Cancel while a late chapter encodes; every owned process reaped; the book taken back."""
        for name, route, extra in (("long6_48", "auto", ("--cancel-in-pass", "40", "--cancel-delay", "1.0")),
                                   ("long6_48", "legacy", ("--cancel-in-pass", "40", "--cancel-delay", "1.0")),
                                   ("scale500", "auto", ("--cancel-after", "400"))):
            summary = self.run("cancel", name, route, extra=extra, expect_states=("CANCELLED",),
                               expect_continuous=(route == "auto"), timeout=3600)
            ok = (summary is not None and summary["cancel_to_settled_s"] is not None
                  and summary["cancel_to_settled_s"] <= 2.0 and not summary["alive_at_settle"]
                  and summary["files"] == 0)
            detail = (f"Cancel settled in {None if summary is None else summary['cancel_to_settled_s']} s (limit 2.0), "
                      f"alive at settle {None if summary is None else summary['alive_at_settle']}, "
                      f"files left {None if summary is None else summary['files']}")
            if route == "legacy":
                self.log(f"for comparison, the seeking route: {detail}")
            else:
                self.check(f"T7:{name}", ok, detail)

    def faults(self) -> None:
        """Kill the encoder or the decoder mid-book; the book fails, Retry Failed starts a fresh decoder and matches."""
        for name, extra in (("scale100", ("--kill", "encoder", "--kill-at", "50")),
                            ("scale100", ("--kill", "decoder", "--kill-at", "50")),
                            ("long6_48", ("--kill", "decoder", "--kill-at", "40"))):
            summary = self.run("fault", name, "auto", extra=extra, expect_continuous=True,
                               expect_states=("COMPLETED_WITH_FAILURES", "SUCCEEDED"), timeout=3600)
            ok = summary is not None and bool(summary["killed"]) and self.identical(summary, name)
            self.check(f"fault:{name}:{extra[1]}", ok,
                       f"killed {None if summary is None else summary['killed']}; first attempt failed, retry "
                       f"{None if summary is None else summary['states']}; outputs identical={ok}")
        summary = self.run("pause", "scale100", "auto", extra=("--pause-after", "30", "--pause-seconds", "3"),
                           expect_continuous=True, timeout=1800)
        ok = (summary is not None and self.identical(summary, "scale100")
              and (summary["outputs_while_paused"] or 0) <= 1)
        self.check("pause:scale100", ok, f"paused after 30 outputs for 3 s; outputs while paused "
                                         f"{None if summary is None else summary['outputs_while_paused']}; identical={ok}")

    def stall_study(self, reps: int) -> None:
        """Phase 7A's one 25.7 s heartbeat gap was in this configuration; repeat it with full diagnostics."""
        for _rep in range(reps):
            summary = self.run("stall", "scale100", "auto", extra=("--kill", "encoder", "--kill-at", "50"),
                               expect_continuous=True, expect_states=("COMPLETED_WITH_FAILURES", "SUCCEEDED"),
                               timeout=1800)
            self.identical(summary, "scale100")

    def smoke(self) -> None:
        """A few minutes of the real cases, to prove the harness end to end before a qualification. Never a verdict."""
        for name, route, mode, metadata, continuous in (("route10", "continuous", "split", "preserve", True),
                                                        ("route10", "auto", "whole", "preserve", False),
                                                        ("r96k", "continuous", "split", "preserve", False)):
            summary = self.run("smoke", name, route, mode=mode, metadata=metadata, expect_continuous=continuous)
            self.check(f"smoke:T8:{name}:{mode}", self.identical(summary, name, mode=mode, metadata=metadata), "pinned")
        summary = self.run("smoke", "scale100", "auto", extra=("--kill", "decoder", "--kill-at", "30"),
                           expect_continuous=True, expect_states=("COMPLETED_WITH_FAILURES", "SUCCEEDED"))
        self.check("smoke:fault", self.identical(summary, "scale100"), "decoder killed, retried, identical")
        summary = self.run("smoke", "scale100", "auto", extra=("--cancel-in-pass", "60", "--cancel-delay", "0.05"),
                           expect_continuous=True, expect_states=("CANCELLED",))
        self.check("smoke:cancel", summary is not None and summary["cancel_to_settled_s"] is not None
                   and summary["cancel_to_settled_s"] <= 2.0 and summary["files"] == 0,
                   f"cancel settled {None if summary is None else summary['cancel_to_settled_s']} s")
        self.heartbeat()

    def heartbeat(self) -> None:
        """T6 across every continuous run of the qualification."""
        continuous = [s for s in self.runs if s.get("continuous") == [True]]
        worst_p99 = max((s["heartbeat"]["p99_s"] or 0.0) for s in continuous) if continuous else None
        over_2s = [s["label"] for s in continuous if (s["heartbeat"]["max_s"] or 0.0) > 2.0]
        self.check("T6", bool(continuous) and worst_p99 <= 0.25 and not over_2s,
                   f"{len(continuous)} continuous runs: worst heartbeat p99 {worst_p99} s (limit 0.25); runs with a "
                   f"stall over 2 s: {over_2s or 'none'}", worst_p99=worst_p99, over_2s=over_2s)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=common.REPO_ROOT, capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


def code_digest() -> str:
    """The tracked bytes of the application and this harness, as Git would store them, so the result names its code."""
    import hashlib  # noqa: PLC0415
    digest = hashlib.sha256()
    listed = git("ls-files", "scripts", "files/dev-work/verification-gate/scaling").splitlines()
    untracked = git("ls-files", "--others", "--exclude-standard", "scripts", "files/dev-work/verification-gate/scaling")
    for relative in sorted(set(listed) | set(untracked.splitlines())):
        path = common.REPO_ROOT / relative
        if path.is_file():
            digest.update(relative.encode() + b"\0" + path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def resolve_ffmpeg() -> str:
    sys.path.insert(0, str(common.SCRIPTS))
    from shared import ffmpeg_utils  # noqa: PLC0415
    return ffmpeg_utils.ffmpeg_cmd()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--ffmpeg", default="")
    parser.add_argument("--python", default=sys.executable, help="the interpreter each benchmark run uses")
    parser.add_argument("--reps", type=int, default=3, help="repetitions of each long throughput case")
    parser.add_argument("--small-reps", type=int, default=10)
    parser.add_argument("--stall-reps", type=int, default=10)
    parser.add_argument("--smoke", action="store_true",
                        help="development only: a few quick cases to exercise the harness; the verdict is SMOKE, never PASS")
    args = parser.parse_args(argv)
    root = args.out.resolve()
    outputs_root = (common.GATE_DIR / "outputs").resolve()
    verdict_path = root / "verdict.json"
    try:
        root.relative_to(outputs_root)
    except ValueError:
        print(f"refused: {root} is not inside {outputs_root}", file=sys.stderr)
        return 3
    root.mkdir(parents=True, exist_ok=False)
    started = time.time()
    status, reason = "FAIL", ""
    qualification = None
    try:
        sys.path.insert(0, str(common.SCRIPTS))
        try:
            from m4b import m4b_continuous  # noqa: PLC0415
        except ImportError as exc:
            status, reason = "BLOCKED", f"the application's M4B code is not here ({type(exc).__name__}: {exc})"
            return 2
        threshold = m4b_continuous.MIN_SAVED_PREFIX_SECONDS
        per_book_second = m4b_continuous.PREFIX_PER_BOOK_SECOND
        pair = common.ffmpeg_pair(args.ffmpeg or resolve_ffmpeg())
        reference = common.load_reference()
        build = common.pinned_build(reference, pair)
        identity = {"head": git("rev-parse", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                    "dirty": git("status", "--porcelain=v1", "--", "scripts", "files/dev-work/verification-gate"),
                    "code_digest": code_digest(), "python": subprocess.run(
                        [args.python, "-c", "import sys;print(sys.version.split()[0])"], capture_output=True,
                        text=True).stdout.strip(), "ffmpeg": pair, "min_saved_prefix_seconds": threshold,
                    "prefix_per_book_second": per_book_second}
        (root / "identity.json").write_text(json.dumps(identity, indent=1), encoding="utf-8")
        if build is None:
            status, reason = "BLOCKED", f"FFmpeg {pair['ffmpeg_sha256'][:12]} is not a build the reference was pinned on"
            return 2
        qualification = Qualification(root, pair, build, threshold, per_book_second, args.python)
        qualification.log(f"identity: HEAD {identity['head']}, code {identity['code_digest'][:12]}, "
                          f"{pair['version']}, threshold {threshold} s")
        before = common.protected_snapshot()
        for name in NEEDED:
            qualification.books[name] = common.ensure_fixture(name, build, pair, qualification.log)
            qualification.hashes[name] = build["fixtures"][name]["sha256"]
        if args.smoke:
            qualification.smoke()
            after = common.protected_snapshot()
            qualification.check("containment", before == after, "the owner's Downloads output tree is unchanged"
                                if before == after else "the owner's Downloads output tree CHANGED")
            failing = [c["name"] for c in qualification.checks if c["status"] != "PASS"]
            status = "SMOKE"
            reason = f"smoke only, never a qualification; {len(failing)} failing check(s): {failing[:12]}"
            return 3
        qualification.compatibility()
        qualification.small_books(args.small_reps)
        long6 = qualification.throughput("long6_48", args.reps, "T1", 2.0, 2.0)
        many = qualification.throughput("scale1000", args.reps, "T1b", 1.8, 2.0)
        long12 = qualification.throughput("long12_24", args.reps, None, None, None)
        qualification.slope_and_quarters(long6)
        qualification.slope_and_quarters(long12)
        qualification.resources([long6, many, long12])
        qualification.cancels()
        qualification.faults()
        qualification.stall_study(args.stall_reps)
        qualification.heartbeat()
        after = common.protected_snapshot()
        qualification.check("containment", before == after,
                            "the owner's Downloads output tree is unchanged" if before == after else
                            "the owner's Downloads output tree CHANGED during the qualification")
        failing = [c["name"] for c in qualification.checks if c["status"] != "PASS"]
        status = "FAIL" if failing else "PASS"
        reason = f"{len(failing)} failing check(s): {failing[:12]}" if failing else "every budget and case passed"
        twelve = {k: v for k, v in long12.items() if k not in ("arms", "runs")}
        (root / "twelve-hour.json").write_text(json.dumps(twelve, indent=1), encoding="utf-8")
        return 0 if status == "PASS" else 1
    except Exception:  # noqa: BLE001 - recorded as the result, never swallowed
        reason = traceback.format_exc()[-3000:]
        status = "FAIL"
        return 1
    finally:
        verdict = {"scenario": "m4b-scaling", "status": status, "reason": reason,
                   "elapsed_seconds": round(time.time() - started, 1),
                   "checks": qualification.checks if qualification else [],
                   "runs": len(qualification.runs) if qualification else 0}
        if qualification is not None:
            (root / "runs.json").write_text(json.dumps(qualification.runs, indent=1), encoding="utf-8")
        verdict_path.write_text(json.dumps(verdict, indent=1), encoding="utf-8")
        print(json.dumps({"status": status, "reason": reason[:500]}), flush=True)


if __name__ == "__main__":
    sys.exit(main())
