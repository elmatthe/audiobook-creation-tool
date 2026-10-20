"""v0.6.7 checkpoint B1 (Plan 01B) — the layout after ``scripts/Universal`` was lifted to ``scripts``.

The relocation changed no behaviour, only where the application's packages live: ``shared``, ``tts``, the tool packages (then one
``mp3_tools`` package, split into ``mp3``, ``m4b`` and ``artwork`` by checkpoint B2) and ``launcher.py`` moved up one level and ``scripts/`` became the import root. Every module that derives the repository root
from its own location (several must, because they run before the virtual environment exists) lost one ``.parent``.
These canaries make that class of mistake loud: every derivation has to land on the same folder, the entry point and the
launchers have to name files that exist, no tracked file may name the old layout, and the module maps in the READMEs
have to match the tree. They also pin the one new behaviour B1 added — a warning-only notice about a leftover
``scripts/Universal`` — including that it never deletes or touches anything.
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"

#: Tracked files that may name ``scripts/Universal`` because they are about the move itself.
OLD_LAYOUT_ALLOWED = {
    "files/dev-tools/speech_characterization.py",   # discovers whichever layout it is run against
    "files/tests/test_speech_characterization.py",  # its docstring says the goldens predate the move
    "files/tests/test_layout_canary.py",            # this file
    "scripts/shared/bootstrap.py",                  # the leftover-folder warning names it on purpose
}
CODE_SUFFIXES = {".py", ".toml", ".bat", ".command", ".txt", ".cfg", ".ini"}
TOP_LEVEL_SCRIPTS = {"launcher.py", "verify.py", "requirements.txt", "qwen3-requirements.txt", "README.md"}
PACKAGES = ("shared", "tts", "mp3", "m4b", "artwork")
#: Sub-packages whose modules their parent package README also maps (B2 split ``m4b`` by tool).
README_SUBPACKAGES = {"m4b": ("converter", "maker", "metadata")}


def git_lines(*args: str) -> list[str]:
    result = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        pytest.skip(f"not a git checkout ({result.stderr.strip()[:80]})")
    return [line for line in result.stdout.split("\0" if "-z" in args else "\n") if line]


# --------------------------------------------------------------------------- #
# One repository root, however each module derives it
# --------------------------------------------------------------------------- #
def derived_roots() -> dict[str, Path]:
    from shared import bootstrap, cleanup_state, cleanup_worker, ffmpeg_health, ffmpeg_portable, paths, release
    from tts import chatterbox_synth, qwen3_runtime

    sys.path.insert(0, str(SCRIPTS))
    try:
        import verify
    finally:
        sys.path.remove(str(SCRIPTS))
    return {
        "shared.paths": paths.REPO_ROOT, "shared.bootstrap": bootstrap.REPO_ROOT,
        "shared.ffmpeg_health": ffmpeg_health.REPO_ROOT, "shared.ffmpeg_portable": ffmpeg_portable.REPO_ROOT,
        "shared.release": release.REPO_ROOT, "shared.cleanup_state": cleanup_state.default_repo_root(),
        "shared.cleanup_worker": cleanup_worker.repository_root(), "tts.qwen3_runtime": qwen3_runtime.repo_root(),
        "tts.chatterbox_synth": chatterbox_synth._repo_root(), "verify": verify.REPO_ROOT,
    }


def test_every_module_that_derives_the_repository_root_lands_on_the_same_folder():
    for name, root in derived_roots().items():
        assert Path(root).resolve() == REPO_ROOT.resolve(), f"{name} derives {root}, not {REPO_ROOT}"


def test_the_fallback_root_of_the_two_engine_modules_is_the_same_folder(monkeypatch):
    """Both search the parents for a folder holding ``scripts`` and ``files``; only the fallback is depth-dependent."""
    from tts import chatterbox_synth, qwen3_runtime

    monkeypatch.setattr(Path, "is_dir", lambda self: False)  # the search finds nothing, so the fallback answers
    assert Path(qwen3_runtime.repo_root()).resolve() == REPO_ROOT.resolve()
    assert Path(chatterbox_synth._repo_root()).resolve() == REPO_ROOT.resolve()


def test_the_repository_root_agrees_with_git():
    top = git_lines("rev-parse", "--show-toplevel")[0]
    assert Path(top).resolve() == REPO_ROOT.resolve()


def test_scripts_is_the_import_root_and_the_packages_import_under_their_plain_names():
    from shared import bootstrap, cleanup_worker, paths, release

    sys.path.insert(0, str(SCRIPTS))
    try:
        import verify
    finally:
        sys.path.remove(str(SCRIPTS))
    for label, value in (("paths.SCRIPTS_DIR", paths.SCRIPTS_DIR), ("bootstrap.SCRIPTS_DIR", bootstrap.SCRIPTS_DIR),
                         ("release.SCRIPTS_DIR", release.SCRIPTS_DIR), ("cleanup_worker.IMPORT_ROOT", cleanup_worker.IMPORT_ROOT),
                         ("verify.IMPORT_ROOT", verify.IMPORT_ROOT)):
        assert Path(value).resolve() == SCRIPTS.resolve(), label
    assert paths.TTS_DIR == SCRIPTS / "tts" and paths.MP3_DIR == SCRIPTS / "mp3"
    assert paths.M4B_DIR == SCRIPTS / "m4b" and paths.ARTWORK_DIR == SCRIPTS / "artwork"
    assert not hasattr(paths, "MP3_TOOLS_DIR") and not (SCRIPTS / "mp3_tools" / "__init__.py").exists()
    for package in PACKAGES:
        module = importlib.import_module(package)
        assert Path(module.__file__).resolve().parent == (SCRIPTS / package).resolve(), package
    assert (SCRIPTS / "launcher.py").is_file()
    assert not (SCRIPTS / "Universal" / "launcher.py").exists()


def test_the_data_locations_did_not_move():
    from shared import paths

    assert paths.FILES_DIR == REPO_ROOT / "files" and paths.RESOURCES_DIR == REPO_ROOT / "files" / "runtime-data"
    assert paths.REQUIREMENTS_FILE == SCRIPTS / "requirements.txt"
    assert paths.SETTINGS_FILE == REPO_ROOT / "files" / "runtime-data" / "settings.json"


def test_the_bundled_reference_recordings_are_where_they_were_and_bit_identical():
    import hashlib

    from shared import release
    from tts import qwen3_runtime as rt

    expected = {v.reference_sha256 for v in rt.QWEN3_VOICES if v.kind == rt.KIND_CLONE}
    found = set()
    for relative in release.REFERENCE_ASSETS:
        path = REPO_ROOT / relative
        assert path.is_file(), relative
        found.add(hashlib.sha256(path.read_bytes()).hexdigest())
    assert found == expected and len(found) == 6


def test_whole_tree_parametrizations_see_exactly_the_application_source():
    """``scripts/`` also holds verify.py and machine-local files; those are not application source."""
    import source_probe

    files = source_probe.application_python_files()
    relative = {p.relative_to(SCRIPTS).as_posix() for p in files}
    assert "launcher.py" in relative and "shared/paths.py" in relative and "tts/qwen3_worker.py" in relative
    assert "verify.py" not in relative and "project-status.py" not in relative
    assert all(r == "launcher.py" or r.split("/")[0] in PACKAGES for r in relative)
    assert not any("__pycache__" in r for r in relative)


# --------------------------------------------------------------------------- #
# Entry point and launchers
# --------------------------------------------------------------------------- #
def test_the_entry_point_and_both_launchers_name_files_that_exist():
    from shared import config

    assert config.DEFAULT_ENTRY_POINT == "scripts/launcher.py"
    entry = tomllib.loads((REPO_ROOT / "config.toml").read_text(encoding="utf-8"))["project"]["entry_point"]
    assert entry == "scripts/launcher.py" and (REPO_ROOT / entry).is_file()

    bat = (REPO_ROOT / "Setup_and_Run-audiobook-creation-tool.bat").read_text(encoding="utf-8", errors="replace")
    command = (REPO_ROOT / "Setup_and_Run-audiobook-creation-tool.command").read_text(encoding="utf-8")
    assert 'set "BOOTSTRAP=scripts\\shared\\bootstrap.py"' in bat
    assert 'BOOTSTRAP="scripts/shared/bootstrap.py"' in command
    assert "scripts/shared/close_terminal.py" in command
    for relative in ("scripts/shared/bootstrap.py", "scripts/shared/close_terminal.py"):
        assert (REPO_ROOT / relative).is_file(), relative
    assert "Universal" not in bat and "Universal" not in command


# --------------------------------------------------------------------------- #
# The tracked tree
# --------------------------------------------------------------------------- #
def test_no_legacy_layout_folder_is_tracked_and_scripts_holds_only_the_approved_top_level():
    tracked = git_lines("ls-files", "--", "scripts")
    assert tracked
    for path in tracked:
        top = path.split("/")[1]
        assert top in TOP_LEVEL_SCRIPTS or top in PACKAGES, f"unexpected tracked path under scripts/: {path}"
        assert not path.startswith(("scripts/Universal/", "scripts/MacOS/", "scripts/Windows/")), path


def test_no_tracked_code_or_configuration_file_names_the_old_layout():
    offenders = []
    for relative in git_lines("ls-files", "-z"):
        if Path(relative).suffix.lower() not in CODE_SUFFIXES or relative in OLD_LAYOUT_ALLOWED:
            continue
        path = REPO_ROOT / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"scripts[\\/]+Universal", text):
            offenders.append(relative)
    assert offenders == [], f"these tracked files still name scripts/Universal: {offenders}"


# --------------------------------------------------------------------------- #
# The warning-only notice about a leftover scripts/Universal
# --------------------------------------------------------------------------- #
@pytest.fixture()
def bootstrap_module():
    from shared import bootstrap

    return bootstrap


def make_tree(tmp_path: Path, files: dict[str, bytes]) -> Path:
    root = tmp_path / "repo"
    for relative, data in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    return root


def snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {p.relative_to(root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_no_notice_when_the_old_folder_is_absent(bootstrap_module, tmp_path):
    assert bootstrap_module.stale_layout_warning(make_tree(tmp_path, {"scripts/launcher.py": b"#"})) is None


def test_no_notice_when_the_old_folder_holds_only_ignored_bytecode_caches(bootstrap_module, tmp_path):
    """What a ``git pull`` across the move leaves behind: caches, no source."""
    root = make_tree(tmp_path, {"scripts/Universal/__pycache__/launcher.cpython-312.pyc": b"x",
                                "scripts/Universal/tests/__pycache__/test_x.cpython-312.pyc": b"x"})
    before = snapshot(root)
    assert bootstrap_module.stale_layout_warning(root) is None
    assert snapshot(root) == before


def test_a_notice_names_the_folder_counts_python_files_and_promises_not_to_delete(bootstrap_module, tmp_path):
    root = make_tree(tmp_path, {"scripts/Universal/launcher.py": b"x = 1\n", "scripts/Universal/shared/paths.py": b"y = 2\n",
                                "scripts/Universal/__pycache__/launcher.cpython-312.pyc": b"x", "scripts/Universal/notes.txt": b"n"})
    message = bootstrap_module.stale_layout_warning(root)
    assert message and "scripts" in message and "Universal" in message and "2 Python file" in message
    assert "never deletes" in message and "by hand" in message


def test_the_notice_never_changes_anything(bootstrap_module, tmp_path):
    root = make_tree(tmp_path, {"scripts/Universal/launcher.py": b"x = 1\n", "scripts/Universal/local-notes.py": b"mine\n",
                                "scripts/Universal/__pycache__/a.cpython-312.pyc": b"x", "scripts/launcher.py": b"new"})
    before = snapshot(root)
    assert bootstrap_module.stale_layout_warning(root)
    assert snapshot(root) == before  # nothing deleted, moved, rewritten or touched


def test_the_notice_is_bounded_and_says_at_least_when_it_stops_early(bootstrap_module, tmp_path):
    files = {f"scripts/Universal/pkg/mod{n}.py": b"#" for n in range(40)}
    message = bootstrap_module.stale_layout_warning(make_tree(tmp_path, files), limit=10)
    assert message and "at least" in message


def test_the_notice_never_raises(bootstrap_module, tmp_path, monkeypatch):
    root = make_tree(tmp_path, {"scripts/Universal/launcher.py": b"x"})

    def boom(*args, **kwargs):
        raise OSError("unreadable")

    monkeypatch.setattr(bootstrap_module.os, "walk", boom)
    assert bootstrap_module.stale_layout_warning(root) is None
    (tmp_path / "file-repo" / "scripts").mkdir(parents=True)
    (tmp_path / "file-repo" / "scripts" / "Universal").write_bytes(b"a file, not a folder")
    assert bootstrap_module.stale_layout_warning(tmp_path / "file-repo") is None


@pytest.mark.parametrize("files, expected", [
    ({"scripts/Universal/a.py": b"#"}, "1 Python file"),
    ({"scripts/Universal/a.json": b"{}"}, "1 JSON file"),
    ({"scripts/Universal/a.py": b"#", "scripts/Universal/b.py": b"#", "scripts/Universal/c.json": b"{}"}, "2 Python and 1 JSON file"),
    ({"scripts/Universal/tts/qwen3_models.json": b"{}", "scripts/Universal/__pycache__/x.cpython-312.pyc": b"x"}, "1 JSON file"),
])
def test_python_json_and_mixed_leftovers_each_raise_an_accurate_notice(bootstrap_module, tmp_path, files, expected):
    root = make_tree(tmp_path, files)
    before = snapshot(root)
    warning = bootstrap_module.stale_layout_warning(root)
    notice = bootstrap_module.stale_layout_notice(root)
    assert warning and expected in warning and notice and expected in notice
    assert "never deletes" in warning and "never deletes" in notice
    assert snapshot(root) == before  # byte-for-byte: nothing moved, deleted or rewritten


@pytest.mark.parametrize("files", [
    {"scripts/Universal/__pycache__/a.cpython-312.pyc": b"x"},
    {"scripts/Universal/__pycache__/data.json": b"{}", "scripts/Universal/tests/__pycache__/b.py": b"#"},
    {"scripts/Universal/notes.txt": b"hello", "scripts/Universal/image.png": b"x"},
])
def test_bytecode_only_and_irrelevant_leftovers_stay_silent(bootstrap_module, tmp_path, files):
    root = make_tree(tmp_path, files)
    assert bootstrap_module.stale_layout_warning(root) is None and bootstrap_module.stale_layout_notice(root) is None


def test_the_short_notice_fits_a_status_bar_and_uses_no_absolute_path(bootstrap_module, tmp_path):
    notice = bootstrap_module.stale_layout_notice(make_tree(tmp_path, {"scripts/Universal/a.py": b"#"}))
    assert len(notice) < 160 and str(tmp_path) not in notice and "scripts\\Universal" in notice


def test_main_no_longer_looks_for_the_leftover_so_check_and_launch_only_cannot_report_it(bootstrap_module, monkeypatch):
    """A notice raised in --venv-check (no output) or --launch-only could only be lost or shown twice."""
    def forbidden(*args, **kwargs):
        raise AssertionError("main() must not evaluate the leftover-folder notice")

    monkeypatch.setattr(bootstrap_module, "stale_layout_warning", forbidden)
    monkeypatch.setattr(bootstrap_module, "stale_layout_notice", forbidden)
    monkeypatch.setattr(bootstrap_module, "_platform_sane", lambda: True)
    monkeypatch.setattr(bootstrap_module, "_configure_hf_cache", lambda: None)
    monkeypatch.setattr(bootstrap_module, "_self_test", lambda: 0)
    assert bootstrap_module.main(["--self-test"]) == 0


# ----- the notice reaches the window the launch starts
class FakeProcess:
    def poll(self):
        return None


@pytest.fixture()
def launch(bootstrap_module, monkeypatch, tmp_path):
    """``launch_gui`` with a stub interpreter and a recording ``Popen``; returns (call, spawned, log)."""
    interpreter = tmp_path / "python.exe"
    interpreter.write_bytes(b"")
    target = tmp_path / "launcher.py"
    target.write_text("#", encoding="utf-8")
    spawned = []
    log_lines = []

    class Log:
        def line(self, text):
            log_lines.append(text)

    monkeypatch.setattr(bootstrap_module, "venv_python", lambda windowed=False: interpreter)
    monkeypatch.setattr(bootstrap_module, "_launch_target", lambda: target)
    monkeypatch.setattr(bootstrap_module, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(bootstrap_module, "_LAUNCH_GRACE_SECONDS", 0)
    monkeypatch.setattr(bootstrap_module, "_ffmpeg_in_bin", lambda: None)
    monkeypatch.setattr(bootstrap_module.subprocess, "Popen",
                        lambda argv, **kwargs: spawned.append((argv, kwargs)) or FakeProcess())
    return (lambda: bootstrap_module.launch_gui(Log())), spawned, log_lines


def test_a_real_launch_hands_the_notice_to_the_window_it_starts(bootstrap_module, monkeypatch, launch):
    call, spawned, log_lines = launch
    monkeypatch.setattr(bootstrap_module, "stale_layout_notice", lambda *a, **k: "Old folder X is no longer used.")
    monkeypatch.setattr(bootstrap_module, "stale_layout_warning", lambda *a, **k: "WARNING: long form")
    assert call() is True
    env = spawned[0][1]["env"]
    assert env[bootstrap_module.STARTUP_NOTICE_ENV] == "Old folder X is no longer used."
    assert "WARNING: long form" in log_lines  # the console/log copy is kept too


def test_a_clean_launch_sets_no_notice_and_drops_an_inherited_one(bootstrap_module, monkeypatch, launch):
    call, spawned, log_lines = launch
    monkeypatch.setenv(bootstrap_module.STARTUP_NOTICE_ENV, "stale text from an outer process")
    monkeypatch.setattr(bootstrap_module, "stale_layout_notice", lambda *a, **k: None)
    assert call() is True
    assert bootstrap_module.STARTUP_NOTICE_ENV not in spawned[0][1]["env"]
    assert not any("WARNING" in line for line in log_lines)


def test_a_failing_detection_never_prevents_the_launch(bootstrap_module, monkeypatch, launch):
    call, spawned, _ = launch

    def boom(*args, **kwargs):
        raise RuntimeError("detection exploded")

    monkeypatch.setattr(bootstrap_module, "stale_layout_notice", boom)
    assert call() is True and len(spawned) == 1
    assert bootstrap_module.STARTUP_NOTICE_ENV not in spawned[0][1]["env"]


def test_the_real_tree_launch_environment_is_silent_when_only_bytecode_remains(bootstrap_module, launch):
    call, spawned, _ = launch
    assert call() is True
    assert bootstrap_module.STARTUP_NOTICE_ENV not in spawned[0][1]["env"]


def test_the_notice_variable_name_is_the_same_in_bootstrap_and_the_launcher():
    import launcher
    from shared import bootstrap

    assert launcher.STARTUP_NOTICE_ENV == bootstrap.STARTUP_NOTICE_ENV == "ACT_STARTUP_NOTICE"


def test_a_healthy_tree_produces_no_notice(bootstrap_module):
    """The real repository after the move: no source left in scripts/Universal, so a launch stays silent."""
    assert not (SCRIPTS / "Universal").exists() or bootstrap_module.stale_layout_warning(REPO_ROOT) is None


# --------------------------------------------------------------------------- #
# The README module maps cannot rot
# --------------------------------------------------------------------------- #
README_PATH = re.compile(r"`([A-Za-z0-9_./\-]+\.(?:py|json|md|txt))`")


def readme(relative: str) -> str:
    return (SCRIPTS / relative).read_text(encoding="utf-8")


@pytest.mark.parametrize("package", PACKAGES)
def test_each_package_readme_names_every_module_and_only_real_files(package):
    text = readme(f"{package}/README.md")
    mentioned = set(README_PATH.findall(text))
    for token in mentioned:
        target = (SCRIPTS / package / token).resolve()
        assert target.is_file(), f"{package}/README.md names {token}, which does not exist"
    names = {Path(token).name for token in mentioned}
    folders = [SCRIPTS / package, *(SCRIPTS / package / sub for sub in README_SUBPACKAGES.get(package, ()))]
    modules = {p.name for folder in folders for p in folder.glob("*.py") if p.name != "__init__.py"}
    missing = sorted(modules - names)
    assert not missing, f"{package}/README.md does not mention: {missing}"


def test_the_top_level_readme_names_real_files_and_every_launcher_tool():
    text = readme("README.md")
    for token in README_PATH.findall(text):
        candidates = [SCRIPTS / token, REPO_ROOT / token]
        assert any(c.is_file() for c in candidates), f"scripts/README.md names {token}, which does not exist"
    sys.path.insert(0, str(SCRIPTS))
    try:
        import launcher
    finally:
        sys.path.remove(str(SCRIPTS))
    for spec in launcher.TOOLS:
        entry = spec.module.replace(".", "/") + ".py"
        assert f"`{entry}`" in text, f"scripts/README.md does not point to {entry} for {spec.label}"
