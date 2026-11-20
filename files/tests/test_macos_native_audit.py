"""v0.8.x P1A D3 remediation -- the native audit's narrow signing exception (``files/dev-tools/macos_native_audit.py``).

The owner accepted exactly seven upstream files (Decisions 2026-11-15): six universal2 extension modules whose arm64
slice verifies, and PyTorch's unsigned ``libomp.dylib``, each by its recorded SHA-256 and wheel. Everything else stays
fail-closed. These tests build small Mach-O files and stand in for ``codesign``, so they run on every platform; the
real audit of the SIMULATED installation is recorded in Decisions and the Handoff.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import importlib.util
import struct
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MACOS_LOCK = REPO_ROOT / "scripts" / "requirements-lock-macos-arm64-py312.txt"
ARM64, X86_64 = 0x0100000C, 0x01000007


def _tool():
    spec = importlib.util.spec_from_file_location("act_macos_native_audit",
                                                  REPO_ROOT / "files" / "dev-tools" / "macos_native_audit.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = _tool()


def _thin(cputype: int, dylibs=("/usr/lib/libSystem.B.dylib",), salt: bytes = b"") -> bytes:
    commands = b""
    for name in dylibs:
        raw = name.encode() + b"\0"
        size = (24 + len(raw) + 7) // 8 * 8
        commands += struct.pack("<IIIIII", 0xC, size, 24, 0, 0, 0) + raw.ljust(size - 24, b"\0")
    header = struct.pack("<IiiIIIII", 0xFEEDFACF, cputype, 0, 6, len(dylibs), len(commands), 0, 0)
    return header + commands + salt


def _fat(*slices: tuple[int, bytes]) -> bytes:
    offset, table, bodies = 4096, b"", b""
    for cputype, body in slices:
        table += struct.pack(">iiIII", cputype, 0, offset + len(bodies), len(body), 12)
        bodies += body.ljust(4096, b"\0")
    return (struct.pack(">II", 0xCAFEBABE, len(slices)) + table).ljust(offset, b"\0") + bodies


SITE = Path(".venv/lib/python3.12/site-packages")


def _install(tree: Path, relative: str, data: bytes, *, record: bool = True) -> Path:
    path = tree / SITE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if record:
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        dist = tree / SITE / "fixture-1.0.dist-info" / "RECORD"
        dist.parent.mkdir(parents=True, exist_ok=True)
        with open(dist, "a", encoding="utf-8") as handle:
            handle.write(f"{relative},sha256={digest},{len(data)}\n")
    return path


def _codesign(answers: dict):
    """Stand-in for codesign: answers[(name, arch)] = (exit code, message); default: a valid signature."""
    def run(path, arch=None):
        return answers.get((Path(path).name, arch), (0, f"{path}: valid on disk"))
    return run


def _exception(relative: str, data: bytes, kind: str, archs) -> "audit.SigningException":
    return audit.SigningException(relative, hashlib.sha256(data).hexdigest(), tuple(archs), kind, "fixture.whl",
                                  "0" * 64)


UNIVERSAL = _fat((X86_64, _thin(X86_64)), (ARM64, _thin(ARM64)))
LIBOMP = _thin(ARM64, salt=b"libomp")


def _verdict(tree, relative, *, answers=None, exceptions=()):
    return audit.judge(tree / SITE / relative, tree, codesign=_codesign(answers or {}), exceptions=exceptions)


def test_a_signed_native_binary_passes(tmp_path):
    _install(tmp_path, "pkg/ok.so", _thin(ARM64))
    assert _verdict(tmp_path, "pkg/ok.so")["verdict"] == "PASS"


def test_an_unexpected_unsigned_binary_fails(tmp_path):
    _install(tmp_path, "pkg/new.so", _thin(ARM64))
    row = _verdict(tmp_path, "pkg/new.so", answers={("new.so", None): (1, "code object is not signed at all")})
    assert row["verdict"] == "FAIL" and "not signed" in row["reason"]


def test_an_approved_universal2_file_passes_only_on_its_arm64_signature(tmp_path):
    _install(tmp_path, "pkg/u.so", UNIVERSAL)
    approved = (_exception("pkg/u.so", UNIVERSAL, audit.UNIVERSAL2, ("x86_64", "arm64")),)
    unsigned_x86 = {("u.so", None): (1, "code object is not signed at all")}
    assert _verdict(tmp_path, "pkg/u.so", answers=unsigned_x86, exceptions=approved)["verdict"] == "PASS-EXCEPTION"
    invalid_arm = {**unsigned_x86, ("u.so", "arm64"): (1, "invalid signature (code or signature have been modified)")}
    row = _verdict(tmp_path, "pkg/u.so", answers=invalid_arm, exceptions=approved)
    assert row["verdict"] == "FAIL" and "arm64 slice does not verify" in row["reason"]


def test_an_unknown_universal2_binary_fails_even_when_it_verifies(tmp_path):
    _install(tmp_path, "pkg/other.so", UNIVERSAL)
    row = _verdict(tmp_path, "pkg/other.so")
    assert row["verdict"] == "FAIL" and "not one of the approved files" in row["reason"]


def test_an_approved_file_with_changed_bytes_fails(tmp_path):
    approved = (_exception("pkg/u.so", UNIVERSAL, audit.UNIVERSAL2, ("x86_64", "arm64")),)
    _install(tmp_path, "pkg/u.so", UNIVERSAL[:-1] + b"\x01")
    row = _verdict(tmp_path, "pkg/u.so", exceptions=approved)
    assert row["verdict"] == "FAIL" and "changed bytes" in row["reason"]


def test_an_approved_file_pip_did_not_record_fails(tmp_path):
    approved = (_exception("pkg/u.so", UNIVERSAL, audit.UNIVERSAL2, ("x86_64", "arm64")),)
    _install(tmp_path, "pkg/u.so", UNIVERSAL, record=False)
    row = _verdict(tmp_path, "pkg/u.so", exceptions=approved)
    assert row["verdict"] == "FAIL" and "RECORD" in row["reason"]


def test_the_unsigned_upstream_library_is_excepted_only_as_unsigned_and_only_at_its_bytes(tmp_path):
    approved = (_exception("torch/lib/libomp.dylib", LIBOMP, audit.UNSIGNED_UPSTREAM, ("arm64",)),)
    _install(tmp_path, "torch/lib/libomp.dylib", LIBOMP)
    # codesign's real message for this file (2026-11-15): the verdict, then an architecture note.
    unsigned = {("libomp.dylib", None): (1, "x/libomp.dylib: code object is not signed at all | In architecture: arm64")}
    assert _verdict(tmp_path, "torch/lib/libomp.dylib", answers=unsigned,
                    exceptions=approved)["verdict"] == "PASS-EXCEPTION"
    for message in ("x/libomp.dylib: invalid signature (code or signature have been modified) | In architecture: arm64",
                    "x/libomp.dylib: code object is not signed at all | a sealed resource is missing or invalid"):
        answer = {("libomp.dylib", None): (1, message)}
        assert _verdict(tmp_path, "torch/lib/libomp.dylib", answers=answer, exceptions=approved)["verdict"] == "FAIL"
    elsewhere = tmp_path / "other"
    _install(elsewhere, "torch/lib/libomp.dylib", LIBOMP + b"!")
    assert _verdict(elsewhere, "torch/lib/libomp.dylib", answers=unsigned, exceptions=approved)["verdict"] == "FAIL"


@pytest.mark.parametrize("dylib", ["/opt/homebrew/opt/libomp/lib/libomp.dylib", "/usr/local/lib/libx.dylib",
                                   "/Library/Frameworks/Other.framework/Other"])
def test_foreign_linkage_fails_even_when_signed(tmp_path, dylib):
    _install(tmp_path, "pkg/linked.so", _thin(ARM64, dylibs=("/usr/lib/libSystem.B.dylib", dylib)))
    row = _verdict(tmp_path, "pkg/linked.so")
    assert row["verdict"] == "FAIL" and "links outside" in row["reason"]


def test_a_binary_without_an_arm64_slice_fails(tmp_path):
    _install(tmp_path, "pkg/intel.so", _thin(X86_64))
    assert _verdict(tmp_path, "pkg/intel.so")["verdict"] == "FAIL"


def test_the_audit_fails_closed_when_any_file_fails_and_reports_unused_exceptions(tmp_path):
    _install(tmp_path, "pkg/ok.so", _thin(ARM64))
    _install(tmp_path, "pkg/new.so", _thin(ARM64))
    result = audit.audit(tmp_path, [".venv"], codesign=_codesign({("new.so", None): (1, "not signed at all")}),
                         exceptions=audit.SIGNING_EXCEPTIONS)
    assert result["PASS"] is False and [row["path"] for row in result["failures"]] == [(SITE / "pkg/new.so").as_posix()]
    assert len(result["exceptions_absent"]) == 7


def test_the_approved_list_is_exactly_seven_files_from_hash_locked_wheels():
    lock = MACOS_LOCK.read_text(encoding="utf-8")
    items = audit.SIGNING_EXCEPTIONS
    assert len(items) == 7 and len({item.relative for item in items}) == 7
    assert [item.kind for item in items].count(audit.UNIVERSAL2) == 6
    (omp,) = [item for item in items if item.kind == audit.UNSIGNED_UPSTREAM]
    assert omp.relative == "torch/lib/libomp.dylib" and omp.architectures == ("arm64",)
    for item in items:
        assert f"# artifact: {item.wheel}" in lock, item.wheel
        assert f"--hash=sha256:{item.wheel_sha256}" in lock, item.wheel
        assert ("universal2" in item.wheel) is (item.kind == audit.UNIVERSAL2)
        assert len(item.sha256) == 64 and int(item.sha256, 16)
