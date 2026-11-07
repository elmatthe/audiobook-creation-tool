"""The gate's disposable scratch under ``%TEMP%\\act-gate``: who owns a child, whether it is in use, and what a failure keeps.

The owner approved this one root as an exception to repository-only scratch on 2026-11-06 (Decisions.md, v0.7.2 Phase 3),
because every repository location measured an unreliable rate of directory renames and ``%TEMP%`` measured none. The approval
has conditions, and this module is where they are kept: only uniquely identified ACT-owned scratch is created or cleaned;
another application's files and an active process's workspace are never touched; a failed run's diagnostics are preserved
inside the repository; ownership and inactivity are established exactly before anything abandoned is removed; nothing sweeps
``%TEMP%``.

So a child is identified by the record it carries from birth, ``act-gate-owner.json``, or for children older than that record
by the run that named it in its evidence. A name that looks right proves nothing. The audit reads and reports; it never
removes anything.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import time
from pathlib import Path

OWNER_NAME = "act-gate-owner.json"
OWNER_KIND = "act-gate-scratch"
#: A preflight child's only file, written by ``preflight_children``. Its bytes identify scratch older than the owner record.
PREFLIGHT_STUB_BYTES = b"sandbox binary"
#: A failing test's folder is evidence up to here; anything larger is listed rather than copied.
PRESERVE_TEST_BYTES = 8 << 20
PRESERVE_RUN_BYTES = 64 << 20
_TMP_NAME_LENGTH = 30  # pytest's tmp_path uses the test's name with \W replaced, cut to 30 characters, then a counter


def _process_created(pid: int) -> int | None:
    """A process's creation time, or None when it is gone. With the pid it names one process: a pid alone can be reused."""
    if sys.platform != "win32":
        return None
    import ctypes.wintypes as w

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = w.HANDLE
    kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel32.GetProcessTimes.argtypes = [w.HANDLE, *[ctypes.POINTER(w.FILETIME)] * 4]
    kernel32.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    kernel32.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        code = w.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != 259:  # STILL_ACTIVE
            return None
        created, ended, kernel, user = w.FILETIME(), w.FILETIME(), w.FILETIME(), w.FILETIME()
        if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(ended), ctypes.byref(kernel),
                                        ctypes.byref(user)):
            return None
        return (created.dwHighDateTime << 32) | created.dwLowDateTime
    finally:
        kernel32.CloseHandle(handle)


def write_owner(child: Path, run_id: str, nonce: str) -> None:
    """The child's birth certificate: which run, and exactly which process, is using it."""
    pid = os.getpid()
    record = {"kind": OWNER_KIND, "run_id": run_id, "nonce": nonce, "pid": pid, "process_created": _process_created(pid),
              "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    (child / OWNER_NAME).write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8", newline="\n")


def read_owner(child: Path) -> dict | None:
    try:
        record = json.loads((child / OWNER_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) and record.get("kind") == OWNER_KIND else None


def owner_process_alive(record: dict) -> bool:
    """True only when the very process that created the child still runs. An unknown creation time counts as alive."""
    created = _process_created(int(record.get("pid", 0)))
    if created is None:
        return False
    recorded = record.get("process_created")
    return recorded is None or recorded == created


def _is_link(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _refused_open(path: str) -> int:
    """The error from asking Windows for an exclusive handle, 0 if granted. Refused means something else holds it open."""
    if sys.platform != "win32":
        return 0
    import ctypes.wintypes as w

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = w.HANDLE
    kernel32.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
    kernel32.CloseHandle.argtypes = [w.HANDLE]
    long_path = path if path.startswith("\\\\?\\") else "\\\\?\\" + path
    handle = kernel32.CreateFileW(long_path, 0x80000000, 0, None, 3, 0x02000000 | 0x00200000, None)  # no sharing, no follow
    if handle == w.HANDLE(-1).value:
        return ctypes.get_last_error()
    kernel32.CloseHandle(handle)
    return 0


def measure(child: Path) -> dict:
    """Size, files, links, newest change and anything refusing an exclusive open, without following a link. Changes nothing."""
    files = links = size = 0
    newest = 0.0
    refused: dict[str, int] = {}
    only_file_is_stub = True
    for dirpath, dirnames, filenames in os.walk(child, followlinks=False):
        for name in [*dirnames, *filenames]:
            full = os.path.join(dirpath, name)
            try:
                info = os.lstat(full)
            except OSError as exc:
                refused[str(getattr(exc, "winerror", exc.errno))] = refused.get(str(getattr(exc, "winerror", exc.errno)), 0) + 1
                continue
            newest = max(newest, info.st_mtime)
            if _is_link(Path(full)):
                links += 1
            if not stat.S_ISDIR(info.st_mode):
                files += 1
                size += info.st_size
                if name != OWNER_NAME and (name != "invalid.exe" or info.st_size != len(PREFLIGHT_STUB_BYTES)):
                    only_file_is_stub = False
            code = _refused_open(full)
            if code:
                refused[str(code)] = refused.get(str(code), 0) + 1
        dirnames[:] = [d for d in dirnames if not _is_link(Path(dirpath) / d)]
    return {"files": files, "bytes": size, "links": links, "newest": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(newest))
            if newest else None, "open_refused": refused, "only_gate_stub": only_file_is_stub and files >= 1}


def _is_preflight_only(child: Path) -> bool:
    """The whole child is the gate's own preflight stub, byte for byte: scratch of the gate whichever run made it."""
    try:
        return (child / "p" / "invalid.exe").read_bytes() == PREFLIGHT_STUB_BYTES
    except OSError:
        return False


def recorded_owner(child_name: str, scratch_root: Path, outputs_root: Path) -> dict | None:
    """The run whose evidence names this child, for scratch older than the owner record."""
    wanted = os.path.normcase(str(Path(scratch_root) / child_name))
    if not Path(outputs_root).is_dir():
        return None
    for run in sorted(Path(outputs_root).iterdir(), reverse=True):
        results = run / "results.json"
        try:
            data = json.loads(results.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if data is not None and os.path.normcase(str((data.get("cleanup") or {}).get("scratch"))) == wanted:
            return {"run_id": run.name, "status": data.get("status"), "named_by": "results.json cleanup.scratch"}
        try:
            log = (run / "logs" / "verify.log").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"scratch: " + re.escape(str(Path(scratch_root) / child_name)) + r"\s*$", log, re.MULTILINE | re.IGNORECASE):
            return {"run_id": run.name, "status": None if data is None else data.get("status"), "named_by": "logs/verify.log"}
    return None


def audit(scratch_root: Path, outputs_root: Path) -> list[dict]:
    """One row per child of the scratch root. ``state`` is ``active``, ``abandoned`` (owner known, not running) or ``unproven``."""
    rows = []
    root = Path(scratch_root)
    if not root.is_dir():
        return rows
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        row = {"path": str(child), "name": child.name, **measure(child)}
        if _is_link(child):
            rows.append({**row, "state": "unproven", "why": "a link or junction, which the gate never creates"})
            continue
        owner = read_owner(child)
        if owner is not None:
            alive = owner_process_alive(owner)
            row.update(state="active" if alive else "abandoned", owner=owner, why=(
                f"owner record: process {owner.get('pid')} of run {owner.get('run_id')} "
                + ("is still running" if alive else "has ended")))
        else:
            named = recorded_owner(child.name, root, outputs_root)
            if named is not None:
                row.update(state="abandoned", owner=named, why=f"named by run {named['run_id']} ({named['named_by']})")
            elif _is_preflight_only(child) and row["only_gate_stub"]:
                row.update(state="abandoned", owner=None, why="holds only the gate's preflight stub, byte for byte; no run recorded it")
            else:
                row.update(state="unproven", owner=None, why="no owner record and no run names it")
        if row["open_refused"] and row["state"] == "abandoned":
            row.update(state="active", why=row["why"] + f"; but something holds it open {row['open_refused']}")
        rows.append(row)
    return rows


def _tmp_prefix(nodeid: str) -> str:
    """The folder name pytest's tmp_path gives a test, without its counter."""
    return re.sub(r"\W", "_", nodeid.rsplit("::", 1)[-1])[:_TMP_NAME_LENGTH]


def preserve_failed(basetemp: Path, failing: list[str], destination: Path, *, per_test: int = PRESERVE_TEST_BYTES,
                    per_run: int = PRESERVE_RUN_BYTES) -> dict:
    """Copy each failing test's temp folder into the run's evidence, within limits. A link is recorded, never followed.

    Returns what was copied and what was left out, so nobody takes a partial copy for the whole. Duplicate-named folders of the
    same test (a counter suffix) all count as that test's: pytest gives no other way to tell them apart.
    """
    record = {"tests": len(failing), "copied": [], "left_out": [], "links_not_followed": 0, "bytes": 0}
    basetemp = Path(basetemp)
    if not basetemp.is_dir() or not failing:
        return record
    wanted = sorted({_tmp_prefix(node) for node in failing})
    children = sorted(item for item in basetemp.iterdir() if not _is_link(item))
    for prefix in wanted:
        for child in children:
            if not (child.name.startswith(prefix) and child.name[len(prefix):].isdigit()):
                continue
            target = destination / child.name
            copied = 0
            for dirpath, dirnames, filenames in os.walk(child, followlinks=False):
                kept = [d for d in dirnames if not _is_link(Path(dirpath) / d)]
                record["links_not_followed"] += len(dirnames) - len(kept)
                dirnames[:] = kept
                relative = Path(dirpath).relative_to(child)
                for name in filenames:
                    source = Path(dirpath) / name
                    if _is_link(source):
                        record["links_not_followed"] += 1
                        continue
                    size = source.stat().st_size
                    if copied + size > per_test or record["bytes"] + size > per_run:
                        record["left_out"].append(f"{child.name}/{(relative / name).as_posix()} ({size} bytes)")
                        continue
                    (target / relative).mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target / relative / name)
                    copied += size
                    record["bytes"] += size
            record["copied"].append(child.name)
    if len(record["left_out"]) > 200:
        record["left_out"] = [*record["left_out"][:200], f"... and {len(record['left_out']) - 200} more"]
    return record


def audit_lines(rows: list[dict]) -> list[str]:
    total = sum(row.get("bytes", 0) for row in rows)
    lines = [f"{len(rows)} scratch folder(s), {total / 2**30:.2f} GiB. This audit changes nothing."]
    for row in rows:
        lines.append(f"  {row['state']:<9} {row['name']}  {row.get('bytes', 0) / 2**20:9.1f} MiB  {row.get('files', 0):>7} files  "
                     f"newest {row.get('newest')}  {row.get('why')}")
    return lines


def tree_digest(path: Path) -> str:
    """Names, sizes and modification times of a tree: what ``--audit-scratch`` and the acceptance stage compare, cheaply."""
    digest = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            info = os.lstat(os.path.join(dirpath, name))
            digest.update(f"{os.path.relpath(os.path.join(dirpath, name), path)}\0{info.st_size}\0{info.st_mtime_ns}\n"
                          .encode("utf-8", "surrogateescape"))
    return digest.hexdigest()
