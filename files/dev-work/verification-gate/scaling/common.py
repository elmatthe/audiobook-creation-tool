"""Shared pieces of the m4b-scaling qualification and its threshold calibration (v0.7.2 Phase 7B). Stdlib only.

* where things live: the repository, the ignored fixture cache, the pinned reference;
* which FFmpeg: the pair is named explicitly, hashed, and must be the pair ``reference.json`` was pinned on;
* fixtures: made by ``recipe.py`` into the ignored cache (``files/dev-work/m4b-scaling-cache``) and accepted only when
  their SHA-256 is the one pinned for this FFmpeg build, so a book is never trusted because a file of that name exists;
* one contained benchmark run: ``bench_run.py`` in its own process, under a timeout, inside the run's own folder;
* digests: one SHA-256 over a run's sorted ``path NUL sha256`` lines, the compact form the reference pins.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE_DIR = HERE.parent
REPO_ROOT = GATE_DIR.parents[2]
SCRIPTS = REPO_ROOT / "scripts"
#: Large generated media, ignored by Git (files/dev-work/* is ignored) and kept between runs so a qualification does not
#: spend twenty minutes re-encoding twelve hours of noise. Every file in it is verified against the pinned hash on use.
CACHE = REPO_ROOT / "files" / "dev-work" / "m4b-scaling-cache"
REFERENCE = HERE / "reference.json"

sys.path.insert(0, str(HERE))
import winjob  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def output_digest(files: list[dict]) -> str:
    """The pinned form of a run's outputs: their relative paths and hashes, in order."""
    lines = "".join(f"{item['path']}\0{item['sha256']}\n" for item in sorted(files, key=lambda item: item["path"]))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def load_reference() -> dict:
    return json.loads(REFERENCE.read_text(encoding="utf-8"))


def ffmpeg_pair(ffmpeg: str) -> dict:
    path = Path(ffmpeg).resolve()
    probe = path.with_name("ffprobe.exe" if path.suffix.lower() == ".exe" else "ffprobe")
    if not path.is_file() or not probe.is_file():
        raise FileNotFoundError(f"no FFmpeg pair at {path}")
    version = subprocess.run([str(path), "-hide_banner", "-version"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout.splitlines()[:1]
    return {"ffmpeg": str(path), "ffprobe": str(probe), "ffmpeg_sha256": sha256(path), "ffprobe_sha256": sha256(probe),
            "version": version[0] if version else ""}


def pinned_build(reference: dict, pair: dict) -> dict | None:
    """The reference entry for this exact FFmpeg pair, or None: byte identity is pinned per build."""
    for build in reference["builds"]:
        if build["ffmpeg_sha256"] == pair["ffmpeg_sha256"] and build["ffprobe_sha256"] == pair["ffprobe_sha256"]:
            return build
    return None


def ensure_fixture(name: str, build: dict, pair: dict, log) -> Path:
    """The validated book *name*, made by the recipe into the cache if it is not already there with the pinned hash."""
    expected = build["fixtures"][name]["sha256"]
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / f"{name}.m4b"
    if target.is_file() and sha256(target) == expected:
        return target
    if target.exists():
        log(f"fixture {name}: cached copy does not match the pinned hash; remaking it")
        target.unlink()
    started = time.perf_counter()
    done = subprocess.run([sys.executable, str(HERE / "recipe.py"), "--ffmpeg", pair["ffmpeg"], "--out", str(CACHE), name],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise RuntimeError(f"fixture {name} could not be made: {done.stdout[-500:]} {done.stderr[-1500:]}")
    found = sha256(target)
    if found != expected:
        raise RuntimeError(f"fixture {name} came out {found}, not the pinned {expected}: the recipe or FFmpeg changed")
    log(f"fixture {name}: made and validated in {time.perf_counter() - started:.1f} s")
    return target


def bench(run_root: Path, label: str, sources: list[Path], pair: dict, *, route: str, timeout: float,
          extra: tuple = (), mode: str = "split", metadata: str = "preserve", python: str | None = None) -> dict:
    """One contained benchmark run in its own process. Returns its results, or a record of why there are none."""
    out = run_root / "runs" / label
    argv = [python or sys.executable, str(HERE / "bench_run.py"), "--code", str(SCRIPTS), "--ffmpeg", pair["ffmpeg"],
            "--root", str(run_root), "--out", str(out), "--route", route, "--mode", mode, "--metadata", metadata,
            "--label", label, "--timeout", str(timeout), "--hash-outputs", *map(str, extra)]
    for source in sources:
        argv += ["--source", str(source)]
    load = winjob.system_times()
    time.sleep(1.0)
    load_before = winjob.load_between(load, winjob.system_times())
    started = time.perf_counter()
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout + 600)
        code, stdout, stderr = done.returncode, done.stdout, done.stderr
    except subprocess.TimeoutExpired as exc:
        code, stdout, stderr = "timeout", str(exc.stdout or ""), str(exc.stderr or "")
    wall = time.perf_counter() - started
    record = {"label": label, "exit": code, "wall_s": round(wall, 2), "load_before_pct": load_before,
              "stdout": stdout.strip()[-600:], "stderr": stderr.strip()[-2000:] if code else ""}
    results_file = out / "results.json"
    if code == 0 and results_file.is_file():
        record["results"] = json.loads(results_file.read_text(encoding="utf-8"))
    return record


def remove_outputs(run_record: dict) -> int:
    """Delete one finished run's produced MP3s (their hashes stay in results.json). Only inside that run's own folder."""
    results = run_record.get("results") or {}
    run_dir = results.get("outcome", {}).get("run_dir")
    out = Path(results.get("containment", {}).get("output_base", "")) if results else None
    if not run_dir or out is None or not out.is_dir():
        return 0
    run_dir = Path(run_dir).resolve()
    run_dir.relative_to(out.resolve())  # raises if the run folder is not inside its own output base
    removed = 0
    for path in run_dir.rglob("*.mp3"):
        path.unlink()
        removed += 1
    shutil.rmtree(run_dir)
    return removed


def protected_snapshot() -> dict:
    """The owner's Downloads output tree and the user profile's ACT settings, by name, size and time: never read in full.
    Compared before and after a qualification, so an escape of any output is a failed containment, not a guess."""
    profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
    roots = [profile / "Downloads" / "Audiobook-Creation-Tool-Outputs"]
    snapshot: dict = {}
    for root in roots:
        entries = {}
        if root.exists():
            for folder, _dirs, names in os.walk(root):
                for name in names:
                    path = Path(folder, name)
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    entries[str(path.relative_to(root))] = [stat.st_size, int(stat.st_mtime)]
        snapshot[str(root)] = entries if root.exists() else "<absent>"
    return snapshot
