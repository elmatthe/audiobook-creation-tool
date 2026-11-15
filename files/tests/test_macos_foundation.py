"""v0.8.x P1A -- the macOS foundation: platform-keyed hash locks, Mach-O reading, the app-owned FFmpeg rules and
acquisition, the per-volume case probe, the coordinator's interpreter, the launcher, and the Git index invariants.

Most of these run on every platform (the platform is injected), so the Windows answers are held here too: the Windows
lock, its store and cache folders, its generator output and its requirements stamp are byte-for-byte what v0.8.0
shipped. The few that need a real Mac (Mach-O of real binaries, codesign, APFS) carry the one native-macOS reason.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import re
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
REQUIREMENTS = SCRIPTS / "requirements.txt"
WINDOWS_LOCK = SCRIPTS / "requirements-lock-windows-py312.txt"
MACOS_LOCK = SCRIPTS / "requirements-lock-macos-arm64-py312.txt"
LAUNCHER = REPO_ROOT / "Setup_and_Run-audiobook-creation-tool.command"
STAGE0 = SCRIPTS / "shared" / "bootstrap_host_macos.sh"
NATIVE_MACOS = "native macOS only (P1A): bash 3.2 stage 0, POSIX process groups, Mach-O and codesign checks"
native = pytest.mark.skipif(sys.platform != "darwin", reason=NATIVE_MACOS)

from shared import base_packages, bootstrap, ffmpeg_health, ffmpeg_portable, macho  # noqa: E402


# --------------------------------------------------------------------------- #
#  Locks (MAC-005): one per platform; Windows unchanged
# --------------------------------------------------------------------------- #
def test_each_platform_has_its_own_lock_and_windows_keeps_its_released_one():
    win = base_packages.lock_path(REQUIREMENTS, platform="win32", machine="AMD64")
    mac = base_packages.lock_path(REQUIREMENTS, platform="darwin", machine="arm64")
    assert win == WINDOWS_LOCK and base_packages.LOCK_NAME == WINDOWS_LOCK.name
    assert mac == MACOS_LOCK
    # Where no lock applies the answers stay the released ones, and nothing is installed from them.
    assert base_packages.lock_path(REQUIREMENTS, platform="darwin", machine="x86_64") == WINDOWS_LOCK
    assert base_packages.lock_path(REQUIREMENTS, platform="linux", machine="x86_64") == WINDOWS_LOCK


@pytest.mark.parametrize("platform, machine, version, applies", [
    ("win32", "AMD64", (3, 12), True), ("win32", "x86_64", (3, 12, 15), True), ("win32", "AMD64", (3, 11), False),
    ("win32", "ARM64", (3, 12), False), ("darwin", "arm64", (3, 12), True), ("darwin", "arm64", (3, 13), False),
    ("darwin", "x86_64", (3, 12), False), ("linux", "x86_64", (3, 12), False), ("darwin", "arm64", None, False),
])
def test_lock_applies_per_platform(platform, machine, version, applies):
    assert base_packages.lock_applies(version, platform=platform, machine=machine) is applies


def test_store_cache_and_quarantine_are_platform_scoped_on_a_mac_only(tmp_path):
    rd = tmp_path / "files" / "runtime-data"
    assert base_packages.store_dir(tmp_path, platform="win32", machine="AMD64") == rd / "python-packages"
    assert base_packages.cache_dir(tmp_path, platform="win32", machine="AMD64") == rd / "pip-cache"
    assert base_packages.quarantine_dir(tmp_path, platform="win32", machine="AMD64") == \
        rd / "python-packages-quarantine"
    assert base_packages.store_dir(tmp_path, platform="darwin", machine="arm64") == \
        rd / "python-packages" / "macosx_arm64"
    assert base_packages.cache_dir(tmp_path, platform="darwin", machine="arm64") == rd / "pip-cache" / "macosx_arm64"
    assert base_packages.quarantine_dir(tmp_path, platform="darwin", machine="arm64") == \
        rd / "python-packages-quarantine" / "macosx_arm64"


def _artifact_kind(name: str) -> str:
    if name.endswith((".tar.gz", ".zip")):
        return "sdist"
    if name.endswith("-none-any.whl"):
        return "pure"
    if "universal2" in name:
        return "universal2"
    if re.search(r"macosx_\d+_\d+_arm64\.whl$", name):
        return "arm64"
    return "foreign"


def test_the_macos_lock_is_complete_hashed_native_and_freezes_the_windows_versions():
    text = MACOS_LOCK.read_text(encoding="utf-8")
    assert "\r" not in text
    problems = base_packages.lock_problems(REQUIREMENTS.read_text(encoding="utf-8"), text,
                                           hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest())
    assert problems == []
    mac = base_packages.parse_lock(text)
    win = base_packages.parse_lock(WINDOWS_LOCK.read_text(encoding="utf-8"))
    assert mac.header[base_packages.HEADER_RESOLVER].endswith("CPython 3.12 macosx_arm64")
    kinds = {}
    for entry in mac.entries:
        assert len(entry.sha256) == 1, entry.name
        kinds.setdefault(_artifact_kind(entry.artifact), []).append(entry.artifact)
    assert "foreign" not in kinds, kinds.get("foreign")
    assert sorted(kinds["sdist"]) == ["antlr4-python3-runtime-4.9.3.tar.gz", "docopt-0.6.2.tar.gz"]
    # The same versions as Windows: nothing upgraded, nothing added; only the Windows-only colorama drops out.
    assert {e.key: e.version for e in mac.entries} == {e.key: e.version for e in win.entries if e.key != "colorama"}
    by_key = mac.by_key()
    assert by_key["torch"].artifact == "torch-2.6.0-cp312-none-macosx_11_0_arm64.whl"
    assert by_key["numpy"].version == "1.26.4" and by_key["torch"].version == "2.6.0"


def _generator():
    spec = importlib.util.spec_from_file_location("act_lock_generator",
                                                  REPO_ROOT / "files" / "dev-tools" / "lock_base_requirements.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("platform, lock", [("win_amd64", WINDOWS_LOCK), ("macosx_arm64", MACOS_LOCK)])
def test_the_generator_renders_each_committed_lock_byte_for_byte(platform, lock):
    """The Windows lock's rendering is unchanged by the platform parameter (and the macOS one is reproducible)."""
    generator = _generator()
    parsed = base_packages.parse_lock(lock.read_text(encoding="utf-8"))
    entries = [{"name": e.name, "version": e.version, "sha256": e.sha256[0], "artifact": e.artifact}
               for e in parsed.entries]
    pip_version = parsed.header[base_packages.HEADER_RESOLVER].split(",")[0].split()[1]
    rendered = generator._render(entries, parsed.header[base_packages.HEADER_SOURCE], pip_version, platform)
    assert rendered == lock.read_text(encoding="utf-8")


def test_the_requirements_stamp_on_windows_is_computed_exactly_as_released(monkeypatch):
    monkeypatch.setattr(base_packages, "lock_target", lambda **kw: base_packages.WINDOWS_LOCK)
    expected = hashlib.sha256(REQUIREMENTS.read_bytes())
    expected.update(b"\0" + b"requirements-lock-windows-py312.txt" + b"\0" + WINDOWS_LOCK.read_bytes())
    assert bootstrap.requirements_fingerprint() == expected.hexdigest()


def test_a_mac_never_reinstalls_without_the_locks_hashes(monkeypatch):
    monkeypatch.setattr(bootstrap, "IS_MAC", True)
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", False)
    monkeypatch.setattr(bootstrap, "_applicable_lock", lambda venv_py, log=None: None)
    monkeypatch.setattr(bootstrap, "_run", lambda *a, **k: pytest.fail("an unhashed reinstall was attempted"))
    assert bootstrap._force_reinstall(Path("/nonexistent/python"), "nltk", lambda line: None) is False


def test_a_mac_never_installs_without_the_locks_hashes(monkeypatch):
    monkeypatch.setattr(bootstrap, "IS_MAC", True)
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", False)
    monkeypatch.setattr(bootstrap, "_applicable_lock", lambda venv_py, log=None: None)
    monkeypatch.setattr(bootstrap, "_pip", lambda *a, **k: pytest.fail("an unhashed pip install was attempted"))
    lines = []
    assert bootstrap.install_base_packages(Path("/nonexistent/python"), lines.append) is False
    assert any("nothing was installed" in line for line in lines)


# --------------------------------------------------------------------------- #
#  Mach-O (no lipo/otool: they are developer-tool shims on macOS)
# --------------------------------------------------------------------------- #
def _thin(cputype: int, dylibs: list[str]) -> bytes:
    commands = b""
    for name in dylibs:
        raw = name.encode() + b"\0"
        size = (24 + len(raw) + 7) // 8 * 8
        commands += struct.pack("<IIIIII", 0xC, size, 24, 0, 0, 0) + raw.ljust(size - 24, b"\0")
    header = struct.pack("<IiiIIIII", 0xFEEDFACF, cputype, 0, 2, len(dylibs), len(commands), 0, 0)
    return header + commands


def test_macho_reads_architectures_and_linked_libraries(tmp_path):
    arm = tmp_path / "arm"
    arm.write_bytes(_thin(0x0100000C, ["/usr/lib/libSystem.B.dylib", "@rpath/libx.dylib",
                                       "/System/Library/Frameworks/AudioToolbox.framework/AudioToolbox"]))
    assert macho.architectures(arm) == ("arm64",)
    assert macho.foreign_dependencies(arm) == []
    brew = tmp_path / "brew"
    brew.write_bytes(_thin(0x0100000C, ["/usr/lib/libSystem.B.dylib", "/opt/homebrew/opt/lame/lib/libmp3lame.dylib"]))
    assert macho.foreign_dependencies(brew) == ["/opt/homebrew/opt/lame/lib/libmp3lame.dylib"]
    intel = _thin(0x01000007, [])
    fat = tmp_path / "fat"
    fat.write_bytes(struct.pack(">II", 0xCAFEBABE, 2) + struct.pack(">iiIII", 0x01000007, 3, 64, len(intel), 0)
                    + struct.pack(">iiIII", 0x0100000C, 0, 64 + len(intel), len(arm.read_bytes()), 0)
                    + b"\0" * (64 - 48) + intel + arm.read_bytes())
    assert macho.architectures(fat) == ("x86_64", "arm64")
    text = tmp_path / "script"
    text.write_text("#!/bin/sh\n")
    assert macho.architectures(text) is None and macho.foreign_dependencies(text) is None


@native
def test_macho_agrees_with_the_system_on_real_binaries():
    assert "arm64" in macho.architectures("/usr/bin/file")
    assert macho.architectures(sys.executable) == ("arm64",)
    assert macho.foreign_dependencies(os.path.realpath(sys.executable)) == []


# --------------------------------------------------------------------------- #
#  FFmpeg on macOS (D3): only the app's own build, arm64, with aac_at
# --------------------------------------------------------------------------- #
@pytest.fixture
def ffmpeg_sandbox(monkeypatch, tmp_path):
    resources = tmp_path / "runtime-data"
    resources.mkdir()
    monkeypatch.setattr(ffmpeg_health, "RESOURCES_DIR", resources)
    monkeypatch.setattr(ffmpeg_health, "BIN_DIR", tmp_path / "bin")
    monkeypatch.setattr(ffmpeg_portable, "RESOURCES_DIR", resources)
    monkeypatch.setattr(ffmpeg_health, "_winget_package_dirs", lambda: [])
    return tmp_path


def test_a_mac_looks_for_ffmpeg_only_in_the_apps_own_folders(monkeypatch, ffmpeg_sandbox, tmp_path):
    monkeypatch.setattr(ffmpeg_health, "IS_MAC", True)
    elsewhere = tmp_path / "homebrew-bin"
    elsewhere.mkdir()
    monkeypatch.setenv("PATH", str(elsewhere))
    monkeypatch.setattr(ffmpeg_health, "_brew_dirs", lambda: [elsewhere])
    dirs = ffmpeg_health.candidate_directories()
    assert elsewhere not in dirs and dirs[0] == ffmpeg_health.BIN_DIR


def test_an_earlier_homebrew_pin_is_never_a_macs_pin(monkeypatch, ffmpeg_sandbox, tmp_path):
    brew = tmp_path / "opt-homebrew-bin"
    brew.mkdir()
    for name in ("ffmpeg", "ffprobe"):
        (brew / f"{name}{ffmpeg_health.EXE}").write_text("x")
    monkeypatch.setattr(ffmpeg_health, "IS_MAC", False)
    pinned = ffmpeg_health.establish(runner=lambda exe: (True, "ffmpeg version 9.0.1"),
                                     candidates=[ffmpeg_health.pair_in(brew)])
    assert pinned is not None and ffmpeg_health.pinned_pair() is not None
    monkeypatch.setattr(ffmpeg_health, "IS_MAC", True)
    assert ffmpeg_health.pinned_pair() is None, "a pin outside files/bin is ignored on a Mac"


def test_a_non_native_ffmpeg_is_refused_before_it_is_run(monkeypatch, ffmpeg_sandbox, tmp_path):
    folder = tmp_path / "bin"
    folder.mkdir()
    for name in ("ffmpeg", "ffprobe"):
        (folder / f"{name}{ffmpeg_health.EXE}").write_bytes(_thin(0x01000007, []))  # x86_64
    monkeypatch.setattr(ffmpeg_health, "IS_MAC", True)
    monkeypatch.setattr(ffmpeg_health._sp, "run", lambda *a, **k: pytest.fail("a non-native binary was executed"))
    proof = ffmpeg_health.prove_pair(ffmpeg_health.pair_in(folder))
    assert not proof.ok and "not a native Apple Silicon program" in proof.detail


def test_no_macos_ffmpeg_is_adopted_and_nothing_unqualified_is_downloaded(ffmpeg_sandbox):
    candidate = ffmpeg_portable.MACOS_RIEDL_9_0_1_CANDIDATE
    assert ffmpeg_portable.MACOS_FFMPEG_PIN is None
    assert candidate.adopted is False and "proof 8" in candidate.status
    assert candidate.build_path == "1787073674_9.0.1" and "redirect" not in candidate.base_url
    lines = []
    log = type("L", (), {"line": lambda self, text: lines.append(text)})()
    opened = []
    assert ffmpeg_portable.acquire_macos(log, opener=lambda url: opened.append(url)) is None
    assert opened == [] and any("No FFmpeg build for macOS has been approved" in line for line in lines)


def _fixture_build(member_bytes: dict, **changes) -> ffmpeg_portable.MacBuild:
    files = {}
    for name, body in member_bytes.items():
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            info = zipfile.ZipInfo(name)
            info.external_attr = (0o100755 << 16)
            zf.writestr(info, body)
        data = buffer.getvalue()
        files[name] = (data, ffmpeg_portable.MacFile(f"{name}.zip", len(data), hashlib.sha256(data).hexdigest(), name,
                                                     len(body), hashlib.sha256(body).hexdigest()))
    build = ffmpeg_portable.MacBuild("9.0.1", "fixture", "https://example.invalid/macos", files["ffmpeg"][1],
                                     files["ffprobe"][1], "Developer ID Application: Fixture (TEAMID)", "TEAMID",
                                     False, "fixture")
    for key, value in changes.items():
        object.__setattr__(build, key, value)
    return build, {f"{n}.zip": d for n, (d, _f) in files.items()}


class _Log:
    def __init__(self):
        self.lines = []

    def line(self, text):
        self.lines.append(text)


def test_a_zip_with_other_bytes_is_refused_and_its_part_file_removed(ffmpeg_sandbox):
    build, served = _fixture_build({"ffmpeg": b"A" * 100, "ffprobe": b"B" * 100})
    log = _Log()
    tampered = served["ffmpeg.zip"][:-1] + b"X"
    result = ffmpeg_portable._mac_download(build, build.ffmpeg, log, lambda url: io.BytesIO(tampered))
    assert result is None and any("is not the recorded build" in line for line in log.lines)
    assert list(ffmpeg_portable.macos_staging_root(build).iterdir()) == []
    oversize = served["ffmpeg.zip"] + b"extra"
    assert ffmpeg_portable._mac_download(build, build.ffmpeg, log, lambda url: io.BytesIO(oversize)) is None


@pytest.mark.parametrize("problem", ["two members", "wrong name", "symlink", "setuid", "other program bytes"])
def test_an_unsafe_ffmpeg_zip_is_refused(ffmpeg_sandbox, tmp_path, problem):
    build, served = _fixture_build({"ffmpeg": b"A" * 100, "ffprobe": b"B" * 100})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        if problem == "two members":
            zf.writestr("ffmpeg", b"A" * 100)
            zf.writestr("extra", b"x")
        elif problem == "wrong name":
            zf.writestr("../ffmpeg", b"A" * 100)
        else:
            info = zipfile.ZipInfo("ffmpeg")
            info.external_attr = {"symlink": 0o120777, "setuid": 0o104755}.get(problem, 0o100755) << 16
            zf.writestr(info, b"A" * 100 if problem != "other program bytes" else b"Z" * 100)
    archive = tmp_path / "ffmpeg.zip"
    archive.write_bytes(buffer.getvalue())
    log = _Log()
    assert ffmpeg_portable._mac_extract(archive, build.ffmpeg, tmp_path / "stage", log) is False
    assert log.lines, problem


def test_interrupted_macos_acquisitions_leave_only_what_the_next_run_removes(ffmpeg_sandbox):
    build, _served = _fixture_build({"ffmpeg": b"A", "ffprobe": b"B"})
    root = ffmpeg_portable.macos_staging_root(build)
    root.mkdir(parents=True)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (root / f".act-stage-ffmpeg-{dead.pid}").mkdir()
    (root / "ffmpeg.zip.part").write_bytes(b"partial")
    live = root / f".act-stage-ffmpeg-{os.getppid()}"
    live.mkdir()
    removed = {p.name for p in ffmpeg_portable.recover_macos_staging(build)}
    assert removed == {f".act-stage-ffmpeg-{dead.pid}", "ffmpeg.zip.part"}
    assert live.exists()


def test_a_mac_ffmpeg_repair_never_runs_homebrew_and_says_what_it_tried(monkeypatch, ffmpeg_sandbox):
    monkeypatch.setattr(bootstrap, "IS_MAC", True)
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", False)
    monkeypatch.setattr(bootstrap, "_run", lambda cmd, **kw: pytest.fail(f"ran {cmd}"))
    monkeypatch.setattr(ffmpeg_health, "establish", lambda log=None, **kw: None)
    monkeypatch.setattr(ffmpeg_portable, "acquire_macos", lambda log=None, **kw: None)
    result = bootstrap.repair_ffmpeg(_Log())
    assert not result.ready
    assert result.routes == (bootstrap.FFMPEG_ROUTE_EXISTING, bootstrap.FFMPEG_ROUTE_PORTABLE)
    assert "Homebrew" not in result.notice() and "brew" not in result.notice()
    assert bootstrap._package_manager_route() is None


RIEDL_ZIPS = REPO_ROOT / "files" / "temp" / "bootstrap" / "riedl-9.0.1"


@native
@pytest.mark.skipif(not (RIEDL_ZIPS / "ffmpeg.zip").is_file(), reason="the Riedl 9.0.1 ZIPs are not downloaded here")
def test_the_candidate_passes_proofs_1_to_7_through_the_production_acquisition(monkeypatch, ffmpeg_sandbox):
    """Real bytes, real codesign (in the guardian's group), real execution; served from the local verified copies."""
    from shared import child_ownership

    candidate = ffmpeg_portable.MACOS_RIEDL_9_0_1_CANDIDATE
    owner = child_ownership.Owner()
    log = _Log()
    try:
        pair = ffmpeg_portable.acquire_macos(log, build=candidate, owner=owner,
                                             opener=lambda url: open(RIEDL_ZIPS / url.rsplit("/", 1)[1], "rb"))
    finally:
        owner.shutdown()
    assert pair is not None, "\n".join(log.lines)
    assert pair.directory == ffmpeg_health.BIN_DIR / "ffmpeg" / "9.0.1" / "bin"
    assert ffmpeg_health.pinned_pair() is not None
    assert any("aac_at and libmp3lame present" in line for line in log.lines)
    assert not any(ffmpeg_portable.macos_staging_root(candidate).iterdir())
    # A build signed by anyone else is refused (proof 5): the recorded identity is the authority.
    other = ffmpeg_portable.MacBuild(**{**candidate.__dict__, "team_id": "OTHERTEAM1"})
    problem = ffmpeg_portable.verify_macos_build(other, pair.directory, owner=child_ownership.Owner())
    assert problem is not None and "proof 5" in problem


# --------------------------------------------------------------------------- #
#  Interpreter: the app's own only (D1/D2, MAC-004, MAC-028)
# --------------------------------------------------------------------------- #
def test_a_mac_builds_its_environment_only_on_the_apps_own_python(monkeypatch):
    monkeypatch.setattr(bootstrap, "IS_MAC", True)
    monkeypatch.setattr(bootstrap, "IS_WINDOWS", False)
    assert bootstrap._candidate_interpreters() == [[str(bootstrap.APP_PYTHON)]]
    monkeypatch.setattr(bootstrap, "_is_app_python", lambda exe: False)
    monkeypatch.setattr(bootstrap, "_tcl_tk_ok", lambda argv: True)
    monkeypatch.setattr(bootstrap, "_candidate_is_worth_probing", lambda argv: False)
    assert bootstrap.find_suitable_python(_Log()) is None, "the running Python is not the app's own: never used"
    assert bootstrap.install_python(_Log()) is None


@native
def test_app_python_layout_matches_the_coordinators_and_no_path_python_is_a_candidate(monkeypatch):
    from shared import cleanup_state

    assert bootstrap.APP_PYTHON.relative_to(bootstrap.REPO_ROOT).parts == cleanup_state.APP_BASE_PYTHON_PARTS
    assert bootstrap.APP_PYTHON.parts[-2:] == ("bin", "python3.12")
    monkeypatch.setattr(cleanup_state.shutil, "which", lambda name: pytest.fail(f"PATH was searched for {name}"))
    assert all("/usr/bin/" not in str(c) for c in cleanup_state.interpreter_candidates())


# --------------------------------------------------------------------------- #
#  Case-insensitivity is a volume's answer (MAC-015)
# --------------------------------------------------------------------------- #
def test_windows_stays_case_blind(monkeypatch):
    from shared import venv_layout

    monkeypatch.setattr(venv_layout, "_CASE_INSENSITIVE", True)
    assert venv_layout.case_insensitive("anything") is True


@native
def test_a_case_insensitive_apfs_volume_folds_case_and_the_answer_comes_from_the_volume(tmp_path):
    from shared import importing, maintenance, venv_integrity, venv_layout

    blind = importing.filesystem_is_case_insensitive(tmp_path)
    # venv_layout asks the volume itself (it may not import the importer); the two answers never differ.
    assert venv_layout.case_insensitive(tmp_path) is blind
    assert venv_layout.case_insensitive(REPO_ROOT) is importing.filesystem_is_case_insensitive(REPO_ROOT)
    (tmp_path / "App").mkdir()
    upper, lower = tmp_path / "App" / ".Venv", tmp_path / "app" / ".venv"
    assert venv_layout.same_path(upper, lower) is blind
    assert maintenance.same_path(upper, lower) is blind
    assert (venv_integrity._key(upper) == venv_integrity._key(lower)) is blind


# --------------------------------------------------------------------------- #
#  The launcher (D2, MAC-001, MAC-041) and the Git index (MAC-046)
# --------------------------------------------------------------------------- #
def test_the_launcher_uses_stage_0_and_never_homebrew_or_a_path_python():
    text = LAUNCHER.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "bootstrap_host_macos.sh" in code and 'APP_PY="files/runtime-data/python/bin/python3.12"' in code
    for forbidden in (r"\bbrew\b", r"install\.sh", r"command -v", r"python3\.11", r"\bpython3\b(?!\.12)",
                      r"--headless", r"right-click"):
        assert not re.search(forbidden, code), forbidden
    assert "sudo" not in code


def _index(path: Path) -> tuple[str, bytes]:
    rel = path.relative_to(REPO_ROOT).as_posix()
    entry = subprocess.run(["git", "ls-files", "-s", "--", rel], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    if not entry:
        pytest.fail(f"{rel} is not in the Git index")
    mode, blob = entry.split()[:2]
    data = subprocess.run(["git", "cat-file", "blob", blob], cwd=REPO_ROOT, capture_output=True).stdout
    return mode, data


@pytest.mark.parametrize("path", [LAUNCHER, STAGE0], ids=["launcher", "stage0"])
def test_launcher_scripts_are_executable_lf_in_the_index(path):
    mode, data = _index(path)
    assert mode == "100755"
    assert b"\r" not in data and data.startswith(b"#!/bin/bash\n")


# --------------------------------------------------------------------------- #
#  An environment whose creation was interrupted is rebuilt (P1A SIMULATED finding)
# --------------------------------------------------------------------------- #
def _fake_venv(monkeypatch, tmp_path, *, site: bool, pip: bool):
    venv = tmp_path / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("")
    if site:
        packages = venv / "lib" / "python3.12" / "site-packages"
        packages.mkdir(parents=True)
        if pip:
            (packages / "pip-25.0.1.dist-info").mkdir()
            (packages / "pip-25.0.1.dist-info" / "RECORD").write_text("pip/__init__.py,,\n")
    monkeypatch.setattr(bootstrap, "VENV_DIR", venv)
    monkeypatch.setattr(bootstrap, "venv_python", lambda windowed=False: venv / "bin" / "python")
    monkeypatch.setattr(bootstrap, "probe_venv", lambda py: {"version": (3, 12), "ssl": True, "tk": True})
    monkeypatch.setattr(bootstrap.venv_integrity, "foreign_base_python", lambda venv_dir, root: None)
    monkeypatch.setattr(bootstrap.venv_integrity, "repair_requested", lambda venv_dir: False)
    monkeypatch.setattr(bootstrap.venv_integrity, "package_damage", lambda venv_dir, required=(): [])
    return venv


def test_on_a_mac_an_environment_whose_creation_was_cut_short_is_rebuilt(monkeypatch, tmp_path):
    _fake_venv(monkeypatch, tmp_path, site=True, pip=False)
    monkeypatch.setattr(bootstrap, "IS_MAC", True)
    health = bootstrap.assess_venv_health()
    assert (health.state, health.reason) == (bootstrap.VENV_REPAIRABLE, "incomplete")


def test_a_finished_mac_environment_and_one_without_evidence_are_not_called_incomplete(monkeypatch, tmp_path):
    _fake_venv(monkeypatch, tmp_path, site=True, pip=True)
    monkeypatch.setattr(bootstrap, "IS_MAC", True)
    assert bootstrap.assess_venv_health().state == bootstrap.VENV_HEALTHY
    assert bootstrap.venv_creation_cut_short(tmp_path / "no-such-venv") is False


def test_windows_health_does_not_apply_the_mac_rule(monkeypatch, tmp_path):
    _fake_venv(monkeypatch, tmp_path, site=True, pip=False)
    monkeypatch.setattr(bootstrap, "IS_MAC", False)
    assert bootstrap.assess_venv_health().state == bootstrap.VENV_HEALTHY


@native
def test_a_real_venv_is_complete_and_the_same_venv_without_pip_is_not(tmp_path):
    venv = tmp_path / "real-venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True, timeout=300)
    assert bootstrap.venv_creation_cut_short(venv) is False
    import shutil

    for record in (venv / "lib").glob("python3*/site-packages/pip-*.dist-info"):
        shutil.rmtree(record)
    assert bootstrap.venv_creation_cut_short(venv) is True


def test_the_macos_download_names_the_app_not_python_and_never_waits_forever(monkeypatch):
    """The build server answers Python's default user agent with HTTP 403 (found by the P1A SIMULATED run)."""
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["agent"], seen["timeout"] = request.get_header("User-agent"), timeout
        return io.BytesIO(b"")

    monkeypatch.setattr(ffmpeg_portable.urllib.request, "urlopen", fake_urlopen)
    ffmpeg_portable._mac_open("https://example.invalid/ffmpeg.zip")
    assert seen == {"agent": "AudiobookCreationTool", "timeout": ffmpeg_portable.MAC_DOWNLOAD_SOCKET_TIMEOUT_S}
    assert "Python-urllib" not in seen["agent"]
