"""ACT v0.7.0 -- regenerate ``scripts/requirements-lock-windows-py312.txt``, the app environment's complete hash lock.

Developer only: never shipped, never imported by the app, never a user requirement.

    python -I files/dev-tools/lock_base_requirements.py --python <venv python.exe> --constraints <versions.txt>
        [--source "<where the versions were proved>"] [--check]

``--python`` must be a CPython 3.12 x86-64 Windows interpreter of a virtual environment (the app's own Python 3.12.15
with its ensurepip pip is the reference). ``--constraints`` holds ``name==version`` lines: the versions already proved
by a qualified installation (``pip list --format=freeze`` of it). pip itself then resolves ``scripts/requirements.txt``
under those constraints (``install --dry-run --ignore-installed --report``), so the lock records exactly the artifact
pip chooses for this platform and its SHA-256 as published by the index. The run is refused unless pip's resolution
is the constraint set exactly (nothing added, nothing missing, no version changed): the lock freezes proven versions,
it never upgrades them. Nothing is installed; pip's cache and configuration are kept in a temporary folder.

``--check`` writes nothing and exits 1 when the committed lock differs from what would be generated.

Exit codes: 0 PASS, 1 the lock differs (--check), 2 refused.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from shared import base_packages  # noqa: E402  (standard library only)

REQUIREMENTS = REPO / "scripts" / "requirements.txt"
#: Installed in a qualified environment but never resolved from the index: pip itself, and the spaCy English model the
#: optional-setup worker installs offline from its own verified wheel.
NOT_LOCKED = {"pip", "en-core-web-sm"}


class Refused(Exception):
    pass


def _constraints(path: Path) -> dict[str, tuple[str, str]]:
    pins = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)", line)
        if not match:
            raise Refused(f"constraint line is not name==version: {line!r}")
        key = base_packages.canonical_name(match.group(1))
        if key not in NOT_LOCKED:
            pins[key] = (match.group(1), match.group(2))
    return pins


def _resolve(python: Path, constraints: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="act-lock-") as tmp:
        report = Path(tmp) / "report.json"
        env = base_packages.pip_environment(os.environ, Path(tmp) / "pip-cache")
        command = [str(python), "-m", "pip", "install", "--dry-run", "--ignore-installed", "--quiet",
                   "--report", str(report), "-r", str(REQUIREMENTS), "-c", str(constraints)]
        done = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if done.returncode != 0:
            raise Refused("pip could not resolve the requirements under these constraints:\n" + done.stderr[-4000:])
        return json.loads(report.read_text(encoding="utf-8"))


def _entries(report: dict) -> list[dict]:
    environment = report.get("environment", {})
    if (environment.get("sys_platform"), environment.get("python_version"),
            environment.get("platform_machine", "").lower()) != ("win32", "3.12", "amd64"):
        raise Refused(f"the interpreter is not CPython 3.12 x86-64 Windows: {environment}")
    entries = []
    for item in report["install"]:
        info = item["download_info"]
        hashes = info.get("archive_info", {}).get("hashes", {})
        if item.get("is_direct") or "sha256" not in hashes:
            raise Refused(f"{item['metadata']['name']} has no index SHA-256 (direct or unhashed artifact)")
        entries.append({"name": item["metadata"]["name"], "version": item["metadata"]["version"],
                        "sha256": hashes["sha256"], "artifact": unquote(Path(urlsplit(info["url"]).path).name)})
    return sorted(entries, key=lambda e: base_packages.canonical_name(e["name"]))


def _compare(entries: list[dict], pins: dict[str, tuple[str, str]]) -> None:
    resolved = {base_packages.canonical_name(e["name"]): e["version"] for e in entries}
    added = sorted(set(resolved) - set(pins))
    missing = sorted(set(pins) - set(resolved))
    changed = sorted(k for k in set(resolved) & set(pins) if resolved[k] != pins[k][1])
    if added or missing or changed:
        raise Refused(f"pip's resolution is not the proven set: added {added}, missing {missing}, "
                      f"changed {[(k, pins[k][1], resolved[k]) for k in changed]}")


def _render(entries: list[dict], source: str, pip_version: str) -> str:
    requirements_sha256 = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    lines = [
        "# Audiobook Creation Tool - the app environment's complete dependency lock (Windows x86-64, CPython 3.12).",
        "#",
        "# Every package the app environment holds, transitive ones included, at one version and with the SHA-256 of",
        "# the one artifact pip installs on this platform. Setup and repair install ONLY from this file",
        "# (pip --require-hashes): a package or version that is not listed here cannot be installed.",
        "# scripts/requirements.txt stays the human-maintained list; regenerate this file after any change to it:",
        "#     python -I files/dev-tools/lock_base_requirements.py --python <venv python> --constraints <versions>",
        "# Do not edit by hand.",
        "#",
        f"# {base_packages.HEADER_REQUIREMENTS}: {requirements_sha256}",
        f"# {base_packages.HEADER_SOURCE}: {source}",
        f"# {base_packages.HEADER_RESOLVER}: pip {pip_version}, CPython 3.12 win_amd64",
        f"# {base_packages.HEADER_COUNT}: {len(entries)}",
        "",
    ]
    for entry in entries:
        lines.append(f"# {base_packages.ARTIFACT_PREFIX} {entry['artifact']}")
        lines.append(f"{entry['name']}=={entry['version']} --hash=sha256:{entry['sha256']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--constraints", required=True, type=Path)
    parser.add_argument("--source", default=None,
                        help="where the versions were proved (default: the committed lock's own statement)")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    lock = base_packages.lock_path(REQUIREMENTS)
    if args.source is None:
        try:
            args.source = base_packages.parse_lock(lock.read_text(encoding="utf-8")).header[base_packages.HEADER_SOURCE]
        except (OSError, base_packages.LockError, KeyError):
            print("REFUSED: --source is required when there is no committed lock to take it from")
            return 2
    try:
        pip_version = subprocess.run([str(args.python), "-m", "pip", "--version"], capture_output=True, text=True,
                                     check=True).stdout.split()[1]
        pins = _constraints(args.constraints)
        entries = _entries(_resolve(args.python, args.constraints))
        _compare(entries, pins)
        text = _render(entries, args.source, pip_version)
        problems = base_packages.lock_problems(REQUIREMENTS.read_text(encoding="utf-8"), text,
                                               hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest())
        if problems:
            raise Refused("the generated lock does not satisfy the lock contract: " + "; ".join(problems))
    except Refused as exc:
        print(f"REFUSED: {exc}")
        return 2
    if args.check:
        same = lock.is_file() and lock.read_text(encoding="utf-8") == text
        print("PASS: the committed lock is current" if same else "DIFFERS: regenerate the lock")
        return 0 if same else 1
    lock.write_text(text, encoding="utf-8", newline="\n")
    print(f"PASS: wrote {lock.relative_to(REPO).as_posix()} ({len(entries)} packages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
