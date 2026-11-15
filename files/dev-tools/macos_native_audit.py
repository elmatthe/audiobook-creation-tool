"""v0.8.x P1A -- the SIMULATED (linkage-verified) native audit of a Mac installation, with the owner's narrow signing
exception (D3 remediation, 2026-11-15). Developer qualification tool; never shipped, never run by the app. Standard
library plus the app's own Mach-O reader; run it with ``-I``:

    python -I files/dev-tools/macos_native_audit.py <tree> <report.json> [--prove-load <venv python>] [folder ...]

Every Mach-O file under the folders (default ``files/runtime-data/python``, ``.venv``, ``files/bin``) must:
  A1 contain arm64, and be arm64 only unless it is one of the approved universal2 files below;
  A2 link, in every slice, only system libraries or its own installation's (never Homebrew, MacPorts, /usr/local);
  A3 pass ``codesign --verify --strict`` -- or be one of the approved files, each judged exactly as recorded:
     * universal2 (six files from five hash-locked wheels): the installed bytes are the recorded SHA-256 and the
       wheel's own RECORD entry, the architectures are exactly x86_64 + arm64, and ``codesign --verify --strict
       --arch arm64`` passes. Apple's linker signs the arm64 slice; the x86_64 slice is never mapped on Apple Silicon.
     * PyTorch's ``torch/lib/libomp.dylib`` (one file): the recorded SHA-256 and RECORD entry, arm64 only, codesign's
       verdict exactly "not signed at all" (any other signature failure is not excepted), and, with ``--prove-load``,
       it is loaded by the dynamic loader and runs PyTorch's OpenMP work in the app's environment.
Anything else fails: an unsigned or invalidly signed binary, an unknown universal2 binary, changed bytes, an arm64
slice that does not verify, a non-arm64 binary or foreign linkage. Nothing is modified, re-signed or replaced.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
CODESIGN = "/usr/bin/codesign"
DEFAULT_FOLDERS = ("files/runtime-data/python", ".venv", "files/bin")
UNIVERSAL2 = "universal2: arm64 slice signed"
UNSIGNED_UPSTREAM = "unsigned upstream library that loads"
NOT_SIGNED = "code object is not signed at all"
_MACHO_MAGICS = (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbf\xba\xfe\xca",
                 b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce")


@dataclass(frozen=True)
class SigningException:
    relative: str                    # the file's path inside site-packages
    sha256: str                      # the installed bytes = the hash-locked wheel's member
    architectures: tuple[str, ...]
    kind: str
    wheel: str                       # the artifact the macOS lock names
    wheel_sha256: str                # its --hash in the macOS lock


#: Owner decision (D3 remediation, 2026-11-15): exactly these seven files, measured in the SIMULATED installation on
#: 2026-11-15 (each equals its wheel's member and its RECORD entry; each wheel's SHA-256 is its lock hash).
SIGNING_EXCEPTIONS = (
    SigningException("_brotli.cpython-312-darwin.so",
                     "faeac3d14fd8a768b2ddea544453b05e201c6076239c7bfa598b8645be8f4eb9", ("x86_64", "arm64"),
                     UNIVERSAL2, "brotli-1.2.0-cp312-cp312-macosx_10_13_universal2.whl",
                     "35d382625778834a7f3061b15423919aa03e4f5da34ac8e02c074e4b75ab4f84"),
    SigningException("onnx/onnx_cpp2py_export.abi3.so",
                     "4b638f68beb21569cca37a26dca2d8711dec439800bd990ae176cbf90edf85f3", ("x86_64", "arm64"),
                     UNIVERSAL2, "onnx-1.23.2-cp312-abi3-macosx_13_0_universal2.whl",
                     "1b8680ce1e6a9a4736374a9dce4de14ea8ee05e0dccf0784a78a6e5646bdc1f6"),
    SigningException("google/_upb/_message.abi3.so",
                     "5fe9c5aa8c22f90136ea60aa2e46bdbd95d1953c1a35bdd3ca4cd643b1d74f6d", ("x86_64", "arm64"),
                     UNIVERSAL2, "protobuf-7.36.2-cp310-abi3-macosx_10_9_universal2.whl",
                     "cbc70b17ee27e28894c7fee8bb04be1abead49e936bc70eb60052531eee2079e"),
    SigningException("charset_normalizer/cd.cpython-312-darwin.so",
                     "d38c3dff8e119637ff6d41466ec09d079dcce1ad93c705503d003673d68ba48b", ("x86_64", "arm64"),
                     UNIVERSAL2, "charset_normalizer-3.5.2-cp312-cp312-macosx_10_13_universal2.whl",
                     "ed2a239c0ea213acc1908150a3037257083c7c083128f1a4cec2ec4b97dca491"),
    SigningException("charset_normalizer/md.cpython-312-darwin.so",
                     "cd79f238f6b9ae576f19d49eee8ae48af8ef536b881a1b7c4689b0d06681f655", ("x86_64", "arm64"),
                     UNIVERSAL2, "charset_normalizer-3.5.2-cp312-cp312-macosx_10_13_universal2.whl",
                     "ed2a239c0ea213acc1908150a3037257083c7c083128f1a4cec2ec4b97dca491"),
    SigningException("ml_dtypes/_ml_dtypes_ext.cpython-312-darwin.so",
                     "00d3d4ce8aab569268ed11186d4779599acb75dc46518f3b115d7e3b5a45e353", ("x86_64", "arm64"),
                     UNIVERSAL2, "ml_dtypes-0.5.4-cp312-cp312-macosx_10_13_universal2.whl",
                     "a174837a64f5b16cab6f368171a1a03a27936b31699d167684073ff1c4237dac"),
    SigningException("torch/lib/libomp.dylib",
                     "def839a00fd8cab0ee576014fe177423889d003b637f236f9854d05962b53dd0", ("arm64",),
                     UNSIGNED_UPSTREAM, "torch-2.6.0-cp312-none-macosx_11_0_arm64.whl",
                     "9a610afe216a85a8b9bc9f8365ed561535c93e804c2a317ef7fabcc5deda0989"),
)


def _macho():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from shared import macho
    finally:
        sys.path.remove(str(REPO_ROOT / "scripts"))
    return macho


def codesign_verify(path: Path, arch: Optional[str] = None) -> tuple[int, str]:
    """``codesign --verify --strict`` (a system program, not a developer-tool shim). (exit code, its whole message,
    lines joined by " | "; the verdict line comes first, e.g. "<path>: code object is not signed at all | In
    architecture: arm64")."""
    argv = [CODESIGN, "--verify", "--strict", *(["--arch", arch] if arch else []), str(path)]
    done = subprocess.run(argv, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    lines = (done.stderr or done.stdout or "").strip().splitlines()
    return done.returncode, " | ".join(line.strip() for line in lines)


def _only_unsigned(detail: str) -> bool:
    """codesign's verdict is exactly "not signed at all", and every other line only names an architecture."""
    verdict, *rest = detail.split(" | ")
    return verdict.endswith(NOT_SIGNED) and all(line.startswith("In architecture:") for line in rest)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _site_relative(path: Path) -> Optional[str]:
    head, marker, tail = path.as_posix().partition("/site-packages/")
    return tail if marker else None


def _record_entry(path: Path, relative: str) -> Optional[str]:
    """The ``sha256=`` value pip's RECORD holds for ``relative``, from the site-packages folder containing ``path``."""
    site = Path(path.as_posix()[: -len(relative)])
    for record in site.glob("*.dist-info/RECORD"):
        try:
            rows = csv.reader(record.read_text(encoding="utf-8").splitlines())
            for row in rows:
                if row and row[0] == relative and len(row) > 1:
                    return row[1]
        except OSError:
            continue
    return None


def _record_value(sha256_hex: str) -> str:
    return "sha256=" + base64.urlsafe_b64encode(bytes.fromhex(sha256_hex)).rstrip(b"=").decode("ascii")


def machos(folder: Path):
    """Every regular (non-link) Mach-O file under ``folder``."""
    for directory, _dirs, names in os.walk(folder):
        for name in names:
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                continue
            try:
                with open(path, "rb") as handle:
                    magic = handle.read(4)
            except OSError:
                continue
            if magic in _MACHO_MAGICS:
                yield path


def judge(path: Path, tree: Path, *, codesign: Callable = codesign_verify,
          exceptions: tuple = SIGNING_EXCEPTIONS) -> dict:
    """One file's verdict: PASS (signed), PASS-EXCEPTION (an approved file, judged as recorded) or FAIL."""
    macho = _macho()
    row: dict = {"path": path.relative_to(tree).as_posix()}
    archs = macho.architectures(path)
    if archs is None:
        if open(path, "rb").read(4) == b"\xca\xfe\xba\xbe":
            row.update(verdict="SKIP", reason="0xCAFEBABE but not Mach-O (a Java class file)")
            return row
        row.update(verdict="FAIL", reason="unreadable Mach-O")
        return row
    row["architectures"] = list(archs)
    if "arm64" not in archs:
        row.update(verdict="FAIL", reason=f"no arm64 slice ({', '.join(archs)})")
        return row
    foreign = macho.foreign_dependencies(path, inside=tree)
    if foreign is None or foreign:
        row.update(verdict="FAIL", reason=f"links outside the system or this installation: {foreign}")
        return row
    relative = _site_relative(path)
    exception = next((item for item in exceptions if relative is not None and item.relative == relative), None)
    if exception is None:
        if archs != ("arm64",):
            row.update(verdict="FAIL", reason="a universal binary that is not one of the approved files")
            return row
        code, detail = codesign(path)
        row["codesign"] = detail
        row.update(verdict="PASS" if code == 0 else "FAIL",
                   reason="signature verifies" if code == 0 else f"codesign: {detail}")
        return row
    row["exception"] = exception.relative
    found = _sha256(path)
    if found != exception.sha256:
        row.update(verdict="FAIL", reason=f"changed bytes: {found}, not the approved {exception.sha256}")
        return row
    if _record_entry(path, relative) != _record_value(exception.sha256):
        row.update(verdict="FAIL", reason="pip's RECORD does not hold these bytes for this file")
        return row
    if archs != exception.architectures:
        row.update(verdict="FAIL", reason=f"architectures {archs}, not the approved {exception.architectures}")
        return row
    code, detail = codesign(path)
    row["codesign"] = detail
    if exception.kind == UNIVERSAL2:
        arm_code, arm_detail = codesign(path, "arm64")
        row["codesign_arm64"] = arm_detail or ("valid" if arm_code == 0 else "")
        ok = arm_code == 0
        row.update(verdict="PASS-EXCEPTION" if ok else "FAIL",
                   reason="approved universal2; its arm64 slice verifies" if ok
                   else f"approved universal2, but its arm64 slice does not verify: {arm_detail}")
        return row
    ok = code == 0 or _only_unsigned(detail)
    row.update(verdict="PASS-EXCEPTION" if ok else "FAIL",
               reason="approved unsigned upstream library (its loading is proved separately)" if ok
               else f"approved only as unsigned, but codesign says: {detail}")
    return row


_LOAD_PROOF = """
import ctypes, sys
omp = ctypes.CDLL(sys.argv[1])          # the dynamic loader maps the exact file
threads = omp.omp_get_max_threads()      # and its code runs
import torch
torch.set_num_threads(4)
x = torch.arange(8_000_000, dtype=torch.float64)
total = float((x * 2).sum())             # ATen's parallel loops (OpenMP backend); exact in float64
print(threads > 0, total == 8_000_000 * 7_999_999, "OpenMP" in torch.__config__.parallel_info(),
      torch.get_num_threads())
"""


def prove_load(python: Path, library: Path) -> dict:
    """The dynamic loader maps ``library``, its code runs, and PyTorch does OpenMP work with it in that environment."""
    done = subprocess.run([str(python), "-I", "-c", _LOAD_PROOF, str(library)], capture_output=True, text=True,
                          timeout=600, stdin=subprocess.DEVNULL)
    ok = done.returncode == 0 and done.stdout.strip() == "True True True 4"
    return {"loads_and_runs": ok, "output": done.stdout.strip(), "detail": done.stderr.strip()[-600:]}


def audit(tree: Path, folders=DEFAULT_FOLDERS, *, codesign: Callable = codesign_verify,
          exceptions: tuple = SIGNING_EXCEPTIONS, python: Optional[Path] = None) -> dict:
    rows = [judge(path, tree, codesign=codesign, exceptions=exceptions)
            for folder in folders for path in sorted(machos(tree / folder))]
    used = {row["exception"] for row in rows if row.get("exception")}
    load = None
    if python is not None:
        omp = [tree / row["path"] for row in rows if row.get("exception", "").endswith("libomp.dylib")
               and row["verdict"] == "PASS-EXCEPTION"]
        load = prove_load(python, omp[0]) if omp else {"loads_and_runs": False, "output": "",
                                                       "detail": "the approved libomp.dylib was not found"}
    failures = [row for row in rows if row["verdict"] == "FAIL"]
    if load is not None and not load["loads_and_runs"]:
        failures.append({"path": "torch/lib/libomp.dylib", "verdict": "FAIL", "reason": f"load proof: {load}"})
    counts: dict = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    return {"machos": len(rows), "counts": counts, "exceptions_used": sorted(used),
            "exceptions_absent": sorted({item.relative for item in exceptions} - used), "load_proof": load,
            "failures": failures, "PASS": not failures,
            "approved_exceptions": [asdict(item) for item in exceptions], "rows": rows}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tree", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("folders", nargs="*", default=list(DEFAULT_FOLDERS))
    parser.add_argument("--prove-load", type=Path, default=None, help="the installation's venv python")
    args = parser.parse_args(argv)
    result = audit(args.tree.resolve(), args.folders, python=args.prove_load)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("machos", "counts", "exceptions_used", "exceptions_absent",
                                                   "load_proof", "failures", "PASS")}, indent=2)[:4000])
    return 0 if result["PASS"] else 1


if __name__ == "__main__":
    sys.exit(main())
