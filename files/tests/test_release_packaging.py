"""The release-archive contract: what ships, what must never ship.

``shared/release.py`` is a developer-only build helper. It packages by *explicit
scope* — it names the handful of root files it wants and walks exactly one tree —
rather than copying the repository and deleting the parts that must not ship. That
distinction is the whole safety argument: a file the packager never names cannot
leak because someone forgot to add it to an exclusion list. The maintainer's
unrelated untracked root ``config-template.toml`` sits directly beside the real
``config.toml`` and is the standing proof that the distinction holds.

Every archive here is built into a pytest temporary directory. Nothing in this
suite writes to ``dist/``, and nothing extracts outside ``tmp_path``.
"""

from __future__ import annotations

import ast
import hashlib
import zipfile
from pathlib import Path

import pytest

from shared import release

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"

OS_NAMES = ("Windows", "MacOS")
LAUNCHERS = {
    "Windows": "Setup_and_Run-audiobook-creation-tool.bat",
    "MacOS": "Setup_and_Run-audiobook-creation-tool.command",
}
ROOT_MEMBERS = {"README.md", "config.toml"}


# --------------------------------------------------------------------------- #
# Building
# --------------------------------------------------------------------------- #


def build(repo_root: Path, dist: Path, os_name: str) -> Path:
    """Build one archive with the packager pointed at *repo_root*.

    The module resolves its own location at import time, so redirecting it is a
    matter of swapping the three module globals and putting them back. The real
    ``main()`` path is not used because it would write into the repository's own
    ``dist/``.
    """
    saved = (release.REPO_ROOT, release.SCRIPTS_DIR, release.DIST_DIR)
    release.REPO_ROOT = repo_root
    release.SCRIPTS_DIR = repo_root / "scripts"
    release.DIST_DIR = dist
    try:
        return release._package_os(os_name)
    finally:
        release.REPO_ROOT, release.SCRIPTS_DIR, release.DIST_DIR = saved


@pytest.fixture(scope="module")
def archives(tmp_path_factory):
    """Both archives, built from the real repository into a temporary dist."""
    dist = tmp_path_factory.mktemp("dist")
    return {name: build(REPO_ROOT, dist, name) for name in OS_NAMES}


def names(archive: Path) -> list[str]:
    with zipfile.ZipFile(archive) as zf:
        return zf.namelist()


def top_level(archive: Path) -> set[str]:
    return {name.split("/", 1)[0] for name in names(archive)}


def fake_repo(root: Path) -> Path:
    """A miniature repository carrying every kind of file that must not ship."""
    (root / "scripts" / "Universal" / "shared").mkdir(parents=True)
    (root / "scripts" / "requirements.txt").write_text("pydub==0.25.1\n", encoding="utf-8")
    (root / "scripts" / "Universal" / "launcher.py").write_text("x = 1\n", encoding="utf-8")
    (root / "scripts" / "Universal" / "shared" / "version.py").write_text(
        'VERSION = "9.9.9"\n', encoding="utf-8")
    (root / "README.md").write_text("readme\n", encoding="utf-8")
    (root / "config.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    (root / "config-template.toml").write_text("# unrelated maintainer file\n", encoding="utf-8")
    for launcher in LAUNCHERS.values():
        (root / launcher).write_text("launcher\n", encoding="utf-8")

    # Everything below is developer or runtime state and must stay behind.
    (root / "scripts" / "Universal" / "__pycache__").mkdir()
    (root / "scripts" / "Universal" / "__pycache__" / "launcher.cpython-312.pyc").write_bytes(b"\x00")
    (root / "scripts" / "Universal" / "stale.pyc").write_bytes(b"\x00")
    (root / ".venv" / "Scripts").mkdir(parents=True)
    (root / ".venv" / "Scripts" / "python.exe").write_bytes(b"\x00")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (root / ".claude").mkdir()
    (root / ".claude" / "CLAUDE.md").write_text("agent\n", encoding="utf-8")
    (root / "dist").mkdir()
    (root / "dist" / "old.zip").write_bytes(b"PK")
    (root / "md-instructions").mkdir()
    (root / "md-instructions" / "Handoff.md").write_text("notes\n", encoding="utf-8")
    maintenance = root / "files" / "runtime-data" / "maintenance"
    maintenance.mkdir(parents=True)
    (maintenance / "cleanup-request.json").write_text("{}", encoding="utf-8")
    (maintenance / "cleanup-result.json").write_text("{}", encoding="utf-8")
    (root / "files" / "runtime-data" / "settings.json").write_text("{}", encoding="utf-8")
    (root / "files" / "runtime-data" / "logs").mkdir()
    (root / "files" / "runtime-data" / "logs" / "session.log").write_text("log\n", encoding="utf-8")
    (root / "files" / "runtime-data" / "models").mkdir()
    (root / "files" / "runtime-data" / "models" / "weights.bin").write_bytes(b"\x00")
    (root / "files" / "bin").mkdir()
    (root / "files" / "bin" / "ffmpeg.exe").write_bytes(b"\x00")
    (root / "files" / "tests").mkdir()
    (root / "files" / "tests" / "test_thing.py").write_text("def test_x(): pass\n", encoding="utf-8")
    (root / "files" / "UI-Prototype-Screenshots").mkdir()
    (root / "files" / "UI-Prototype-Screenshots" / "shot.png").write_bytes(b"\x89PNG")
    return root


# --------------------------------------------------------------------------- #
# config.toml — the Phase 8 packaging requirement
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_each_archive_carries_config_toml_at_its_root_exactly_once(archives, os_name):
    assert names(archives[os_name]).count("config.toml") == 1


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_the_packaged_config_is_byte_identical_to_the_committed_file(archives, os_name):
    """Packaged, never regenerated — comments and all."""
    committed = (REPO_ROOT / "config.toml").read_bytes()
    with zipfile.ZipFile(archives[os_name]) as zf:
        assert zf.read("config.toml") == committed
    assert hashlib.sha256(committed).hexdigest() == hashlib.sha256(
        (REPO_ROOT / "config.toml").read_bytes()).hexdigest()


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_the_untracked_template_beside_it_is_still_absent(archives, os_name):
    """The real repository genuinely has both files side by side right now."""
    import os

    entries = os.listdir(REPO_ROOT)
    assert "config.toml" in entries and "config-template.toml" in entries, (
        "this test is only meaningful while both files sit at the root")
    assert "config-template.toml" not in names(archives[os_name])


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_a_template_in_a_synthetic_root_is_excluded_by_scope(tmp_path, os_name):
    """Proved again where the fixture, not the repository, guarantees the file."""
    root = fake_repo(tmp_path / "repo")
    archive = build(root, tmp_path / "dist", os_name)
    members = names(archive)
    assert "config.toml" in members
    assert not any("config-template" in name for name in members)


def test_the_packager_never_names_the_template_at_all():
    """Excluded by explicit scope — not copied and then deleted.

    ``test_repository_contract`` already forbids the string anywhere under
    ``scripts/`` except the protected-path list; this states the packaging half
    of that contract in the place a future reader of ``release.py`` will look.
    """
    source = (UNIVERSAL / "shared" / "release.py").read_text(encoding="utf-8")
    assert "config-template" not in source
    assert "shutil" not in source and "copytree" not in source


def test_the_packaged_root_files_are_a_closed_named_set():
    """Root packaging is an enumerated list, not a directory walk."""
    tree = ast.parse((UNIVERSAL / "shared" / "release.py").read_text(encoding="utf-8"))
    function = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "_package_os")
    attributes = [n.attr for n in ast.walk(function) if isinstance(n, ast.Attribute)]
    assert "iterdir" not in attributes, "the repository root must never be walked"
    assert "walk" not in attributes
    assert attributes.count("rglob") == 1, "exactly one tree is walked: scripts/"


# --------------------------------------------------------------------------- #
# Archive shape
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_the_archive_root_holds_only_the_approved_entries(archives, os_name):
    assert top_level(archives[os_name]) == ROOT_MEMBERS | {LAUNCHERS[os_name], "scripts"}


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_each_archive_carries_only_its_own_launcher(archives, os_name):
    members = names(archives[os_name])
    other = LAUNCHERS["MacOS" if os_name == "Windows" else "Windows"]
    assert LAUNCHERS[os_name] in members
    assert other not in members


def test_the_macos_launcher_keeps_its_executable_mode(archives):
    """A user must never have to ``chmod +x`` a freshly extracted launcher."""
    with zipfile.ZipFile(archives["MacOS"]) as zf:
        info = zf.getinfo(LAUNCHERS["MacOS"])
    mode = info.external_attr >> 16
    assert mode & 0o111 == 0o111, oct(mode)
    assert mode & 0o777 == 0o755, oct(mode)


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_the_scripts_tree_is_complete(archives, os_name):
    """Every source file the application needs, and no compiled leftovers."""
    expected = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "scripts").rglob("*")
        if path.is_file()
        and not {".venv", "__pycache__", ".pytest_cache"} & set(path.relative_to(REPO_ROOT).parts)
        and path.suffix not in {".pyc", ".pyo", ".pyd"}
    }
    packaged = {name for name in names(archives[os_name]) if name.startswith("scripts/")}
    assert packaged == expected
    assert "scripts/requirements.txt" in packaged
    assert "scripts/Universal/launcher.py" in packaged
    assert "scripts/verify.py" in packaged


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_the_version_in_the_archive_name_comes_from_version_py(archives, os_name):
    from shared.version import VERSION

    assert archives[os_name].name == f"AudiobookTool-{os_name}-v{VERSION}.zip"


# --------------------------------------------------------------------------- #
# Nothing developer-side or runtime-side leaks
# --------------------------------------------------------------------------- #


LEAKY_PREFIXES = (
    ".venv/", ".git/", ".github/", ".claude/", ".codex/", "files/", "md-instructions/",
    "dist/", "test-logs/", "scripts/__pycache__/",
)
LEAKY_FRAGMENTS = (
    "__pycache__", ".pytest_cache", "settings.json", "cleanup-request", "cleanup-result",
    "cleanup-coordinator", "maintenance/", "UI-Prototype-Screenshots", "session.log",
    ".pyc", ".pyo", ".pyd", ".DS_Store", "Thumbs.db",
)


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_no_developer_or_runtime_state_leaks(archives, os_name):
    for member in names(archives[os_name]):
        assert not member.startswith(LEAKY_PREFIXES), member
        for fragment in LEAKY_FRAGMENTS:
            assert fragment not in member, member


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_a_repository_full_of_state_still_ships_nothing_extra(tmp_path, os_name):
    """The synthetic root plants every forbidden artifact; none may appear."""
    root = fake_repo(tmp_path / "repo")
    members = names(build(root, tmp_path / "dist", os_name))
    for member in members:
        assert not member.startswith(LEAKY_PREFIXES), member
        for fragment in LEAKY_FRAGMENTS:
            assert fragment not in member, member
    assert members  # and it did package something


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_maintenance_state_can_never_be_packaged(archives, os_name):
    """Cleanup state lives under ``files/runtime-data/``, which is out of scope."""
    from shared import cleanup_state

    assert cleanup_state.STATE_DIR_PARTS[0] == "files"
    members = names(archives[os_name])
    assert not any(member.startswith("files/") for member in members)
    for filename in cleanup_state.STATE_FILENAMES:
        assert not any(member.endswith(filename) for member in members), filename


# --------------------------------------------------------------------------- #
# Extraction safety
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_no_member_is_absolute_traversing_or_duplicated(archives, os_name):
    members = names(archives[os_name])
    assert len(members) == len(set(members)), "duplicate member"
    for member in members:
        assert not member.startswith("/"), member
        assert "\\" not in member, member
        assert ":" not in member, member
        assert ".." not in Path(member).parts, member
        assert not Path(member).is_absolute(), member


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_every_member_extracts_inside_the_extraction_root(tmp_path, archives, os_name):
    target = tmp_path / "extract"
    target.mkdir()
    root = target.resolve()
    with zipfile.ZipFile(archives[os_name]) as zf:
        for info in zf.infolist():
            assert not info.is_dir()
            destination = (root / info.filename).resolve()
            assert destination == root or root in destination.parents, info.filename
        zf.extractall(target)
    assert (target / "config.toml").read_bytes() == (REPO_ROOT / "config.toml").read_bytes()
    assert (target / "scripts" / "Universal" / "launcher.py").is_file()


# --------------------------------------------------------------------------- #
# Determinism and the dev-only boundary
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_two_builds_produce_the_same_manifest(tmp_path, os_name):
    """Names, order, sizes and CRCs are stable; only zip metadata may differ."""
    def manifest(dist_name):
        archive = build(REPO_ROOT, tmp_path / dist_name, os_name)
        with zipfile.ZipFile(archive) as zf:
            return [(i.filename, i.file_size, i.CRC) for i in zf.infolist()]

    assert manifest("one") == manifest("two")


def test_the_packager_is_never_imported_by_the_application():
    """Nothing the launcher can reach may pull in the build helper."""
    offenders = []
    for path in UNIVERSAL.rglob("*.py"):
        if path.name == "release.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.split(".")[-1] == "release" for alias in node.names):
                    offenders.append(path)
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".")[-1] == "release":
                    offenders.append(path)
                elif any(alias.name == "release" for alias in node.names):
                    offenders.append(path)
    assert offenders == []


def test_the_packager_imports_nothing_from_the_application():
    """It depends only on the stdlib plus the version constant."""
    tree = ast.parse((UNIVERSAL / "shared" / "release.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "sys", "zipfile", "pathlib", "version"}


def test_building_is_not_part_of_application_startup():
    """The launcher never builds, and the packager only runs as ``__main__``."""
    launcher = (UNIVERSAL / "launcher.py").read_text(encoding="utf-8")
    assert "release" not in launcher and "zipfile" not in launcher
    source = (UNIVERSAL / "shared" / "release.py").read_text(encoding="utf-8")
    assert source.rstrip().endswith("raise SystemExit(main())")
    assert '__name__ == "__main__"' in source
