"""macho.py -- read a Mach-O file's architectures and the libraries it links, without running anything (macOS).

``/usr/bin/lipo`` and ``/usr/bin/otool`` look like system tools, but on macOS they are Xcode developer-tool shims
(the same file as ``/usr/bin/git`` and ``/usr/bin/clang``): on a Mac without the Command Line Tools, running one opens
the "install developer tools" prompt. ACT must work on such a Mac, so the architecture and linkage checks of an
app-owned binary (FFmpeg, plan section 11.1, proofs 4 and 6) read the headers here instead. ``file``, ``codesign`` and
``shasum`` are real system programs and stay usable.

Standard library only (``struct``), importable before the venv exists. Reads at most the header and load commands.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_FAT_MAGIC = 0xCAFEBABE
_FAT_MAGIC_64 = 0xCAFEBABF
_MH_MAGIC_64 = 0xFEEDFACF
_MH_CIGAM_64 = 0xCFFAEDFE
_MH_MAGIC = 0xFEEDFACE
_MH_CIGAM = 0xCEFAEDFE

_CPU_ARCH_ABI64 = 0x01000000
_CPU_TYPES = {7: "i386", 7 | _CPU_ARCH_ABI64: "x86_64", 12: "arm", 12 | _CPU_ARCH_ABI64: "arm64",
              12 | 0x02000000: "arm64_32", 18: "ppc", 18 | _CPU_ARCH_ABI64: "ppc64"}

#: Load commands that name a library the binary needs at run time.
_LC_REQ_DYLD = 0x80000000
_DYLIB_COMMANDS = {0xC: "load", 0x18 | _LC_REQ_DYLD: "weak", 0x1F | _LC_REQ_DYLD: "reexport", 0x20: "lazy",
                   0x23 | _LC_REQ_DYLD: "upward"}

#: Where a system library or framework lives; anything else must be inside the app.
SYSTEM_PREFIXES = ("/usr/lib/", "/System/Library/")
#: Locations a binary ACT ships or downloads must never depend on.
FORBIDDEN_PREFIXES = ("/opt/homebrew/", "/usr/local/", "/opt/local/")

_MAX_LOAD_COMMANDS_BYTES = 16 * 1024 * 1024


class NotMachO(ValueError):
    """The file is not a Mach-O executable or library this reader understands."""


@dataclass(frozen=True)
class Slice:
    arch: str
    dylibs: tuple[str, ...]


def _read_thin(data: bytes, offset: int) -> Slice:
    magic = struct.unpack_from("<I", data, offset)[0]
    if magic in (_MH_MAGIC_64, _MH_MAGIC):
        endian = "<"
    elif magic in (_MH_CIGAM_64, _MH_CIGAM):
        endian = ">"
    else:
        raise NotMachO(f"unknown magic {magic:#x} at offset {offset}")
    is64 = magic in (_MH_MAGIC_64, _MH_CIGAM_64)
    cputype, _sub, _filetype, ncmds, sizeofcmds = struct.unpack_from(endian + "iiiII", data, offset + 4)
    header = 32 if is64 else 28
    if sizeofcmds > _MAX_LOAD_COMMANDS_BYTES or offset + header + sizeofcmds > len(data):
        raise NotMachO("load commands run past the end of the file")
    arch = _CPU_TYPES.get(cputype & 0xFFFFFFFF if cputype >= 0 else cputype & 0xFFFFFFFF, f"cputype-{cputype:#x}")
    dylibs: list[str] = []
    cursor = offset + header
    end = cursor + sizeofcmds
    for _ in range(ncmds):
        if cursor + 8 > end:
            raise NotMachO("truncated load command")
        cmd, cmdsize = struct.unpack_from(endian + "II", data, cursor)
        if cmdsize < 8 or cursor + cmdsize > end:
            raise NotMachO("malformed load command size")
        if cmd in _DYLIB_COMMANDS:
            name_offset = struct.unpack_from(endian + "I", data, cursor + 8)[0]
            raw = data[cursor + name_offset:cursor + cmdsize]
            dylibs.append(raw.split(b"\0", 1)[0].decode("utf-8", "replace"))
        cursor += cmdsize
    return Slice(arch, tuple(dylibs))


def read(path) -> tuple[Slice, ...]:
    """Every architecture slice of the Mach-O file at ``path``. Raises :class:`NotMachO` for anything else."""
    path = Path(path)
    with open(path, "rb") as handle:
        head = handle.read(8)
        if len(head) < 8:
            raise NotMachO("file too short")
        magic_be = struct.unpack(">I", head[:4])[0]
        if magic_be in (_FAT_MAGIC, _FAT_MAGIC_64):
            count = struct.unpack(">I", head[4:8])[0]
            if count > 32:
                raise NotMachO("implausible slice count")
            entry = 32 if magic_be == _FAT_MAGIC_64 else 20
            table = handle.read(count * entry)
            slices = []
            for index in range(count):
                if magic_be == _FAT_MAGIC_64:
                    _cpu, _sub, offset, size, _align, _res = struct.unpack_from(">iiQQII", table, index * entry)
                else:
                    _cpu, _sub, offset, size, _align = struct.unpack_from(">iiIII", table, index * entry)
                handle.seek(offset)
                body = handle.read(min(size, _MAX_LOAD_COMMANDS_BYTES + 64))
                slices.append(_read_thin(body, 0))
            return tuple(slices)
        handle.seek(0)
        body = handle.read(_MAX_LOAD_COMMANDS_BYTES + 64)
    return (_read_thin(body, 0),)


def architectures(path) -> Optional[tuple[str, ...]]:
    """The architectures of ``path`` (``("arm64",)`` for a native Apple Silicon binary), or None if not Mach-O."""
    try:
        return tuple(s.arch for s in read(path))
    except (NotMachO, OSError, struct.error):
        return None


def foreign_dependencies(path, *, inside: Optional[Path] = None) -> Optional[list[str]]:
    """Linked libraries of ``path`` that are neither system libraries nor ``@rpath``/``@loader_path``/
    ``@executable_path`` references (which resolve beside the binary; ``inside`` is accepted for absolute paths within
    an app-owned folder). An empty list means every dependency is a system library or the binary's own. None when the
    file cannot be read as Mach-O. A path under Homebrew, MacPorts or ``/usr/local`` is always foreign."""
    try:
        slices = read(path)
    except (NotMachO, OSError, struct.error):
        return None
    foreign: list[str] = []
    root = str(Path(inside).resolve()) + "/" if inside is not None else None
    for one in slices:
        for dylib in one.dylibs:
            if dylib.startswith(FORBIDDEN_PREFIXES):
                foreign.append(dylib)
            elif dylib.startswith(SYSTEM_PREFIXES) or dylib.startswith(("@rpath/", "@loader_path/",
                                                                         "@executable_path/")):
                continue
            elif root is not None and dylib.startswith(root):
                continue
            else:
                foreign.append(dylib)
    return sorted(set(foreign))
