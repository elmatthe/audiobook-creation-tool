"""v0.8.x P5 (macOS closeout): on a Mac a narration that reaches the assembly gate is always assembled on disk.

Measured natively on an Apple Silicon Mac (P5 closeout, the real narration of a 37-minute Edge file, evidence
``files/dev-work/macos-p5-closeout/``): ``read_book``'s in-memory chapter join (``combined += AudioSegment.from_file(part)``)
kept the memory of every superseded copy in the process, so the footprint grew with the square of the number of parts:
0.43 GiB for 32 paragraph parts, 4.86 GiB for 128 (101 MiB of PCM, where ``peak_bytes_for_pcm`` budgets 0.37 GiB), 10 GiB by
232 (66 minutes). In the real 37-minute run the app process reached 5.2 GiB. The disk route on the same 128 parts: 28 MiB,
the PCM identical.

The rule (``worker_limits.IN_MEMORY_ASSEMBLY``, false on darwin only): at or above ``ASSEMBLY_GATE_MIN_PCM_BYTES`` the gate
offers a Mac the disk route alone. Its room, its reservation (``DISK_ASSEMBLY_BYTES``), its wait, its failure and Cancel are
the gate's own. Below the minimum nothing changes. Every other platform keeps the in-memory route. The modules that test
that route pin the flag on, so they test it on every machine.

  * A. The rule: the source line, its value here, and that only the gate's entry point reads it.
  * B. The gate: disk only with plenty of memory, the small join untouched, the reservation, Cancel, no room. Each case has a
    negative control with the flag on, which takes the in-memory route, so the test can tell.
  * C. The Edge routes end to end (direct and folder): with the flag off no in-memory route runs, the chapter joins and
    the final encode go through ``disk_assembly``, and the MP3 is the in-memory route's MP3, to the byte.
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

import pytest

from shared.cancellation import ConversionCancelled
from tts import disk_assembly
from tts import worker_limits as wl

from test_assembly_on_disk import (  # noqa: E402  (the v0.7.1 helpers: real 24 kHz Edge-format clips, offline engine)
    clip_for, direct_mp3, folder_mp3, forbid_memory_routes, needs_ffmpeg, offline, write_book)

GB = 1024 ** 3
MB = 1024 ** 2
SRC = Path(wl.__file__).read_text(encoding="utf-8")
assert clip_for and offline  # used as a helper and as a fixture below


def _gate(available_gb: float = 20, *, wait_seconds: float | None = None) -> wl.AssemblyGate:
    return wl.AssemblyGate(lambda: wl.MemoryInfo(int(available_gb * GB), 32 * GB), poll_seconds=0.001,
                           wait_seconds=wait_seconds)


@pytest.fixture()
def plenty(monkeypatch):
    """20 GB free: any of these narrations would be admitted in memory by the in-memory rule."""
    gate = _gate(20)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", gate)
    return gate


def _routes(pcm_bytes: int, **kwargs) -> list[str]:
    taken: list[str] = []
    wl.assemble(pcm_bytes, lambda: taken.append("memory"), lambda: taken.append("disk"), **kwargs)
    return taken


# --------------------------------------------------------------------------- A. the rule
def test_the_rule_is_darwin_only_and_holds_on_this_machine():
    assert "IN_MEMORY_ASSEMBLY = sys.platform != \"darwin\"" in SRC
    assert wl.IN_MEMORY_ASSEMBLY is (sys.platform != "darwin")


def test_only_the_gates_entry_point_reads_the_rule():
    """One decision point: ``assembly_place``. The routes, the gate class and the callers never consult it themselves."""
    tree = ast.parse(SRC)
    readers = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
               and any(isinstance(n, ast.Name) and n.id == "IN_MEMORY_ASSEMBLY" for n in ast.walk(node))}
    assert readers == {"assembly_place"}
    scripts = Path(wl.__file__).resolve().parents[1]
    elsewhere = [str(p.relative_to(scripts)) for p in scripts.rglob("*.py")
                 if p.name != "worker_limits.py" and "IN_MEMORY_ASSEMBLY" in p.read_text(encoding="utf-8", errors="replace")]
    assert elsewhere == []


def test_the_gate_class_keeps_its_in_memory_route_unless_told():
    """``disk_only`` defaults to off: every existing caller of the class, and every other platform, is as it was."""
    assert inspect.signature(wl.AssemblyGate.place).parameters["disk_only"].default is False
    assert inspect.signature(wl.AssemblyGate._route).parameters["disk_only"].default is False


# --------------------------------------------------------------------------- B. the gate
@pytest.mark.parametrize("pcm", [wl.ASSEMBLY_GATE_MIN_PCM_BYTES, 101 * MB, 3 * GB])
def test_on_a_mac_a_narration_at_the_gate_goes_to_disk_however_much_is_free(monkeypatch, plenty, pcm):
    monkeypatch.setattr(wl, "IN_MEMORY_ASSEMBLY", False)
    assert _routes(pcm) == ["disk"]
    monkeypatch.setattr(wl, "IN_MEMORY_ASSEMBLY", True)  # negative control: the in-memory rule admits it
    assert _routes(pcm) == ["memory"]


def test_below_the_gate_a_small_join_stays_in_memory_on_every_platform(monkeypatch, plenty):
    for flag in (False, True):
        monkeypatch.setattr(wl, "IN_MEMORY_ASSEMBLY", flag)
        assert _routes(wl.ASSEMBLY_GATE_MIN_PCM_BYTES - 1) == ["memory"]
    assert plenty._in_use == 0 and plenty._in_memory == 0 and plenty._on_disk == 0


def test_on_a_mac_the_place_reserves_what_the_disk_route_needs_and_gives_it_back(monkeypatch, plenty):
    monkeypatch.setattr(wl, "IN_MEMORY_ASSEMBLY", False)
    seen = {}

    def on_disk():
        seen.update(in_use=plenty._in_use, on_disk=plenty._on_disk, in_memory=plenty._in_memory)

    wl.assemble(101 * MB, lambda: pytest.fail("in memory on a Mac"), on_disk)
    assert seen == {"in_use": wl.DISK_ASSEMBLY_BYTES, "on_disk": 1, "in_memory": 0}
    assert (plenty._in_use, plenty._on_disk, plenty._in_memory) == (0, 0, 0)


def test_on_a_mac_cancel_before_the_gate_runs_neither_route(monkeypatch, plenty):
    monkeypatch.setattr(wl, "IN_MEMORY_ASSEMBLY", False)
    with pytest.raises(ConversionCancelled):
        _routes(101 * MB, cancel_check=lambda: True)
    assert plenty._in_use == 0


def test_on_a_mac_with_no_room_even_for_disk_it_fails_with_the_gates_reason(monkeypatch):
    gate = _gate(0.01, wait_seconds=0.05)  # 10 MB free: less than DISK_ASSEMBLY_BYTES
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", gate)
    monkeypatch.setattr(wl, "IN_MEMORY_ASSEMBLY", False)
    with pytest.raises(wl.AssemblyMemoryError):
        _routes(101 * MB)
    assert gate._in_use == 0


def test_on_a_mac_a_wait_names_the_disk_routes_need_not_the_in_memory_budget(monkeypatch):
    gate = _gate(0.01, wait_seconds=0.05)
    monkeypatch.setattr(wl, "ASSEMBLY_GATE", gate)
    monkeypatch.setattr(wl, "IN_MEMORY_ASSEMBLY", False)
    said: list[str] = []
    with pytest.raises(wl.AssemblyMemoryError):
        _routes(3 * GB, note=said.append)
    assert said and "about 0.1 GB" in said[0], said  # DISK_ASSEMBLY_BYTES, never the 3 GB narration's in-memory budget


# --------------------------------------------------------------------------- C. the Edge routes, end to end
@pytest.fixture()
def counted_disk_routes(monkeypatch):
    calls = {"join_to_flac": 0, "encode_mp3": 0}
    for name in calls:
        real = getattr(disk_assembly, name)

        def counting(*args, _real=real, _name=name, **kwargs):
            calls[_name] += 1
            return _real(*args, **kwargs)

        monkeypatch.setattr(disk_assembly, name, counting)
    return calls


@needs_ffmpeg
def test_on_a_mac_the_direct_route_assembles_on_disk_and_gives_the_same_mp3(tmp_path, offline, monkeypatch, plenty,
                                                                             counted_disk_routes):
    source = write_book(tmp_path / "in")
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)  # the test book is small: every join reaches the gate
    monkeypatch.setattr(wl, "IN_MEMORY_ASSEMBLY", True)
    in_memory = direct_mp3(source, tmp_path / "memory")
    assert counted_disk_routes == {"join_to_flac": 0, "encode_mp3": 0}, "negative control: memory was free, so no disk"

    monkeypatch.setattr(wl, "IN_MEMORY_ASSEMBLY", False)
    forbid_memory_routes(monkeypatch)
    assert direct_mp3(source, tmp_path / "mac") == in_memory
    assert counted_disk_routes["join_to_flac"] == 2, "both chapters were joined on disk"
    assert counted_disk_routes["encode_mp3"] == 1, "the one encode ran on disk"
    assert plenty._in_use == 0


@needs_ffmpeg
def test_on_a_mac_the_folder_route_assembles_on_disk_and_gives_the_same_mp3(tmp_path, offline, monkeypatch, plenty,
                                                                             counted_disk_routes):
    source = write_book(tmp_path / "in", "".join(f"Sentence number {n} of this long text, which is read in chunks. "
                                                 for n in range(300)))
    monkeypatch.setattr(wl, "ASSEMBLY_GATE_MIN_PCM_BYTES", 0)
    monkeypatch.setattr(wl, "IN_MEMORY_ASSEMBLY", True)
    in_memory = folder_mp3(source, tmp_path / "memory")
    assert counted_disk_routes["encode_mp3"] == 0

    monkeypatch.setattr(wl, "IN_MEMORY_ASSEMBLY", False)
    forbid_memory_routes(monkeypatch)
    assert folder_mp3(source, tmp_path / "mac") == in_memory
    assert counted_disk_routes["encode_mp3"] == 1
    assert not any((tmp_path / "mac").rglob("*.wav")), "nothing of the assembly is left behind"
