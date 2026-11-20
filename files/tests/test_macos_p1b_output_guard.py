"""v0.8.x P1B, after MAC-032 -- a test's run publishes only into its own folder, never the real default output folder.

Under the focused gate one pytest process runs many test files, and ``shared.config`` caches one configuration snapshot
for the process. MAC-032 set its own output base through ``shared.settings`` after an earlier test had cached the
snapshot, so its real MP3 Combine resolved the stale default and published into the real
``~/Downloads/Audiobook-Creation-Tool-Outputs``. ``output_guard`` is the fail-closed answer for any test that runs a real
tool, and these are its negative controls: a stale cached snapshot, a different configuration, two tests sharing one
process (where the write boundary still holds if the check is skipped), and an expected folder that is itself a real
location are each refused before anything is created. The positive controls show the guard is not simply refusing
everything, so a pass of MAC-032 still means something.

Everything but the real-location group runs against an injected home (``shared.paths.downloads_dir`` patched to a fake
``Downloads`` in ``tmp_path``) and the test's own settings file, so the real Downloads folder is never a target. The
real-location group computes the real default from the real home only to refuse it, and looks at it with
``os.path.lexists`` and nothing else. Around every test, writes into the real Downloads and default output folders and
into the production roots (``conftest.PRODUCTION_WRITE_ROOTS``) are refused before they happen, ``files/runtime-data``
is compared before and after, and the process's configuration cache is dropped, so no later test in the process
inherits a snapshot built here. Platform-neutral: it runs on Windows as well.
"""

from __future__ import annotations

import ast
import os
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

import output_guard
import write_tripwire
from output_guard import UnsafeOutputBase, real_output_locations_refused, require_isolated_output_base
from shared import config, output_paths, paths
from shared import settings as app_settings

pytestmark = pytest.mark.usefixtures("production_writes_refused")

RUNTIME_DATA = paths.REPO_ROOT / "files" / "runtime-data"
MAINTHREAD_TEST = Path(__file__).resolve().parent / "test_macos_p1b_mainthread.py"

#: Taken at import, from the real home, before any test here injects a fake one. Computed, never created.
REAL_DEFAULT = output_guard.real_default_output_base()
REAL_DOWNLOADS = output_guard.real_downloads_dir()


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _real_downloads_refused():
    """Belt and braces for this file itself: whatever a test here gets wrong, nothing it runs can write into the real
    Downloads folder or the real default output folder (refused before the write, and the test fails)."""
    with write_tripwire.armed((REAL_DEFAULT, REAL_DOWNLOADS)) as attempts:
        yield
    if attempts:
        pytest.fail("this test attempted to write the real Downloads or default output folder (refused before "
                    "anything changed): " + "; ".join(f"{event} {path}" for event, path in attempts[:5]))


def _runtime_data_listing() -> dict:
    """The top level of the repository's ``files/runtime-data``: each name with its kind, size and mtime. One scandir,
    never a walk -- ``models`` is large, and ``settings.json``, ``logs/`` and ``ffmpeg-state.json`` sit at the top."""
    listing = {}
    try:
        with os.scandir(RUNTIME_DATA) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                listing[entry.name] = (entry.is_dir(follow_symlinks=False), info.st_size, info.st_mtime_ns)
    except FileNotFoundError:
        return {}
    return listing


@pytest.fixture(autouse=True)
def _runtime_data_untouched():
    """The repository's real ``files/runtime-data`` is the same after the test as before it."""
    before = _runtime_data_listing()
    yield
    after = _runtime_data_listing()
    if after != before:
        changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
        pytest.fail(f"this test changed the repository's real files/runtime-data: {changed}")


@pytest.fixture(autouse=True)
def _no_snapshot_survives():
    """Start with no cached snapshot and leave none behind: one built here (from a fake home, or stale on purpose) must
    never become the next test's configuration."""
    config.invalidate()
    yield
    config.invalidate()


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """A stand-in home whose Downloads folder the app's default output base resolves into, for this test only."""
    home = tmp_path / "fake-home"
    downloads = home / "Downloads"
    downloads.mkdir(parents=True)
    monkeypatch.setattr(paths, "downloads_dir", lambda: downloads)
    default = downloads / config.OUTPUT_BASE_FOLDER_NAME
    assert config.default_output_base() == default == output_guard.real_default_output_base()
    assert output_guard.real_downloads_dir() == downloads
    assert not os.path.lexists(default)
    return SimpleNamespace(home=home, downloads=downloads, default=default)


@pytest.fixture
def own_settings(tmp_path):
    """This test's own settings file, so an output base set here never reaches the session's settings (or the next
    test). The previous location is put back exactly, with the settings cache dropped."""
    previous = app_settings._path_override
    app_settings.use_path(tmp_path / "settings" / "settings.json")
    try:
        yield app_settings
    finally:
        app_settings.use_path(previous)


def _snapshot(home: Path, base: Path | None):
    """A snapshot as a run captures one: the committed ``config.toml`` (read only) and these settings."""
    settings = {"output_base_directory": str(base)} if base is not None else {}
    return config.load(settings_data=settings, home=home)


def _created(*folders: Path) -> list[Path]:
    return [folder for folder in folders if os.path.lexists(folder)]


# --------------------------------------------------------------------------- #
#  The check before a run: require_isolated_output_base
# --------------------------------------------------------------------------- #
def test_a_stale_cached_snapshot_is_refused_and_left_as_found(fake_home, own_settings, tmp_path):
    """A snapshot cached while the base was A; the settings then say B, with no invalidation. The run would still go to
    A, so B must be refused -- and the guard must not refresh the cache to make B true, which would hide the fault from
    the test while the run could still resolve A. Nothing is created at A or B. Invalidating, the remedy the refusal
    names, then passes: the guard refuses the stale snapshot, not the folder."""
    first, second = tmp_path / "A-Outputs", tmp_path / "B-Outputs"
    assert own_settings.set("output_base_directory", str(first))
    assert config.get_effective().output.base_directory == first  # cached with A

    assert own_settings.set("output_base_directory", str(second))  # and no config.invalidate()
    with pytest.raises(UnsafeOutputBase) as refused:
        require_isolated_output_base(second)

    message = str(refused.value)
    assert f"publish into {first}" in message and "config.invalidate()" in message, message
    assert config.get_effective().output.base_directory == first, "the guard refreshed the stale snapshot"
    assert _created(first, second) == []

    config.invalidate()
    assert require_isolated_output_base(second) == second
    assert _created(first, second) == []


@pytest.mark.parametrize("named_by", ["the settings", "the run's own snapshot"])
def test_a_configuration_naming_another_base_is_refused(named_by, fake_home, own_settings, tmp_path):
    """The run's configuration names a folder that is not the test's: through the settings (fresh, not stale), or
    through the snapshot the run captured while the process's own snapshot names the test's folder. Checking the
    process snapshot instead of the one the run uses would pass the second; it must be refused too."""
    mine, other = tmp_path / "Mine", tmp_path / "Other"
    if named_by == "the settings":
        assert own_settings.set("output_base_directory", str(other))
        effective = None
    else:
        assert own_settings.set("output_base_directory", str(mine))
        assert output_paths.resolve_output_base() == mine
        effective = _snapshot(fake_home.home, other)

    with pytest.raises(UnsafeOutputBase, match="not this test's own folder") as refused:
        require_isolated_output_base(mine, effective=effective)

    assert f"publish into {other}" in str(refused.value)
    assert "config.invalidate()" not in str(refused.value), "a fresh configuration is not a stale cache"
    assert _created(mine, other) == []


def test_only_the_tests_own_folder_passes_and_nothing_is_created(fake_home, own_settings, tmp_path):
    """Positive controls, so a pass means something: the base set and the cache dropped; and a captured snapshot naming
    the test's folder while the process names another (the snapshot a run uses is the one checked)."""
    mine, other = tmp_path / "Mine", tmp_path / "Other"
    assert own_settings.set("output_base_directory", str(mine))
    assert require_isolated_output_base(mine) == mine

    assert own_settings.set("output_base_directory", str(other))
    config.invalidate()
    assert require_isolated_output_base(mine, effective=_snapshot(fake_home.home, mine)) == mine
    assert _created(mine, other, fake_home.default) == []


def test_two_tests_sharing_a_process_cannot_send_a_run_into_the_default_folder(fake_home, own_settings, tmp_path):
    """MAC-032 as it happened, with the fake home's Downloads standing in for the real one. The earlier test runs on the
    defaults and caches the snapshot; the later one sets its own folder and forgets to invalidate. The check refuses,
    naming the default folder. Had the later test gone ahead anyway, the tools' own run reservation is refused at the
    write (``PermissionError``), and the block still fails though the reservation's caller caught the error, as the MP3
    Tool does -- and the default folder never comes into existence."""
    earlier = config.get_effective()
    assert earlier.output.is_default and output_paths.resolve_output_base() == fake_home.default

    mine = tmp_path / "Outputs"
    mine.mkdir()
    assert own_settings.set("output_base_directory", str(mine))
    with pytest.raises(UnsafeOutputBase) as refused:
        require_isolated_output_base(mine)
    assert f"the resolved output base {fake_home.default} is inside the real default output folder" \
        in str(refused.value), str(refused.value)

    with pytest.raises(UnsafeOutputBase, match="was attempted") as blocked:
        with real_output_locations_refused() as roots:
            assert fake_home.default in roots and fake_home.downloads in roots
            with pytest.raises(output_paths.OutputBaseError) as reservation:
                output_paths.reserve_run_directory("mp3_tool")
            assert isinstance(reservation.value.__cause__, PermissionError)
            assert "write tripwire" in str(reservation.value.__cause__)
    assert f"os.mkdir {fake_home.default}" in str(blocked.value), str(blocked.value)
    assert _created(fake_home.default) == []
    assert list(fake_home.downloads.iterdir()) == [] and list(mine.iterdir()) == []


@pytest.mark.parametrize("how", ["raised out of the block", "caught on a worker thread"])
def test_a_write_into_the_default_folder_fails_the_block_however_it_ends(how, fake_home, own_settings):
    """The block fails on the attempt itself, not on what the code under test made of it: the refusal raised out of the
    block (the cause is kept), or swallowed on another thread, where a tool's worker publishes."""
    target = fake_home.default / "MP3-Tool-Outputs" / "MP3-Tool-1"
    swallowed: list[BaseException] = []

    def publish():
        try:
            target.mkdir(parents=True)
        except OSError as exc:
            swallowed.append(exc)

    with pytest.raises(UnsafeOutputBase, match="was attempted") as blocked:
        with real_output_locations_refused():
            if how == "raised out of the block":
                output_paths.ensure_output_base(fake_home.default)
            else:
                worker = threading.Thread(target=publish, name="output-guard-worker")
                worker.start()
                worker.join(30)
                assert not worker.is_alive()
    if how == "raised out of the block":
        assert isinstance(blocked.value.__cause__, output_paths.OutputBaseError)
        assert isinstance(blocked.value.__cause__.__cause__, PermissionError)
    else:
        assert len(swallowed) == 1 and isinstance(swallowed[0], PermissionError)
    assert _created(fake_home.default) == []


def test_the_refusal_leaves_the_tests_own_folder_writable(fake_home, own_settings, tmp_path):
    """Positive control for the write boundary: a run reserved in the test's own folder succeeds inside the block, which
    ends quietly. A boundary that refused the test's own tree would fail every real-tool test for the wrong reason."""
    mine = tmp_path / "Outputs"
    assert own_settings.set("output_base_directory", str(mine))
    assert require_isolated_output_base(mine) == mine
    with real_output_locations_refused():
        reservation = output_paths.reserve_run_directory("mp3_tool")
    assert reservation.run_directory == mine / "MP3-Tool-Outputs" / "MP3-Tool-1"
    assert reservation.run_directory.is_dir()
    assert _created(fake_home.default) == []


# --------------------------------------------------------------------------- #
#  The real locations, from the real home: refused, and only looked at
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("where", [
    "the real default output folder itself",
    "a folder inside the real default output folder",
    "a folder inside the real Downloads folder",
    "a folder inside the repository's files/runtime-data",
])
def test_an_expected_folder_in_a_real_location_is_refused_before_anything_exists(where):
    """A test that names a real location as its own folder (here the snapshot agrees with it, so the location is the
    only fault) is refused, and nothing is created: the real default output folder, the Downloads folder and the
    expected folder exist afterwards exactly as before, ``files/runtime-data`` lists the same, and the write boundary
    over those places, armed throughout, saw no attempt. Existence is all this test reads of them."""
    real_default = output_guard.real_default_output_base()
    downloads = output_guard.real_downloads_dir()
    assert (real_default, downloads) == (REAL_DEFAULT, REAL_DOWNLOADS), "this test must see the real home"
    probe = f"act-output-guard-probe-{uuid.uuid4().hex}"  # a name nothing has
    expected, label = {
        "the real default output folder itself": (real_default, "the real default output folder"),
        "a folder inside the real default output folder": (real_default / probe, "the real default output folder"),
        "a folder inside the real Downloads folder": (downloads / probe, "the real Downloads folder"),
        "a folder inside the repository's files/runtime-data": (RUNTIME_DATA / probe,
                                                                 "the repository's files/runtime-data"),
    }[where]
    snapshot = config.load(settings_data={"output_base_directory": str(expected)})
    assert output_paths.resolve_output_base(snapshot) == expected

    watched = (real_default, downloads, expected)
    existed = [os.path.lexists(folder) for folder in watched]
    listing = _runtime_data_listing()
    with real_output_locations_refused(extra=(RUNTIME_DATA,)):
        with pytest.raises(UnsafeOutputBase) as refused:
            require_isolated_output_base(expected, effective=snapshot)
    assert f"this test's folder {expected} is inside {label}" in str(refused.value), str(refused.value)
    assert [os.path.lexists(folder) for folder in watched] == existed
    assert _runtime_data_listing() == listing


# --------------------------------------------------------------------------- #
#  MAC-032 keeps using it
# --------------------------------------------------------------------------- #
def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def test_mac_032_checks_its_folder_after_invalidating_and_runs_inside_the_refusal():
    """The guard protects MAC-032 only while MAC-032 uses it: the check on its own ``outputs`` folder after the cached
    snapshot is dropped and before the Combine, and the Combine itself inside the write refusal."""
    tree = ast.parse(MAINTHREAD_TEST.read_text(encoding="utf-8"))
    test = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test_a_real_combine"))
    calls = [(node.lineno, _dotted(node.func), node) for node in ast.walk(test) if isinstance(node, ast.Call)]
    invalidated = [line for line, name, _ in calls if name == "config.invalidate"]
    checked = [(line, node) for line, name, node in calls if name == "require_isolated_output_base"]
    combined = [line for line, name, _ in calls if name.endswith("btn_combine.invoke")]
    assert invalidated and checked and len(combined) == 1
    (check_line, check), = checked
    assert [_dotted(arg) for arg in check.args] == ["outputs"] and not check.keywords
    assert min(invalidated) < check_line < combined[0]

    refusing = [node for node in ast.walk(test) if isinstance(node, ast.With)
                and any(isinstance(item.context_expr, ast.Call)
                        and _dotted(item.context_expr.func) == "real_output_locations_refused" for item in node.items)]
    assert any(check_line < block.lineno < combined[0] <= block.end_lineno for block in refusing)
