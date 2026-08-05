"""v0.6.0 Drop 2 Phase 6 — the downloaded-data catalog, inventory and schemas.

Every filesystem assertion here runs against a disposable fake repository root
built in ``tmp_path``. Nothing in this file reads, walks, hashes, measures or
touches the maintainer's real ``.venv``, ``files/bin``,
``files/runtime-data/models``, ``files/runtime-data/logs``, ``settings.json``,
Downloads folder, output base, source media, source, docs, tests, ``config.toml``
or ``config-template.toml`` — a test at the end proves the real root is never
passed to :func:`inventory`, and the fake-root tests hash their fixtures before
and after to prove nothing was modified.

Phase 6 deletes nothing. The structural guards below assert that: no destructive
primitive, no process spawning, no persistence and no coordinator exists in the
maintenance implementation.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import uuid
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared import maintenance as mnt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MODULE = Path(mnt.__file__)

UTC = timezone.utc
FIXED_TIME = datetime(2026, 8, 4, 9, 30, tzinfo=UTC)
FIXED_UUID = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"


# --------------------------------------------------------------------------- #
# Fake repository roots
# --------------------------------------------------------------------------- #


def write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def fake_root(tmp_path: Path, *, venv=True, binaries=True, models=True, logs=True) -> Path:
    """A disposable stand-in for the repository root, with known byte totals."""
    root = tmp_path / "fake-repo"
    (root / "scripts" / "Universal" / "shared").mkdir(parents=True, exist_ok=True)
    (root / "md-instructions").mkdir(parents=True, exist_ok=True)
    (root / "files" / "tests").mkdir(parents=True, exist_ok=True)
    (root / "files" / "runtime-data").mkdir(parents=True, exist_ok=True)
    write(root / "config.toml", b"# fake\n")
    write(root / "files" / "runtime-data" / "settings.json", b"{}")

    if venv:
        write(root / ".venv" / "pyvenv.cfg", b"x" * 100)
        write(root / ".venv" / "Lib" / "site-packages" / "thing.py", b"y" * 400)
    if binaries:
        write(root / "files" / "bin" / "ffmpeg.exe", b"z" * 1000)
    if models:
        write(root / "files" / "runtime-data" / "models" / "kokoro" / "model.bin", b"m" * 2048)
    if logs:
        write(root / "files" / "runtime-data" / "logs" / "session.log", b"l" * 50)
    return root


VENV_BYTES = 500
BIN_BYTES = 1000
MODEL_BYTES = 2048
LOG_BYTES = 50


def snapshot(root: Path) -> dict[str, str]:
    """Path -> sha256 for every file under *root*, for before/after proof."""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            out[str(path.relative_to(root)).replace("\\", "/")] = digest
    return out


def make_junction(link: Path, target: Path) -> bool:
    """A Windows junction (no elevation) or a POSIX symlink. False if refused."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True,
        )
        return result.returncode == 0
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        return False


def items_by_id(items):
    return {item.asset_id: item for item in items}


# --------------------------------------------------------------------------- #
# The catalog
# --------------------------------------------------------------------------- #


def test_the_catalog_holds_exactly_four_ids_in_a_fixed_order():
    assert mnt.ASSET_IDS == (
        "virtual_environment", "portable_binaries", "downloaded_models", "application_logs",
    )
    assert len(mnt.CATALOG) == 4
    assert tuple(d.asset_id for d in mnt.CATALOG) == mnt.ASSET_IDS


def test_every_catalog_entry_carries_its_approved_display_name():
    names = {d.asset_id: d.display_name for d in mnt.CATALOG}
    assert names == {
        "virtual_environment": "Private Python environment",
        "portable_binaries": "Portable binaries",
        "downloaded_models": "Downloaded voice models",
        "application_logs": "Application logs",
    }


def test_the_catalog_relative_targets_are_the_approved_four():
    targets = {d.asset_id: d.relative_target for d in mnt.CATALOG}
    assert targets == {
        "virtual_environment": ".venv",
        "portable_binaries": "files/bin",
        "downloaded_models": "files/runtime-data/models",
        "application_logs": "files/runtime-data/logs",
    }


def test_post_exit_handling_is_recorded_for_venv_and_logs():
    by_id = {d.asset_id: d for d in mnt.CATALOG}
    assert by_id["virtual_environment"].requires_post_exit is True
    assert by_id["application_logs"].requires_post_exit is True
    assert by_id["portable_binaries"].requires_post_exit is False


def test_only_the_venv_removes_its_own_directory():
    by_id = {d.asset_id: d for d in mnt.CATALOG}
    assert by_id["virtual_environment"].removes_target_itself is True
    for other in ("portable_binaries", "downloaded_models", "application_logs"):
        assert by_id[other].removes_target_itself is False


def test_the_catalog_and_its_entries_are_immutable():
    with pytest.raises(FrozenInstanceError):
        mnt.CATALOG[0].asset_id = "something_else"
    with pytest.raises(TypeError):
        mnt.CATALOG_BY_ID["extra"] = mnt.CATALOG[0]
    assert isinstance(mnt.CATALOG, tuple)


def test_the_catalog_never_names_settings_outputs_source_or_a_system_path():
    forbidden = (
        "settings", "config.toml", "config-template", "Downloads", "Outputs",
        "scripts", "md-instructions", "tests", "ffmpeg.exe", "/usr/", "C:\\",
        "Program Files", "System32", "homebrew", "site-packages",
    )
    for definition in mnt.CATALOG:
        for word in forbidden:
            assert word not in definition.relative_target, definition.asset_id


def test_system_ffmpeg_is_explicitly_excluded_in_the_binaries_wording():
    binaries = mnt.CATALOG_BY_ID["portable_binaries"]
    assert "System-installed ffmpeg is never removed." in binaries.consequence
    assert "System-installed ffmpeg will not be removed." in binaries.effect_line


# --------------------------------------------------------------------------- #
# ID validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", [
    "unknown_asset", "", " ", "virtual_environment ", "VIRTUAL_ENVIRONMENT",
    "../../etc/passwd", "..", ".", "/", "\\", "files/bin", ".venv",
    "C:/Windows/System32", "/usr/bin/ffmpeg", "settings.json", "config.toml",
    "virtual_environment/../..",
])
def test_unknown_malicious_and_pathlike_ids_are_refused(bad):
    with pytest.raises(mnt.UnknownAssetError):
        mnt.asset(bad)


@pytest.mark.parametrize("bad", [None, 1, 1.5, True, b"virtual_environment",
                                ["virtual_environment"], {"a": 1}, Path(".venv")])
def test_wrong_typed_ids_are_refused(bad):
    with pytest.raises(mnt.UnknownAssetError):
        mnt.asset(bad)


def test_a_valid_selection_is_normalised_to_catalog_order():
    assert mnt.validate_asset_ids(["application_logs", "virtual_environment"]) == (
        "virtual_environment", "application_logs",
    )


def test_an_empty_selection_is_refused():
    with pytest.raises(mnt.SchemaError):
        mnt.validate_asset_ids([])


def test_a_duplicated_selection_is_refused():
    with pytest.raises(mnt.SchemaError):
        mnt.validate_asset_ids(["application_logs", "application_logs"])


def test_a_bare_string_is_not_a_selection():
    with pytest.raises(mnt.SchemaError):
        mnt.validate_asset_ids("virtual_environment")


# --------------------------------------------------------------------------- #
# Target authorization
# --------------------------------------------------------------------------- #


def test_each_id_maps_to_its_exact_target_under_the_fake_root(tmp_path):
    root = fake_root(tmp_path)
    assert mnt.authorized_target("virtual_environment", root) == root / ".venv"
    assert mnt.authorized_target("portable_binaries", root) == root / "files" / "bin"
    assert mnt.authorized_target("downloaded_models", root) == (
        root / "files" / "runtime-data" / "models"
    )
    assert mnt.authorized_target("application_logs", root) == (
        root / "files" / "runtime-data" / "logs"
    )


def test_a_target_is_always_inside_the_supplied_root(tmp_path):
    root = fake_root(tmp_path)
    for asset_id in mnt.ASSET_IDS:
        target = mnt.authorized_target(asset_id, root)
        assert str(target).startswith(str(root))
        assert target != root


def test_mapping_follows_the_root_it_is_given_not_the_real_repository(tmp_path):
    root = fake_root(tmp_path)
    target = mnt.authorized_target("virtual_environment", root)
    assert REPO_ROOT not in target.parents
    assert target != REPO_ROOT / ".venv"


def test_assert_authorized_accepts_only_the_compiled_target(tmp_path):
    root = fake_root(tmp_path)
    good = mnt.authorized_target("application_logs", root)
    assert mnt.assert_authorized("application_logs", root, good) == good


@pytest.mark.parametrize("relative", [
    "", "scripts", "md-instructions", "files/tests", "config.toml",
    "config-template.toml", "files/runtime-data/settings.json",
    "Setup_and_Run-audiobook-creation-tool.bat", "files/runtime-data",
])
def test_a_protected_or_root_path_is_never_an_authorized_target(tmp_path, relative):
    root = fake_root(tmp_path)
    candidate = root.joinpath(*relative.split("/")) if relative else root
    with pytest.raises(mnt.UnsafeTargetError):
        mnt.assert_authorized("application_logs", root, candidate)


def test_a_system_path_is_never_an_authorized_target(tmp_path):
    root = fake_root(tmp_path)
    for outsider in (Path("C:/Windows/System32"), Path("/usr/bin/ffmpeg"),
                     Path.home(), tmp_path):
        with pytest.raises(mnt.UnsafeTargetError):
            mnt.assert_authorized("portable_binaries", root, outsider)


def test_a_target_that_would_swallow_a_protected_path_is_refused(tmp_path, monkeypatch):
    """Structural: if a future edit widened a target, authorization refuses it.

    ``files/`` contains the protected ``files/tests``, so widening the binaries
    target to it must fail even though the path is inside the project.
    """
    root = fake_root(tmp_path)
    widened = mnt.AssetDefinition(
        asset_id="portable_binaries", display_name="Portable binaries",
        relative_target="files", consequence="", effect_line="",
        requires_post_exit=False, removes_target_itself=False,
    )
    monkeypatch.setattr(
        mnt, "CATALOG_BY_ID", {**mnt.CATALOG_BY_ID, "portable_binaries": widened}
    )
    with pytest.raises(mnt.UnsafeTargetError):
        mnt.authorized_target("portable_binaries", root)


def test_a_linked_target_is_refused_rather_than_followed(tmp_path):
    root = fake_root(tmp_path, models=False)
    elsewhere = tmp_path / "outside-models"
    write(elsewhere / "big.bin", b"q" * 4096)
    link = root / "files" / "runtime-data" / "models"
    if not make_junction(link, elsewhere):
        pytest.skip("this account cannot create a directory link here")
    with pytest.raises(mnt.UnsafeTargetError):
        mnt.authorized_target("downloaded_models", root)


def test_a_linked_ancestor_is_refused_rather_than_followed(tmp_path):
    root = tmp_path / "fake-repo"
    (root / "files").mkdir(parents=True)
    real = tmp_path / "elsewhere-runtime"
    write(real / "logs" / "x.log", b"p" * 32)
    link = root / "files" / "runtime-data"
    if not make_junction(link, real):
        pytest.skip("this account cannot create a directory link here")
    with pytest.raises(mnt.UnsafeTargetError):
        mnt.authorized_target("application_logs", root)


def test_a_linked_repository_root_is_refused(tmp_path):
    real = fake_root(tmp_path)
    link = tmp_path / "linked-repo"
    if not make_junction(link, real):
        pytest.skip("this account cannot create a directory link here")
    with pytest.raises(mnt.UnsafeTargetError):
        mnt.authorized_target("virtual_environment", link)


# --------------------------------------------------------------------------- #
# Size estimation
# --------------------------------------------------------------------------- #


def test_nested_regular_file_bytes_are_totalled(tmp_path):
    root = fake_root(tmp_path)
    estimate = mnt.estimate_size(root / ".venv")
    assert estimate.total_bytes == VENV_BYTES
    assert estimate.complete is True
    assert estimate.problems == ()


def test_an_empty_target_measures_zero_and_is_complete(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    estimate = mnt.estimate_size(empty)
    assert estimate.total_bytes == 0
    assert estimate.complete is True


def test_a_missing_target_measures_zero_without_raising(tmp_path):
    estimate = mnt.estimate_size(tmp_path / "not-there")
    assert estimate.total_bytes == 0
    assert estimate.complete is True


class _VanishedEntry:
    """A directory entry whose file is gone by the time it is measured.

    A real ``DirEntry`` on Windows caches its size from the directory
    enumeration, so deleting the file mid-walk would not reproduce the race.
    This raises from ``stat`` the way the OS does when the file has genuinely
    gone — a log rotating underneath the walk.
    """

    def __init__(self, parent: Path):
        self.name = "rotated.log"
        self.path = str(parent / self.name)

    def is_symlink(self):
        return False

    def is_dir(self, follow_symlinks=True):
        return False

    def is_file(self, follow_symlinks=True):
        return True

    def stat(self, follow_symlinks=True):
        raise FileNotFoundError(2, "No such file or directory", self.path)


def test_a_file_disappearing_mid_walk_is_tolerated(tmp_path, monkeypatch):
    root = fake_root(tmp_path)
    target = root / ".venv"
    real_scandir = os.scandir

    def vanishing(path):
        entries = list(real_scandir(path))
        if Path(path) == target:
            entries.append(_VanishedEntry(target))
        return iter(entries)

    monkeypatch.setattr(mnt.os, "scandir", vanishing)
    estimate = mnt.estimate_size(target)
    assert estimate.total_bytes == VENV_BYTES   # the surviving files only
    assert estimate.complete is True            # vanishing is normal, not an error
    assert estimate.problems == ()


def test_a_vanished_folder_is_skipped_without_an_error(tmp_path, monkeypatch):
    root = fake_root(tmp_path)
    real_scandir = os.scandir

    def vanishing(path):
        if Path(path).name == "Lib":
            raise FileNotFoundError(2, "No such file or directory", str(path))
        return real_scandir(path)

    monkeypatch.setattr(mnt.os, "scandir", vanishing)
    estimate = mnt.estimate_size(root / ".venv")
    assert estimate.total_bytes == 100
    assert estimate.complete is True


def test_an_unreadable_subfolder_makes_the_estimate_incomplete(tmp_path, monkeypatch):
    root = fake_root(tmp_path)
    target = root / ".venv"
    real_scandir = os.scandir

    def refusing(path):
        if Path(path).name == "Lib":
            raise PermissionError(13, "Access is denied")
        return real_scandir(path)

    monkeypatch.setattr(mnt.os, "scandir", refusing)
    estimate = mnt.estimate_size(target)
    assert estimate.complete is False
    assert estimate.problems
    assert estimate.total_bytes == 100          # a floor, not a false exact total


def test_estimation_never_follows_a_directory_link(tmp_path):
    root = fake_root(tmp_path)
    outside = tmp_path / "huge-outside"
    write(outside / "enormous.bin", b"x" * 9000)
    if not make_junction(root / ".venv" / "linked", outside):
        pytest.skip("this account cannot create a directory link here")
    estimate = mnt.estimate_size(root / ".venv")
    assert estimate.total_bytes == VENV_BYTES   # the 9000 bytes were not counted
    assert estimate.complete is False
    assert any("link" in p for p in estimate.problems)


def test_estimation_modifies_nothing_it_measures(tmp_path):
    root = fake_root(tmp_path)
    before = snapshot(root)
    before_dirs = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    for asset_id in mnt.ASSET_IDS:
        mnt.estimate_size(mnt.authorized_target(asset_id, root))
    assert snapshot(root) == before
    assert sorted(str(p.relative_to(root)) for p in root.rglob("*")) == before_dirs


@pytest.mark.parametrize("count,expected", [
    (0, "0 bytes"), (1, "1 byte"), (999, "999 bytes"),
    (1024, "1.0 KB"), (1536, "1.5 KB"), (1048576, "1.0 MB"),
    (1073741824, "1.0 GB"), (1099511627776, "1.0 TB"),
])
def test_byte_formatting_is_human_and_exact(count, expected):
    assert mnt.format_bytes(count) == expected


def test_a_negative_byte_count_is_refused():
    with pytest.raises(ValueError):
        mnt.format_bytes(-1)


# --------------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------------- #


def test_a_full_fake_root_reports_four_present_selectable_items(tmp_path):
    items = mnt.inventory(fake_root(tmp_path))
    assert len(items) == 4
    assert [i.asset_id for i in items] == list(mnt.ASSET_IDS)
    assert all(i.present and i.selectable for i in items)


def test_inventory_sizes_match_the_fixture_totals(tmp_path):
    by_id = items_by_id(mnt.inventory(fake_root(tmp_path)))
    assert by_id["virtual_environment"].size.total_bytes == VENV_BYTES
    assert by_id["portable_binaries"].size.total_bytes == BIN_BYTES
    assert by_id["downloaded_models"].size.total_bytes == MODEL_BYTES
    assert by_id["application_logs"].size.total_bytes == LOG_BYTES


def test_a_missing_target_is_a_normal_state_not_an_error(tmp_path):
    root = fake_root(tmp_path, venv=False, models=False)
    by_id = items_by_id(mnt.inventory(root))
    assert by_id["virtual_environment"].present is False
    assert by_id["virtual_environment"].selectable is False
    assert by_id["virtual_environment"].size is None
    assert by_id["virtual_environment"].problem is None
    assert by_id["virtual_environment"].state_text == "Missing"
    assert by_id["portable_binaries"].present is True


def test_a_wrong_typed_target_is_present_but_unavailable(tmp_path):
    root = fake_root(tmp_path, binaries=False)
    write(root / "files" / "bin", b"not a folder")
    item = items_by_id(mnt.inventory(root))["portable_binaries"]
    assert item.present is True
    assert item.selectable is False
    assert item.problem == mnt.NOT_A_FOLDER_PROBLEM


def test_a_linked_target_is_present_but_unavailable_with_an_explanation(tmp_path):
    root = fake_root(tmp_path, logs=False)
    real = tmp_path / "outside-logs"
    write(real / "a.log", b"a" * 10)
    if not make_junction(root / "files" / "runtime-data" / "logs", real):
        pytest.skip("this account cannot create a directory link here")
    item = items_by_id(mnt.inventory(root))["application_logs"]
    assert item.present is True
    assert item.selectable is False
    assert "link" in (item.problem or "")


def test_an_unmeasured_inventory_walks_nothing(tmp_path, monkeypatch):
    root = fake_root(tmp_path)
    monkeypatch.setattr(mnt, "estimate_size",
                        lambda p: pytest.fail("measure=False must not walk"))
    items = mnt.inventory(root, measure=False)
    assert all(i.size is None for i in items)
    assert all(i.size_text == mnt.CALCULATING_TEXT for i in items)


def test_an_incomplete_size_is_labelled_as_a_minimum(tmp_path, monkeypatch):
    root = fake_root(tmp_path)
    monkeypatch.setattr(mnt, "estimate_size",
                        lambda p: mnt.SizeEstimate(64, False, ("unreadable",)))
    item = items_by_id(mnt.inventory(root))["application_logs"]
    assert item.selectable is True
    assert item.size_text == "64 bytes (at least)"
    assert item.problem == mnt.INCOMPLETE_PROBLEM


def test_inventory_items_are_immutable(tmp_path):
    item = mnt.inventory(fake_root(tmp_path))[0]
    with pytest.raises(FrozenInstanceError):
        item.selectable = True
    with pytest.raises(FrozenInstanceError):
        item.size = None


def test_inventory_modifies_nothing(tmp_path):
    root = fake_root(tmp_path)
    before = snapshot(root)
    listing = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    mnt.inventory(root)
    mnt.inventory(root, measure=False)
    assert snapshot(root) == before
    assert sorted(str(p.relative_to(root)) for p in root.rglob("*")) == listing


def test_inventory_creates_no_missing_target(tmp_path):
    root = fake_root(tmp_path, venv=False)
    mnt.inventory(root)
    assert not (root / ".venv").exists()


def test_settings_config_and_outputs_never_appear_in_an_inventory(tmp_path):
    root = fake_root(tmp_path)
    targets = {str(mnt.authorized_target(i, root)) for i in mnt.ASSET_IDS}
    for protected in ("config.toml", "files/runtime-data/settings.json",
                      "scripts", "md-instructions", "files/tests"):
        assert str(root.joinpath(*protected.split("/"))) not in targets


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #


def test_a_selection_totals_only_what_was_chosen(tmp_path):
    items = mnt.inventory(fake_root(tmp_path))
    summary = mnt.summarise_selection(items, ["application_logs", "portable_binaries"])
    assert summary.asset_ids == ("portable_binaries", "application_logs")
    assert summary.known_bytes == BIN_BYTES + LOG_BYTES
    assert summary.complete is True
    assert summary.count == 2


def test_an_empty_selection_totals_nothing(tmp_path):
    items = mnt.inventory(fake_root(tmp_path))
    summary = mnt.summarise_selection(items, [])
    assert summary.asset_ids == ()
    assert summary.known_bytes == 0
    assert mnt.selected_total_text(summary) == mnt.NOTHING_SELECTED_TEXT


def test_selecting_a_missing_item_is_refused(tmp_path):
    items = mnt.inventory(fake_root(tmp_path, venv=False))
    with pytest.raises(mnt.SelectionError):
        mnt.summarise_selection(items, ["virtual_environment"])


def test_selecting_an_unknown_id_is_refused(tmp_path):
    items = mnt.inventory(fake_root(tmp_path))
    with pytest.raises(mnt.UnknownAssetError):
        mnt.summarise_selection(items, ["everything"])


def test_selecting_the_same_item_twice_is_refused(tmp_path):
    items = mnt.inventory(fake_root(tmp_path))
    with pytest.raises(mnt.SelectionError):
        mnt.summarise_selection(items, ["application_logs", "application_logs"])


def test_an_unknown_size_keeps_the_total_honest(tmp_path, monkeypatch):
    root = fake_root(tmp_path)
    monkeypatch.setattr(mnt, "estimate_size",
                        lambda p: mnt.SizeEstimate(10, False, ("unreadable",)))
    items = mnt.inventory(root)
    summary = mnt.summarise_selection(items, ["application_logs"])
    assert summary.complete is False
    assert "could not be read safely" in mnt.selected_total_text(summary)
    assert "could not be read safely" in mnt.freed_space_line(summary)


def test_a_complete_total_states_an_exact_figure(tmp_path):
    items = mnt.inventory(fake_root(tmp_path))
    summary = mnt.summarise_selection(items, ["application_logs"])
    assert mnt.freed_space_line(summary) == "Estimated space to be freed: 50 bytes."


# --------------------------------------------------------------------------- #
# Confirmation wording
# --------------------------------------------------------------------------- #


def test_the_confirmation_body_uses_the_approved_wording(tmp_path):
    items = mnt.inventory(fake_root(tmp_path))
    body = mnt.confirmation_body(items, ["virtual_environment", "application_logs"])

    assert body.startswith("You selected 2 downloaded-data item(s) to clear:")
    assert "• Private Python environment — Present, 500 bytes" in body
    assert "• Application logs — Present, 50 bytes" in body
    assert "Estimated space to be freed: 550 bytes." in body
    assert (
        "Audiobook Creation Tool will close before cleanup starts. Selected data will "
        "be removed only after the app has exited." in body
    )
    assert (
        "Preferences, config.toml, source media, and audiobook outputs are not included."
        in body
    )
    assert body.endswith(
        "This cleanup cannot be undone, although selected dependencies, binaries, and "
        "models can be rebuilt or downloaded again. Continue?"
    )


def test_only_the_applicable_effect_lines_appear(tmp_path):
    items = mnt.inventory(fake_root(tmp_path))
    body = mnt.confirmation_body(items, ["application_logs"])
    assert mnt.CATALOG_BY_ID["application_logs"].effect_line in body
    for other in ("virtual_environment", "portable_binaries", "downloaded_models"):
        assert mnt.CATALOG_BY_ID[other].effect_line not in body


def test_the_body_states_the_exact_selected_count(tmp_path):
    items = mnt.inventory(fake_root(tmp_path))
    assert "You selected 1 downloaded-data item(s)" in mnt.confirmation_body(
        items, ["portable_binaries"]
    )
    assert "You selected 4 downloaded-data item(s)" in mnt.confirmation_body(
        items, list(mnt.ASSET_IDS)
    )


def test_the_body_reports_an_unreadable_size_rather_than_a_false_total(tmp_path,
                                                                       monkeypatch):
    root = fake_root(tmp_path)
    monkeypatch.setattr(mnt, "estimate_size",
                        lambda p: mnt.SizeEstimate(0, False, ("unreadable",)))
    items = mnt.inventory(root)
    body = mnt.confirmation_body(items, ["downloaded_models"])
    assert (
        "Estimated space to be freed: 0 bytes, plus data whose size could not be "
        "read safely." in body
    )


def test_the_destructive_button_label_is_singular_or_plural():
    assert mnt.confirmation_button_label(1) == "Clear 1 Selected Item and Close"
    assert mnt.confirmation_button_label(2) == "Clear 2 Selected Items and Close"
    assert mnt.confirmation_button_label(4) == "Clear 4 Selected Items and Close"


def test_the_dialog_title_and_intro_are_exact():
    assert mnt.CLEANUP_DIALOG_TITLE == "Clear Downloaded Data"
    assert mnt.CONFIRM_TITLE == "Confirm clearing downloaded data"
    assert mnt.CLEANUP_INTRO == (
        "Remove only regenerable data downloaded or created by Audiobook Creation "
        "Tool. Your preferences, configuration, source media, and audiobook outputs "
        "are not included."
    )


def test_the_fail_closed_message_is_exact():
    assert mnt.CLEANUP_UNAVAILABLE_MESSAGE == (
        "Cleanup did not start. Safe post-exit cleanup is not available yet. No data "
        "was changed, and Audiobook Creation Tool will remain open."
    )


# --------------------------------------------------------------------------- #
# Cleanup request schema
# --------------------------------------------------------------------------- #


def build(ids=("application_logs",), **kw):
    kw.setdefault("clock", lambda: FIXED_TIME)
    kw.setdefault("process_id", 4321)
    kw.setdefault("request_id", FIXED_UUID)
    return mnt.build_request(ids, **kw)


def test_a_request_round_trips_through_json():
    request = build(("application_logs", "virtual_environment"))
    payload = json.dumps(mnt.request_to_dict(request))
    restored = mnt.request_from_dict(json.loads(payload))
    assert restored == request


def test_a_request_is_immutable():
    request = build()
    with pytest.raises(FrozenInstanceError):
        request.asset_ids = ("virtual_environment",)
    assert isinstance(request.asset_ids, tuple)


def test_request_ids_are_stored_in_deterministic_catalog_order():
    a = build(("application_logs", "virtual_environment"))
    b = build(("virtual_environment", "application_logs"))
    assert a.asset_ids == b.asset_ids == ("virtual_environment", "application_logs")
    assert mnt.request_to_dict(a) == mnt.request_to_dict(b)


def test_the_defaults_use_the_real_clock_pid_and_a_fresh_uuid():
    request = mnt.build_request(["application_logs"])
    assert request.process_id == os.getpid()
    assert request.created_at.tzinfo is not None
    assert uuid.UUID(request.request_id)
    assert mnt.build_request(["application_logs"]).request_id != request.request_id


def test_an_empty_request_is_refused():
    with pytest.raises(mnt.SchemaError):
        build(())


def test_a_duplicated_request_selection_is_refused():
    with pytest.raises(mnt.SchemaError):
        build(("application_logs", "application_logs"))


def test_an_unknown_id_cannot_enter_a_request():
    with pytest.raises(mnt.UnknownAssetError):
        build(("everything",))
    with pytest.raises(mnt.UnknownAssetError):
        build(("../../.venv",))


@pytest.mark.parametrize("pid", [0, -1, -4321])
def test_a_nonpositive_pid_is_refused(pid):
    with pytest.raises(mnt.SchemaError):
        build(process_id=pid)


@pytest.mark.parametrize("pid", ["4321", 4321.0, True, [4321]])
def test_a_wrong_typed_pid_is_refused(pid):
    with pytest.raises(mnt.SchemaError):
        build(process_id=pid)


def test_a_naive_timestamp_is_refused():
    with pytest.raises(mnt.SchemaError):
        build(clock=lambda: datetime(2026, 8, 4, 9, 30))


@pytest.mark.parametrize("bad", ["not-a-uuid", "", "1234", 17, ["x"]])
def test_a_malformed_request_id_is_refused(bad):
    with pytest.raises(mnt.SchemaError):
        build(request_id=bad)


def test_a_wrong_schema_version_is_refused():
    data = mnt.request_to_dict(build())
    data["schema_version"] = 2
    with pytest.raises(mnt.SchemaError):
        mnt.request_from_dict(data)
    data["schema_version"] = "1"
    with pytest.raises(mnt.SchemaError):
        mnt.request_from_dict(data)


def test_an_extra_request_field_is_refused():
    data = mnt.request_to_dict(build())
    data["target_path"] = "C:/Windows"
    with pytest.raises(mnt.SchemaError):
        mnt.request_from_dict(data)


def test_a_missing_request_field_is_refused():
    data = mnt.request_to_dict(build())
    del data["process_id"]
    with pytest.raises(mnt.SchemaError):
        mnt.request_from_dict(data)


@pytest.mark.parametrize("value", ["application_logs", 3, None, {"a": 1}])
def test_wrong_json_types_for_asset_ids_are_refused(value):
    data = mnt.request_to_dict(build())
    data["asset_ids"] = value
    with pytest.raises((mnt.SchemaError, mnt.UnknownAssetError)):
        mnt.request_from_dict(data)


@pytest.mark.parametrize("value", ["2026-08-04T09:30:00", "not a time", 17, None])
def test_a_bad_serialized_timestamp_is_refused(value):
    data = mnt.request_to_dict(build())
    data["created_at"] = value
    with pytest.raises(mnt.SchemaError):
        mnt.request_from_dict(data)


def test_a_request_is_not_a_dict_of_something_else():
    for bad in ([], "x", None, 5):
        with pytest.raises(mnt.SchemaError):
            mnt.request_from_dict(bad)


# --------------------------------------------------------------------------- #
# Cleanup result schema
# --------------------------------------------------------------------------- #


def make_result(outcomes=None, **kw):
    kw.setdefault("schema_version", mnt.SCHEMA_VERSION)
    kw.setdefault("request_id", FIXED_UUID)
    kw.setdefault("started_at", FIXED_TIME)
    kw.setdefault("completed_at", FIXED_TIME + timedelta(seconds=9))
    if outcomes is None:
        outcomes = (mnt.AssetOutcome("application_logs", "removed", 50, "Removed."),)
    return mnt.CleanupResult(outcomes=tuple(outcomes), **kw)


def test_a_result_round_trips_through_json():
    result = make_result((
        mnt.AssetOutcome("virtual_environment", "removed", 500, "Removed."),
        mnt.AssetOutcome("application_logs", "missing", None, "Nothing to remove."),
    ))
    restored = mnt.result_from_dict(json.loads(json.dumps(mnt.result_to_dict(result))))
    assert restored == result


def test_a_result_and_its_outcomes_are_immutable():
    result = make_result()
    with pytest.raises(FrozenInstanceError):
        result.request_id = FIXED_UUID
    with pytest.raises(FrozenInstanceError):
        result.outcomes[0].status = "failed"
    assert isinstance(result.outcomes, tuple)


def test_result_outcomes_are_held_in_catalog_order():
    result = make_result((
        mnt.AssetOutcome("application_logs", "removed", 1),
        mnt.AssetOutcome("virtual_environment", "removed", 2),
    ))
    assert [o.asset_id for o in result.outcomes] == [
        "virtual_environment", "application_logs",
    ]


@pytest.mark.parametrize("status", ["removed", "missing", "failed", "refused"])
def test_every_closed_status_is_accepted(status):
    assert mnt.AssetOutcome("application_logs", status).status == status


@pytest.mark.parametrize("status", ["deleted", "ok", "", None, 1, "REMOVED"])
def test_an_unknown_status_is_refused(status):
    with pytest.raises(mnt.SchemaError):
        mnt.AssetOutcome("application_logs", status)


def test_an_unknown_outcome_id_is_refused():
    with pytest.raises(mnt.UnknownAssetError):
        mnt.AssetOutcome("everything", "removed")


def test_a_negative_bytes_freed_is_refused():
    with pytest.raises(mnt.SchemaError):
        mnt.AssetOutcome("application_logs", "removed", -1)


def test_a_duplicated_outcome_is_refused():
    with pytest.raises(mnt.SchemaError):
        make_result((
            mnt.AssetOutcome("application_logs", "removed"),
            mnt.AssetOutcome("application_logs", "failed"),
        ))


def test_an_empty_result_is_refused():
    with pytest.raises(mnt.SchemaError):
        make_result(())


def test_a_result_that_finishes_before_it_starts_is_refused():
    with pytest.raises(mnt.SchemaError):
        make_result(completed_at=FIXED_TIME - timedelta(seconds=1))


def test_a_naive_result_timestamp_is_refused():
    with pytest.raises(mnt.SchemaError):
        make_result(started_at=datetime(2026, 8, 4, 9, 30))


def test_a_wrong_result_schema_version_is_refused():
    with pytest.raises(mnt.SchemaError):
        make_result(schema_version=2)


def test_an_extra_result_or_outcome_field_is_refused():
    data = mnt.result_to_dict(make_result())
    data["deleted_path"] = "C:/Windows"
    with pytest.raises(mnt.SchemaError):
        mnt.result_from_dict(data)

    data = mnt.result_to_dict(make_result())
    data["outcomes"][0]["target"] = "C:/Windows"
    with pytest.raises(mnt.SchemaError):
        mnt.result_from_dict(data)


def test_a_malformed_result_request_id_is_refused():
    with pytest.raises(mnt.SchemaError):
        make_result(request_id="not-a-uuid")


# --------------------------------------------------------------------------- #
# The no-paths guarantee
# --------------------------------------------------------------------------- #

PATHY = ("path", "target", "directory", "dir", "root", "command", "cmd", "exe",
         "executable", "argv", "script")


def test_no_schema_field_can_carry_a_path_or_a_command():
    for field in mnt.REQUEST_FIELDS + mnt.RESULT_FIELDS + mnt.OUTCOME_FIELDS:
        for word in PATHY:
            assert word not in field.lower(), field


def test_a_serialized_request_contains_no_path_like_value():
    payload = json.dumps(mnt.request_to_dict(build(tuple(mnt.ASSET_IDS))))
    assert "/" not in payload
    assert "\\" not in payload
    for word in PATHY:
        assert word not in payload.lower()


def test_a_serialized_result_contains_no_path_like_value():
    payload = json.dumps(mnt.result_to_dict(make_result()))
    for word in PATHY:
        assert word not in payload.lower()


def test_a_request_carries_no_repository_root(tmp_path):
    request = build(tuple(mnt.ASSET_IDS))
    payload = json.dumps(mnt.request_to_dict(request))
    assert str(tmp_path) not in payload
    assert str(REPO_ROOT) not in payload
    assert not hasattr(request, "repo_root")


# --------------------------------------------------------------------------- #
# The Phase 6 boundary — structural guards
# --------------------------------------------------------------------------- #


def module_tree():
    return ast.parse(MODULE.read_text(encoding="utf-8"))


def test_the_maintenance_module_calls_no_destructive_primitive():
    tree = module_tree()
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    called |= {n.func.id for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    for destructive in ("rmtree", "unlink", "remove", "removedirs", "rmdir",
                        "truncate", "write_text", "write_bytes", "replace",
                        "rename", "chmod", "Popen", "system", "spawnv",
                        "execv", "fork", "kill", "startfile"):
        assert destructive not in called, destructive


def test_the_maintenance_module_imports_no_deletion_or_process_library():
    tree = module_tree()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    for forbidden in ("shutil", "subprocess", "multiprocessing", "signal",
                      "atexit", "threading", "tkinter"):
        assert forbidden not in imported, forbidden


def test_the_maintenance_module_defines_no_executor_or_coordinator():
    tree = module_tree()
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    for phase_seven in ("run_cleanup", "execute", "execute_request", "perform_cleanup",
                        "delete_asset", "delete_assets", "remove_asset", "coordinator",
                        "CleanupCoordinator", "CleanupWorker", "write_request",
                        "save_request", "persist_request", "consume_request",
                        "write_result", "schedule_cleanup", "wait_for_exit"):
        assert phase_seven not in defined, phase_seven


def test_no_maintenance_state_directory_or_request_filename_is_named():
    source = MODULE.read_text(encoding="utf-8")
    for phase_seven in ("maintenance-state", "cleanup-request", "cleanup_request.json",
                        "cleanup-result", ".act-cleanup"):
        assert phase_seven not in source, phase_seven


def test_the_module_never_writes_to_the_filesystem(tmp_path):
    """Behavioural, not only structural: a read-only fake root still works."""
    root = fake_root(tmp_path)
    before = snapshot(root)
    items = mnt.inventory(root)
    mnt.summarise_selection(items, ["application_logs"])
    mnt.confirmation_body(items, ["application_logs"])
    request = build(("application_logs",))
    mnt.request_to_dict(request)
    assert snapshot(root) == before
    assert not list(tmp_path.glob("**/*cleanup*"))
    assert not list(tmp_path.glob("**/*request*"))


def test_the_fail_closed_handler_refuses_and_changes_nothing(tmp_path):
    root = fake_root(tmp_path)
    before = snapshot(root)
    assert mnt.unavailable_cleanup_handler(build(tuple(mnt.ASSET_IDS))) is False
    assert snapshot(root) == before


def test_the_fail_closed_handler_only_accepts_a_real_request():
    with pytest.raises(mnt.SchemaError):
        mnt.unavailable_cleanup_handler({"asset_ids": ["application_logs"]})


def test_inventory_always_requires_an_explicit_root():
    import inspect

    signature = inspect.signature(mnt.inventory)
    assert signature.parameters["repo_root"].default is inspect.Parameter.empty
    for name in ("authorized_target", "compiled_target", "assert_authorized"):
        params = inspect.signature(getattr(mnt, name)).parameters
        assert params["repo_root"].default is inspect.Parameter.empty


def test_the_module_never_defaults_to_the_real_repository_root():
    source = MODULE.read_text(encoding="utf-8")
    assert "REPO_ROOT" not in source
    assert "from . import paths" not in source
    assert "from .paths" not in source


# --------------------------------------------------------------------------- #
# Reset Preferences stays separate
# --------------------------------------------------------------------------- #


def test_the_catalog_cannot_reach_settings_or_reset_preferences(tmp_path):
    root = fake_root(tmp_path)
    settings = root / "files" / "runtime-data" / "settings.json"
    for asset_id in mnt.ASSET_IDS:
        target = mnt.authorized_target(asset_id, root)
        assert target != settings
        assert settings.parent != target
        assert not str(settings).startswith(str(target) + os.sep)


def test_maintenance_can_neither_read_nor_reset_preferences():
    """``settings.json`` appears only in the protected list — never as a target."""
    tree = module_tree()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(a.name for a in node.names)
    assert "settings" not in imported
    assert "config" not in imported

    source = MODULE.read_text(encoding="utf-8")
    for word in ("reset_preferences", "last_tool", "output_base", "set_output_base"):
        assert word not in source, word
    assert "files/runtime-data/settings.json" in mnt.PROTECTED_RELATIVE


def test_selection_state_is_never_persisted():
    source = MODULE.read_text(encoding="utf-8").lower()
    for word in ("last_selection", "save_selection", "remembered_selection",
                 "suppress", "do_not_ask", "dont_ask"):
        assert word not in source, word


# --------------------------------------------------------------------------- #
# Existing safety contracts are untouched
# --------------------------------------------------------------------------- #


def test_phase_four_and_five_output_contracts_are_unchanged():
    from shared import output_paths

    assert output_paths.TEMP_SIBLING_PREFIX == ".act-tmp-"
    assert hasattr(output_paths, "reserve_run_directory")
    assert hasattr(output_paths, "atomic_replace")
    assert hasattr(output_paths, "validate_custom_destination")


def test_phase_six_added_no_output_or_tool_behaviour():
    """``ffmpeg`` appears only in the binaries wording, never as behaviour."""
    source = MODULE.read_text(encoding="utf-8")
    for foreign in ("output_paths", "reserve_run_directory", "DestinationPlanner",
                    "atomic_replace", "Cover", "M4B", "resize", "pydub"):
        assert foreign not in source, foreign


def test_the_application_version_is_still_unchanged():
    from shared.version import VERSION

    assert VERSION == "0.5.1"


def test_no_test_in_this_module_measures_the_real_repository():
    """Structural self-check: every root that reaches maintenance is disposable.

    Parsed rather than grepped so this test cannot trip over its own text: it
    reads the call sites and asserts that no call into the maintenance module
    passes ``REPO_ROOT`` — the only real path this file knows.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    entry_points = {"inventory", "estimate_size", "authorized_target",
                    "compiled_target", "assert_authorized"}

    def names_repo_root(node) -> bool:
        return any(isinstance(n, ast.Name) and n.id == "REPO_ROOT"
                   for n in ast.walk(node))

    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        func = call.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in entry_points:
            continue
        for argument in list(call.args) + [k.value for k in call.keywords]:
            assert not names_repo_root(argument), (
                f"{name}() was handed the real repository root"
            )
