"""The release-archive contract: what ships, what must never ship.

``shared/release.py`` is a developer-only build helper. It packages by *explicit
scope* — it names the handful of root files it wants and walks exactly one tree —
rather than copying the repository and deleting the parts that must not ship. That
distinction is the whole safety argument: a file the packager never names cannot
leak because someone forgot to add it to an exclusion list.

``config-template.toml`` is the file that argument was built around. It used to
sit untracked directly beside the real ``config.toml``; the maintainer removed it
on 2026-08-08 and the v0.6.0 Drop 3 contract keeps the repository root free of it.
The proof therefore moved rather than weakened: the *synthetic* fixture below
deliberately creates one, so the packager is still exercised against a template it
must refuse, and the real-repository test asserts the root stays clean.

Every archive here is built into a pytest temporary directory. Nothing in this
suite writes to ``dist/``, and nothing extracts outside ``tmp_path``.
"""

from __future__ import annotations

import ast
import hashlib
import os
import subprocess
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
    # (.git/ itself is created for real by commit_everything below.)
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
    # Folder-metadata artifacts a real OS drops just from browsing a folder in
    # Finder/Explorer -- gitignored, so a real dev checkout is never
    # guaranteed to be free of them at packaging time (v0.6.5 Phase 8: a real
    # Mac checkout that had simply been opened in Finder shipped
    # scripts/.DS_Store before this was caught).
    (root / "scripts" / "Universal" / ".DS_Store").write_bytes(b"\x00")
    (root / "scripts" / "Universal" / "Thumbs.db").write_bytes(b"\x00")
    # Everything above is committed -- forced past any ignore rule -- so the
    # name/suffix exclusions are proved on tracked junk too, not only on files
    # the tracked-only rule would already have dropped.
    commit_everything(root)
    return root


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=packager-test",
         "-c", "user.email=packager-test@example.invalid", "-c", "core.autocrlf=false",
         # A throwaway fixture repository, never the project's: a global signing
         # setting must not make the fixture commit fail on some machines.
         "-c", "commit.gpgsign=false",
         *args],
        capture_output=True, text=True, check=True)
    return result.stdout


def commit_everything(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "add", "-A", "-f")
    git(root, "commit", "-q", "-m", "fixture")


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
    """The real root carries ``config.toml`` and no template, and neither ships.

    The precondition changed with the repository, not with the requirement. Until
    2026-08-08 the maintainer's untracked ``config-template.toml`` sat beside
    ``config.toml`` and this test asserted that coexistence; the file has since
    been removed by instruction and must stay absent, so the precondition now
    asserts the current contract. The substantive assertion underneath is
    untouched: whatever the root holds, no archive may contain a template.

    ``os.listdir`` is used rather than ``Path.exists`` on purpose — a path lookup
    on NTFS and APFS is case-insensitive and would happily confirm a name that is
    not actually there.
    """
    entries = os.listdir(REPO_ROOT)
    assert "config.toml" in entries, (
        "the committed root config.toml must exist for this suite to mean anything")
    assert "config-template.toml" not in entries, (
        "the root config-template.toml must remain absent (v0.6.0 Drop 3 contract); "
        "it must never be recreated, staged, packaged or loaded")
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
    # The high bits describe a Unix mode only when the archive declares Unix
    # as the originating system, including archives built on Windows.
    assert info.create_system == 3


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_the_scripts_tree_is_complete(archives, os_name):
    """Every source file the application needs, and no compiled leftovers.

    Mirrors ``release._is_excluded`` by importing its own exclusion sets
    rather than hand-copying them -- a hand-copied literal here is exactly
    how this test went stale of a real exclusion (v0.6.5 Phase 8: a real Mac
    checkout's stray ``.DS_Store`` was excluded from packaging by
    ``release.py`` before this test's own copy of the exclusion rule knew
    about it).
    """
    tracked = set(git(REPO_ROOT, "ls-files", "--", "scripts").splitlines())
    expected = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "scripts").rglob("*")
        if path.is_file()
        and path.relative_to(REPO_ROOT).as_posix() in tracked
        and not release.EXCLUDED_DIR_NAMES & set(path.relative_to(REPO_ROOT).parts)
        and path.suffix not in release.EXCLUDED_SUFFIXES
        and path.name not in release.EXCLUDED_FILE_NAMES
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
def test_an_untracked_file_under_scripts_never_ships(tmp_path, os_name):
    """Only committed content ships (v0.6.6 Phase 11).

    Walking ``scripts/`` on disk used to package whatever happened to be there:
    the maintainer's local-only, never-committed ``scripts/project-status.py``
    landed in both archives. Uncommitted work -- notes, helpers, a stray ``.env``
    -- is not part of the product, whatever its name.
    """
    root = fake_repo(tmp_path / "repo")
    (root / "scripts" / "local-helper.py").write_text("x = 2\n", encoding="utf-8")
    (root / "scripts" / "Universal" / ".env").write_text("TOKEN=not-real\n", encoding="utf-8")
    members = names(build(root, tmp_path / "dist", os_name))
    assert "scripts/local-helper.py" not in members
    assert "scripts/Universal/.env" not in members
    assert "scripts/Universal/launcher.py" in members


def test_the_real_archives_carry_no_untracked_file(archives):
    tracked = set(git(REPO_ROOT, "ls-files", "--", "scripts").splitlines())
    for archive in archives.values():
        untracked = [m for m in names(archive) if m.startswith("scripts/") and m not in tracked]
        assert untracked == []


def test_packaging_outside_a_git_checkout_is_refused(tmp_path):
    """Fail closed: without git there is no way to tell committed from local."""
    root = tmp_path / "plain"
    (root / "scripts" / "Universal").mkdir(parents=True)
    (root / "scripts" / "Universal" / "launcher.py").write_text("x = 1\n", encoding="utf-8")
    for name in (*ROOT_MEMBERS, *LAUNCHERS.values()):
        (root / name).write_text("x\n", encoding="utf-8")
    with pytest.raises(release.ReleaseError):
        build(root, tmp_path / "dist", "Windows")
    assert not (tmp_path / "dist").exists() or not any((tmp_path / "dist").iterdir())


def run_main(root: Path, dist: Path) -> int:
    saved = (release.REPO_ROOT, release.SCRIPTS_DIR, release.DIST_DIR)
    release.REPO_ROOT, release.SCRIPTS_DIR, release.DIST_DIR = root, root / "scripts", dist
    try:
        return release.main()
    finally:
        release.REPO_ROOT, release.SCRIPTS_DIR, release.DIST_DIR = saved


@pytest.mark.parametrize("edited", [
    "scripts/Universal/launcher.py", "README.md", "config.toml",
    "Setup_and_Run-audiobook-creation-tool.bat",
    "Setup_and_Run-audiobook-creation-tool.command",
])
def test_the_release_build_refuses_uncommitted_changes(tmp_path, edited):
    """A release archive is the committed state, never a dirty working tree."""
    root = fake_repo(tmp_path / "repo")
    (root / edited).write_text("edited, not committed\n", encoding="utf-8")
    assert run_main(root, tmp_path / "dist") != 0
    assert not (tmp_path / "dist").exists() or not any((tmp_path / "dist").iterdir())


def test_a_staged_but_uncommitted_change_is_refused_too(tmp_path):
    root = fake_repo(tmp_path / "repo")
    (root / "scripts" / "Universal" / "launcher.py").write_text("x = 3\n", encoding="utf-8")
    git(root, "add", "scripts/Universal/launcher.py")
    assert run_main(root, tmp_path / "dist") != 0


def test_a_clean_checkout_builds_both_archives(tmp_path):
    root = fake_repo(tmp_path / "repo")
    (root / "scripts" / "local-helper.py").write_text("x = 2\n", encoding="utf-8")
    assert run_main(root, tmp_path / "dist") == 0
    built = sorted(p.name for p in (tmp_path / "dist").iterdir())
    # The name carries the packager's own VERSION, read once at import.
    assert built == [f"AudiobookTool-MacOS-v{release.VERSION}.zip",
                     f"AudiobookTool-Windows-v{release.VERSION}.zip"]
    assert "scripts/local-helper.py" not in names(tmp_path / "dist" / built[0])


# --------------------------------------------------------------------------- #
# The launchers, byte for byte
# --------------------------------------------------------------------------- #


def test_the_windows_launcher_ships_with_crlf_line_endings(archives):
    """cmd.exe misparses labels and blocks in an LF-only batch file."""
    with zipfile.ZipFile(archives["Windows"]) as zf:
        data = zf.read(LAUNCHERS["Windows"])
    assert data.count(b"\n") > 0
    assert data.count(b"\n") == data.count(b"\r\n")


def test_the_macos_launcher_ships_lf_only_with_its_shebang(archives):
    """A stray CR breaks bash with 'bad interpreter' / 'command not found'."""
    with zipfile.ZipFile(archives["MacOS"]) as zf:
        data = zf.read(LAUNCHERS["MacOS"])
    assert data.startswith(b"#!/bin/bash\n")
    assert b"\r" not in data


def test_the_macos_launcher_is_committed_executable():
    """A developer clone on a Mac double-clicks the committed file, not the zip."""
    stage = git(REPO_ROOT, "ls-files", "-s", "--", LAUNCHERS["MacOS"]).split()
    assert stage[0] == "100755", stage


def test_the_packaged_macos_launcher_parses_as_bash(tmp_path, archives):
    """``bash -n`` over the exact bytes a Mac user extracts (no execution)."""
    import shutil

    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on this machine")
    with zipfile.ZipFile(archives["MacOS"]) as zf:
        extracted = Path(zf.extract(LAUNCHERS["MacOS"], tmp_path))
    result = subprocess.run([bash, "-n", extracted.as_posix()], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_translocation_help_names_the_folder_the_archive_extracts_to():
    """Finder extracts ``AudiobookTool-MacOS-vX.Y.Z.zip`` into a folder of that name."""
    text = (REPO_ROOT / LAUNCHERS["MacOS"]).read_text(encoding="utf-8")
    assert '"AudiobookTool-MacOS-v..."' in text
    assert '"audiobook-creation-tool" folder' not in text


@pytest.mark.parametrize("launch_rc,expected_rc,repairs", [(3, 0, True), (1, 1, False)])
def test_packaged_macos_launcher_routes_bootstrap_exit_code(
    tmp_path, archives, launch_rc, expected_rc, repairs
):
    """Execute the packaged shell; only bootstrap's rebuild code enters repair.

    Interpreter shims prevent installs or GUI launches. This exercises real Bash
    control flow, including the status of a failed command inside an ``if``.
    """
    import shutil

    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on this machine")
    root = tmp_path / "app folder"
    with zipfile.ZipFile(archives["MacOS"]) as zf:
        zf.extractall(root)
    shim = (
        '#!/bin/bash\n'
        'printf "%s\\n" "$*" >> "$RC_CALLS"\n'
        'case "$*" in\n'
        '  *--launch-only*) exit "$RC_LAUNCH_EXIT" ;;\n'
        '  --version) echo "Python 3.12 shim" ;;\n'
        'esac\n'
        'exit 0\n'
    )
    for relative in (".venv/bin/python", "shim-bin/python3.12"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(shim, encoding="utf-8", newline="\n")
        path.chmod(0o755)
    calls = root / "calls.txt"
    env = dict(os.environ, RC_CALLS=calls.as_posix(), RC_LAUNCH_EXIT=str(launch_rc))
    # Use MSYS paths on Windows so a drive colon is not a PATH separator.
    def shell_path(path):
        value = Path(path).as_posix()
        if os.name == "nt":
            return "/" + value[0].lower() + value[2:]
        return value

    env["PATH"] = shell_path(root / "shim-bin") + ":" + shell_path(Path(bash).parent) + ":/usr/bin:/bin"
    result = subprocess.run(
        [bash, (root / LAUNCHERS["MacOS"]).as_posix()],
        input="x\n", capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == expected_rc, result.stdout + result.stderr
    recorded = calls.read_text(encoding="utf-8").splitlines()
    assert recorded[0].endswith("--launch-only")
    assert any("--repair-venv" in call for call in recorded) is repairs
    assert not any("close_terminal.py" in call for call in recorded)


def test_the_launcher_line_endings_are_pinned_by_gitattributes():
    rules = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "*.command text eol=lf" in rules
    assert "*.bat text eol=crlf" in rules


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
    # subprocess is for git alone: v0.6.6 Phase 11 packages only committed files.
    assert imported <= {"__future__", "subprocess", "sys", "zipfile", "pathlib", "version"}


def test_building_is_not_part_of_application_startup():
    """The launcher never builds, and the packager only runs as ``__main__``."""
    launcher = (UNIVERSAL / "launcher.py").read_text(encoding="utf-8")
    assert "release" not in launcher and "zipfile" not in launcher
    source = (UNIVERSAL / "shared" / "release.py").read_text(encoding="utf-8")
    assert source.rstrip().endswith("raise SystemExit(main())")
    assert '__name__ == "__main__"' in source
