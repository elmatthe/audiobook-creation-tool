"""v0.6.0 Drop 2 Phase 3 — output base, run reservation, collision, mirroring.

Everything runs in ``tmp_path`` against an injected configuration snapshot, so
no test resolves or writes the maintainer's real Downloads folder, settings,
outputs, logs, ``.venv``, models, binaries or media. Nothing here builds a Tk
widget: the whole surface is platform-neutral by design.

Nothing in the application consumes these services yet — that is Phase 4, and
the scope guards at the foot of this file hold that line.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path, PurePath

import pytest

from shared import config, output_paths as op
from shared import paths as shared_paths

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

ALL_TOOL_KEYS = ("tts", "m4b_converter", "mp3_tool", "m4b_maker", "cover", "m4b_metadata")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def snapshot_with_base(tmp_path: Path, base: str = "") -> object:
    """An effective configuration snapshot pointing at a temporary base."""
    root = tmp_path / "fakerepo"
    entry = root / "scripts" / "Universal" / "launcher.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("#\n", encoding="utf-8")
    body = f"""
[project]
name = "Audiobook Creation Tool"
version = "{config.DEFAULTS['project.version']}"
python_min = "3.11"
entry_point = "scripts/Universal/launcher.py"
platforms = ["Windows", "MacOS"]

[output]
base_directory = "{base}"
"""
    (root / "config.toml").write_text(body, encoding="utf-8")
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True, exist_ok=True)
    return config.load(
        config_path=root / "config.toml", settings_data={}, repo_root=root, home=home
    )


def touch(path: Path, payload: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def make_dir_link(link: Path, target: Path) -> str:
    """Create a directory link, returning "" on success or the reason it failed.

    Tries a symlink first, then a Windows **junction**, which needs neither
    Developer Mode nor elevation — so the link-safety tests get real coverage
    on an ordinary Windows account instead of being skipped wholesale.
    """
    try:
        link.symlink_to(target, target_is_directory=True)
        return ""
    except (OSError, NotImplementedError, AttributeError) as exc:
        symlink_reason = f"symlink: {type(exc).__name__}: {exc}"
    if os.name != "nt":
        return symlink_reason
    import subprocess

    try:
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{symlink_reason}; junction: {type(exc).__name__}: {exc}"
    if completed.returncode != 0 or not link.exists():
        return f"{symlink_reason}; junction: {completed.stderr.strip() or completed.stdout.strip()}"
    return ""


def make_file_link(link: Path, target: Path) -> str:
    """Create a file link, returning "" on success or the reason it failed.

    A *file* hardlink is not a reparse point, so only a symlink will do here;
    on Windows that genuinely needs the privilege and the test skips.
    """
    try:
        link.symlink_to(target)
        return ""
    except (OSError, NotImplementedError, AttributeError) as exc:
        return f"symlink: {type(exc).__name__}: {exc}"


@pytest.fixture
def dir_link_support(tmp_path):
    """Skip with an exact reason if no directory link can be made here."""
    target = tmp_path / "_linktarget"
    target.mkdir(exist_ok=True)
    probe = tmp_path / "_linkprobe"
    reason = make_dir_link(probe, target)
    if reason:
        pytest.skip(f"this environment cannot create a directory link — {reason}")
    return make_dir_link


# --------------------------------------------------------------------------- #
# A. Effective output-base resolution
# --------------------------------------------------------------------------- #


def test_the_default_base_is_downloads_audiobook_outputs(tmp_path):
    snapshot = snapshot_with_base(tmp_path)
    base = op.resolve_output_base(snapshot)
    assert base == tmp_path / "home" / "Downloads" / "Audiobook-Creation-Tool-Outputs"


def test_a_custom_absolute_base_is_used(tmp_path):
    custom = tmp_path / "Custom" / "Outputs"
    snapshot = snapshot_with_base(tmp_path, custom.as_posix())
    assert op.resolve_output_base(snapshot) == custom


def test_a_tilde_base_is_expanded(tmp_path):
    snapshot = snapshot_with_base(tmp_path, "~/MediaOut")
    base = op.resolve_output_base(snapshot)
    assert base.is_absolute() and not str(base).startswith("~")
    assert base.name == "MediaOut"


def test_a_relative_base_falls_back_to_the_default(tmp_path):
    """Phase 1 rejects it during validation; the base is still absolute here."""
    snapshot = snapshot_with_base(tmp_path, "Outputs")
    assert any(d.key == "output.base_directory" for d in snapshot.diagnostics)
    assert op.resolve_output_base(snapshot).is_absolute()
    assert snapshot.output.is_default is True


@pytest.mark.parametrize("raw", ["%USERPROFILE%/Out", "$HOME/Out"])
def test_environment_variables_are_never_expanded_into_a_base(tmp_path, raw):
    snapshot = snapshot_with_base(tmp_path, raw)
    base = op.resolve_output_base(snapshot)
    assert "%" not in str(base) and "$" not in str(base)
    assert snapshot.output.is_default is True


def test_resolving_a_base_creates_nothing(tmp_path):
    custom = tmp_path / "NeverCreated"
    snapshot = snapshot_with_base(tmp_path, custom.as_posix())
    assert op.resolve_output_base(snapshot) == custom
    assert not custom.exists()


def test_the_base_is_independent_of_the_working_directory(tmp_path, monkeypatch):
    custom = tmp_path / "Fixed"
    snapshot = snapshot_with_base(tmp_path, custom.as_posix())
    first = op.resolve_output_base(snapshot)
    monkeypatch.chdir(tmp_path)
    assert op.resolve_output_base(snapshot) == first


def test_ensure_output_base_creates_and_returns_it(tmp_path):
    base = tmp_path / "Made" / "Here"
    assert op.ensure_output_base(base) == base
    assert base.is_dir()


def test_ensure_output_base_reports_a_file_in_the_way(tmp_path):
    blocked = touch(tmp_path / "blocked")
    with pytest.raises(op.OutputBaseError) as excinfo:
        op.ensure_output_base(blocked)
    assert "could not be created" in excinfo.value.message or "not a folder" in excinfo.value.message
    assert excinfo.value.detail


def test_output_base_errors_carry_technical_detail_separately(tmp_path):
    blocked = touch(tmp_path / "blocked2")
    with pytest.raises(op.OutputBaseError) as excinfo:
        op.ensure_output_base(blocked)
    assert "Traceback" not in excinfo.value.message


# --------------------------------------------------------------------------- #
# B. Stable tool-parent mapping
# --------------------------------------------------------------------------- #


def test_the_tool_parent_mapping_is_exactly_the_approved_six():
    assert dict(op.TOOL_OUTPUT_PARENTS) == {
        "tts": "TTS-Audiobook-Outputs",
        "m4b_converter": "M4B-Converter-Outputs",
        "mp3_tool": "MP3-Tool-Outputs",
        "m4b_maker": "M4B-Maker-Outputs",
        "cover": "Cover-Image-Outputs",
        "m4b_metadata": "M4B-Metadata-Outputs",
    }


def test_the_mapping_covers_every_registered_launcher_tool():
    """The registry must never drift from the launcher's six tools."""
    import launcher

    registered = [spec.key for spec in launcher.TOOLS]
    assert sorted(registered) == sorted(op.TOOL_OUTPUT_PARENTS)
    assert sorted(registered) == sorted(ALL_TOOL_KEYS)


def test_the_registry_reuses_the_existing_slugs_rather_than_redeclaring_them():
    for key, slug in shared_paths.TOOL_SLUGS.items():
        assert op.TOOL_OUTPUT_PARENTS[key] == f"{slug}-Outputs"
        assert op.TOOL_RUN_PREFIXES[key] == slug


def test_the_registry_is_immutable():
    with pytest.raises(TypeError):
        op.TOOL_OUTPUT_PARENTS["tts"] = "Elsewhere"


@pytest.mark.parametrize("bad", ["", "unknown", "../escape", None, "TTS"])
def test_an_unknown_tool_identifier_is_rejected(bad):
    with pytest.raises(op.UnknownToolError):
        op.tool_parent_name(bad)


def test_a_tool_identifier_can_never_become_a_path_fragment(tmp_path):
    with pytest.raises(op.UnknownToolError):
        op.tool_parent_dir(tmp_path, "../../etc")


def test_tool_parent_dir_computes_without_creating(tmp_path):
    directory = op.tool_parent_dir(tmp_path, "cover")
    assert directory == tmp_path / "Cover-Image-Outputs"
    assert not directory.exists()


# --------------------------------------------------------------------------- #
# C. Atomic run-directory reservation
# --------------------------------------------------------------------------- #


def test_a_reservation_creates_the_full_layout(tmp_path):
    snapshot = snapshot_with_base(tmp_path, (tmp_path / "Base").as_posix())
    res = op.reserve_run_directory("m4b_metadata", effective=snapshot)
    assert res.run_directory == tmp_path / "Base" / "M4B-Metadata-Outputs" / "M4B-Metadata-1"
    assert res.run_directory.is_dir()
    assert res.run_number == 1
    assert res.tool_key == "m4b_metadata"
    assert res.config_snapshot is snapshot


def test_a_reservation_creates_no_files(tmp_path):
    snapshot = snapshot_with_base(tmp_path, (tmp_path / "Base").as_posix())
    res = op.reserve_run_directory("tts", effective=snapshot)
    assert list(res.run_directory.iterdir()) == []


def test_an_existing_run_directory_is_skipped_not_reused(tmp_path):
    base = tmp_path / "Base"
    (base / "MP3-Tool-Outputs" / "MP3-Tool-1").mkdir(parents=True)
    marker = touch(base / "MP3-Tool-Outputs" / "MP3-Tool-1" / "keep.txt")
    snapshot = snapshot_with_base(tmp_path, base.as_posix())

    res = op.reserve_run_directory("mp3_tool", effective=snapshot)
    assert res.run_number == 2
    assert marker.exists() and marker.read_bytes() == b"x"


def test_repeated_reservations_take_successive_numbers(tmp_path):
    snapshot = snapshot_with_base(tmp_path, (tmp_path / "Base").as_posix())
    numbers = [op.reserve_run_directory("cover", effective=snapshot).run_number for _ in range(4)]
    assert numbers == [1, 2, 3, 4]


def test_one_run_uses_one_directory_and_a_later_run_gets_another(tmp_path):
    snapshot = snapshot_with_base(tmp_path, (tmp_path / "Base").as_posix())
    first = op.reserve_run_directory("cover", effective=snapshot)
    second = op.reserve_run_directory("cover", effective=snapshot)
    assert first.run_directory != second.run_directory


def test_concurrent_reservations_never_claim_the_same_directory(tmp_path):
    """The atomic mkdir is the correctness boundary, not a prior existence check."""
    snapshot = snapshot_with_base(tmp_path, (tmp_path / "Base").as_posix())
    op.ensure_output_base(tmp_path / "Base")

    results: list[op.RunReservation] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(8)

    def worker():
        try:
            barrier.wait(timeout=10)
            results.append(op.reserve_run_directory("m4b_maker", effective=snapshot))
        except Exception as exc:  # noqa: BLE001 - recorded and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == []
    directories = [r.run_directory for r in results]
    assert len(directories) == 8
    assert len(set(directories)) == 8, "two threads claimed the same run directory"
    assert sorted(r.run_number for r in results) == list(range(1, 9))


def test_reservation_is_bounded_and_fails_with_a_diagnostic(tmp_path):
    base = tmp_path / "Base"
    parent = base / "Cover-Image-Outputs"
    parent.mkdir(parents=True)
    for n in range(1, 4):
        (parent / f"Cover-Image-{n}").mkdir()
    snapshot = snapshot_with_base(tmp_path, base.as_posix())

    with pytest.raises(op.ReservationError) as excinfo:
        op.reserve_run_directory("cover", effective=snapshot, max_attempts=3)
    assert "no free run folder" in excinfo.value.message
    assert "Cover-Image-1" in excinfo.value.detail


def test_reserving_for_an_unknown_tool_fails_before_touching_the_disk(tmp_path):
    base = tmp_path / "Base"
    snapshot = snapshot_with_base(tmp_path, base.as_posix())
    with pytest.raises(op.UnknownToolError):
        op.reserve_run_directory("not_a_tool", effective=snapshot)
    assert not base.exists(), "an invalid key must not create the output base"


def test_an_unwritable_base_fails_before_processing(tmp_path, monkeypatch):
    snapshot = snapshot_with_base(tmp_path, (tmp_path / "Base").as_posix())

    def refuse(*_args, **_kwargs):
        raise PermissionError("access is denied")

    monkeypatch.setattr(Path, "mkdir", refuse)
    with pytest.raises(op.OutputBaseError) as excinfo:
        op.reserve_run_directory("tts", effective=snapshot)
    assert "PermissionError" in excinfo.value.detail


def test_release_if_empty_removes_only_an_empty_run_directory(tmp_path):
    snapshot = snapshot_with_base(tmp_path, (tmp_path / "Base").as_posix())
    res = op.reserve_run_directory("tts", effective=snapshot)
    assert op.release_if_empty(res) is True
    assert not res.run_directory.exists()


def test_release_if_empty_never_removes_a_directory_with_content(tmp_path):
    snapshot = snapshot_with_base(tmp_path, (tmp_path / "Base").as_posix())
    res = op.reserve_run_directory("tts", effective=snapshot)
    kept = touch(res.run_directory / "produced.mp3")
    assert op.release_if_empty(res) is False
    assert res.run_directory.is_dir() and kept.exists()


def test_a_reservation_is_immutable(tmp_path):
    snapshot = snapshot_with_base(tmp_path, (tmp_path / "Base").as_posix())
    res = op.reserve_run_directory("tts", effective=snapshot)
    with pytest.raises(Exception):
        res.run_directory = tmp_path / "elsewhere"


def test_a_reservation_carries_its_configuration_snapshot(tmp_path):
    """A preference changed mid-run cannot move an operation already going."""
    snapshot = snapshot_with_base(tmp_path, (tmp_path / "Base").as_posix())
    res = op.reserve_run_directory("tts", effective=snapshot)
    assert res.config_snapshot.output.base_directory == tmp_path / "Base"
    assert res.base_directory == tmp_path / "Base"


# --------------------------------------------------------------------------- #
# D. Filename sanitisation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("ch", list('<>:"/\\|?*'))
def test_forbidden_windows_characters_are_replaced(ch):
    result = op.sanitize_component(f"Book{ch}One.m4b")
    assert ch not in result
    assert result.endswith(".m4b")


def test_control_characters_are_removed():
    assert op.sanitize_component("Bo\x00ok\x1f.m4b") == "Book.m4b"


@pytest.mark.parametrize("raw", ["Book.m4b   ", "Book.m4b...", "Book.m4b . . "])
def test_trailing_spaces_and_periods_are_stripped(raw):
    """Windows drops them on write, which would silently merge two names."""
    assert op.sanitize_component(raw) == "Book.m4b"


@pytest.mark.parametrize("raw", ["", "   ", None, ".", "..", "///"])
def test_blank_and_dot_names_become_the_fallback(raw):
    assert op.sanitize_component(raw) == op.FALLBACK_COMPONENT


@pytest.mark.parametrize("name", ["CON", "con", "PRN", "AUX", "NUL", "COM1", "LPT9"])
def test_reserved_device_names_are_defused(name):
    assert op.sanitize_component(name) == f"_{name}"


@pytest.mark.parametrize("name", ["CON.txt", "com4.mp3", "NUL.m4b"])
def test_reserved_device_names_with_extensions_are_defused(name):
    result = op.sanitize_component(name)
    assert result.startswith("_")
    assert result.endswith(Path(name).suffix)


@pytest.mark.parametrize(
    "raw", ["../../etc/passwd", "..\\..\\Windows\\system32", "C:/Windows/notepad.exe"]
)
def test_a_whole_path_is_reduced_to_its_last_component(raw):
    result = op.sanitize_component(raw)
    assert "/" not in result and "\\" not in result
    assert ".." not in result


def test_the_length_limit_truncates_the_stem_and_keeps_the_extension():
    long_name = "x" * 400 + ".m4b"
    result = op.sanitize_component(long_name)
    assert len(result) == op.MAX_COMPONENT_LENGTH
    assert result.endswith(".m4b")


def test_a_short_name_is_never_padded_or_altered():
    assert op.sanitize_component("Book One.m4b") == "Book One.m4b"


@pytest.mark.parametrize(
    "raw", ["Böök – Ⅻ.m4b", "日本語の本.mp3", "Крига.m4b", "Book’s Tale.m4b"]
)
def test_unicode_names_survive_intact(raw):
    result = op.sanitize_component(raw)
    assert result == raw
    assert result


def test_unicode_is_normalised_to_nfc():
    decomposed = "Bo" + "o" + "\u0308" + "k.m4b"      # o + combining diaeresis
    composed = "Bo\u00f6k.m4b"
    assert op.sanitize_component(decomposed) == composed


def test_names_with_spaces_and_apostrophes_are_kept():
    assert op.sanitize_component("The Hunter's Moon - Part 2.m4b") == (
        "The Hunter's Moon - Part 2.m4b"
    )


def test_sanitisation_is_deterministic():
    raw = 'a<b>c:"d/e\\f|g?h*i.m4b'
    assert op.sanitize_component(raw) == op.sanitize_component(raw)


def test_the_final_suffix_only_is_treated_as_the_extension():
    """Dotted book titles are far commoner than multi-part extensions."""
    assert op.split_suffix("Book 1.5 - Extras.m4b") == ("Book 1.5 - Extras", ".m4b")
    assert op.numbered_variant("Book 1.5 - Extras.m4b", 1) == "Book 1.5 - Extras-1.m4b"
    # A genuine multi-part extension keeps its final part, losing nothing.
    assert op.numbered_variant("archive.tar.gz", 1) == "archive.tar-1.gz"


def test_a_name_with_no_extension_is_numbered_cleanly():
    assert op.numbered_variant("Book", 3) == "Book-3"


def test_sanitize_relative_rejects_absolute_and_traversal():
    for bad in ("/etc", "C:/Windows", "../up", "a/../../b"):
        with pytest.raises(op.UnsafePathError):
            op.sanitize_relative(bad)


def test_sanitize_relative_cleans_every_component():
    result = op.sanitize_relative("Series A/CON/Bad<Name>")
    assert result.parts == ("Series A", "_CON", "Bad_Name_")


# --------------------------------------------------------------------------- #
# E/F. Collision numbering and planned-batch tracking
# --------------------------------------------------------------------------- #


def test_the_requested_name_is_used_when_it_is_free(tmp_path):
    planner = op.DestinationPlanner(tmp_path)
    assert planner.plan("Book.m4b") == tmp_path / "Book.m4b"


def test_an_existing_file_forces_the_numbered_variant(tmp_path):
    touch(tmp_path / "Book.m4b")
    planner = op.DestinationPlanner(tmp_path)
    assert planner.plan("Book.m4b") == tmp_path / "Book-1.m4b"


def test_an_existing_directory_also_forces_a_variant(tmp_path):
    (tmp_path / "Book.m4b").mkdir()
    planner = op.DestinationPlanner(tmp_path)
    assert planner.plan("Book.m4b") == tmp_path / "Book-1.m4b"


def test_planned_but_not_yet_created_names_collide(tmp_path):
    planner = op.DestinationPlanner(tmp_path)
    first = planner.plan("Book.m4b")
    second = planner.plan("Book.m4b")
    third = planner.plan("Book.m4b")
    assert [p.name for p in (first, second, third)] == ["Book.m4b", "Book-1.m4b", "Book-2.m4b"]
    assert not any(p.exists() for p in (first, second, third))


def test_existing_files_and_planned_names_are_combined(tmp_path):
    touch(tmp_path / "Book.m4b")
    touch(tmp_path / "Book-1.m4b")
    planner = op.DestinationPlanner(tmp_path)
    assert planner.plan("Book.m4b").name == "Book-2.m4b"
    assert planner.plan("Book.m4b").name == "Book-3.m4b"


def test_a_name_that_already_looks_numbered_is_not_special_cased(tmp_path):
    touch(tmp_path / "Book-1.m4b")
    planner = op.DestinationPlanner(tmp_path)
    assert planner.plan("Book-1.m4b").name == "Book-1-1.m4b"


def test_collisions_introduced_by_sanitisation_are_resolved(tmp_path):
    """Two different raw names can sanitise to one; that is still a collision."""
    planner = op.DestinationPlanner(tmp_path)
    first = planner.plan("Book<One>.m4b")
    second = planner.plan("Book|One|.m4b")
    assert first.name == "Book_One_.m4b"
    assert second.name == "Book_One_-1.m4b"


def test_case_only_collisions_are_treated_as_collisions(tmp_path):
    """Safer on every platform, and identical on the two we ship to."""
    planner = op.DestinationPlanner(tmp_path)
    assert planner.plan("Book.m4b").name == "Book.m4b"
    assert planner.plan("BOOK.M4B").name == "BOOK-1.M4B"


def test_separate_batches_have_independent_trackers(tmp_path):
    first = op.DestinationPlanner(tmp_path / "a", check_filesystem=False)
    second = op.DestinationPlanner(tmp_path / "b", check_filesystem=False)
    assert first.plan("Book.m4b").name == "Book.m4b"
    assert second.plan("Book.m4b").name == "Book.m4b", "trackers must not share state"


def test_there_is_no_global_tracker_shared_between_operations(tmp_path):
    for _ in range(3):
        planner = op.DestinationPlanner(tmp_path, check_filesystem=False)
        assert planner.plan("Book.m4b").name == "Book.m4b"


def test_collision_planning_is_deterministic_for_a_given_order(tmp_path):
    def run():
        planner = op.DestinationPlanner(tmp_path, check_filesystem=False)
        return [planner.plan(n).name for n in ("A.m4b", "A.m4b", "B.m4b", "A.m4b")]

    assert run() == run() == ["A.m4b", "A-1.m4b", "B.m4b", "A-2.m4b"]


def test_planning_creates_nothing_on_disk(tmp_path):
    planner = op.DestinationPlanner(tmp_path)
    for _ in range(5):
        planner.plan("Book.m4b")
    assert list(tmp_path.iterdir()) == []


def test_the_collision_search_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(op, "MAX_COLLISION_ATTEMPTS", 3)
    planner = op.DestinationPlanner(tmp_path, check_filesystem=False)
    for _ in range(4):
        planner.plan("Book.m4b")
    with pytest.raises(op.ReservationError) as excinfo:
        planner.plan("Book.m4b")
    assert "no free name" in excinfo.value.message


def test_a_planner_plans_into_a_subdirectory(tmp_path):
    planner = op.DestinationPlanner(tmp_path)
    assert planner.plan("ch1.mp3", subdir="Series A") == tmp_path / "Series A" / "ch1.mp3"
    assert not (tmp_path / "Series A").exists()


def test_a_planner_refuses_a_traversing_subdirectory(tmp_path):
    planner = op.DestinationPlanner(tmp_path)
    with pytest.raises(op.UnsafePathError):
        planner.plan("ch1.mp3", subdir="../escape")


# --------------------------------------------------------------------------- #
# G. Input protection and containment
# --------------------------------------------------------------------------- #


def test_a_destination_equal_to_an_input_is_rejected(tmp_path):
    source = touch(tmp_path / "in" / "Book.m4b")
    with pytest.raises(op.UnsafePathError) as excinfo:
        op.assert_not_input(source, [source])
    assert "overwrite one of the files being read" in excinfo.value.message


def test_input_equality_is_compared_after_normalisation(tmp_path):
    source = touch(tmp_path / "in" / "Book.m4b")
    awkward = tmp_path / "in" / ".." / "in" / "Book.m4b"
    with pytest.raises(op.UnsafePathError):
        op.assert_not_input(awkward, [source])


def test_a_distinct_destination_passes_input_protection(tmp_path):
    source = touch(tmp_path / "in" / "Book.m4b")
    op.assert_not_input(tmp_path / "out" / "Book.m4b", [source])


def test_a_destination_inside_a_source_tree_is_rejected(tmp_path):
    source_root = tmp_path / "Library"
    source_root.mkdir()
    with pytest.raises(op.UnsafePathError) as excinfo:
        op.assert_outside_source_trees(source_root / "Series" / "out.mp3", [source_root])
    assert "inside the folder it is reading from" in excinfo.value.message


def test_a_destination_beside_a_source_tree_is_allowed(tmp_path):
    source_root = tmp_path / "Library"
    source_root.mkdir()
    op.assert_outside_source_trees(tmp_path / "Outputs" / "out.mp3", [source_root])


def test_a_contained_destination_is_accepted(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    assert op.assert_contained(root, root / "sub" / "file.mp3")


def test_a_destination_outside_the_root_is_rejected(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    with pytest.raises(op.UnsafePathError) as excinfo:
        op.assert_contained(root, tmp_path / "elsewhere" / "file.mp3")
    assert "outside the chosen output folder" in excinfo.value.message


def test_a_traversal_escape_is_rejected(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    with pytest.raises(op.UnsafePathError):
        op.assert_contained(root, root / ".." / ".." / "escaped.mp3")


def test_an_absolute_child_injection_is_rejected(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    injected = Path(tmp_path / "other" / "abs.mp3")
    with pytest.raises(op.UnsafePathError):
        op.assert_contained(root, injected)


def test_the_root_itself_is_not_a_valid_destination(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    with pytest.raises(op.UnsafePathError):
        op.assert_contained(root, root)


def test_a_non_existent_child_is_checked_rather_than_assumed_safe(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    deep = root / "a" / "b" / "c" / "never-created.mp3"
    assert not deep.exists()
    assert op.assert_contained(root, deep)
    with pytest.raises(op.UnsafePathError):
        op.assert_contained(root, root / "a" / ".." / ".." / "outside.mp3")


def test_containment_is_independent_of_the_working_directory(tmp_path, monkeypatch):
    root = tmp_path / "run"
    root.mkdir()
    first = op.assert_contained(root, root / "f.mp3")
    monkeypatch.chdir(tmp_path)
    assert op.assert_contained(root, root / "f.mp3") == first


def test_a_linked_output_root_is_refused(tmp_path, dir_link_support):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    assert dir_link_support(link, real) == ""
    with pytest.raises(op.UnsafePathError) as excinfo:
        op.ensure_output_base(link)
    assert "link" in excinfo.value.message


def test_a_link_escaping_the_output_root_is_rejected(tmp_path, dir_link_support):
    """A junction pointing outside is caught by containment: resolve() follows
    it, so the destination normalises outside the root."""
    root = tmp_path / "run"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    assert dir_link_support(root / "sub", outside) == ""
    with pytest.raises(op.UnsafePathError) as excinfo:
        op.assert_contained(root, root / "sub" / "file.mp3")
    assert "outside the chosen output folder" in excinfo.value.message


def test_a_link_pointing_back_inside_the_root_is_still_not_followed(tmp_path,
                                                                    dir_link_support):
    """The case containment alone cannot catch.

    The junction's target is *inside* the run directory, so the resolved path
    is contained and the containment check passes — but a destination is still
    never established through a link, so ``assert_no_link_in`` refuses it.
    """
    root = tmp_path / "run"
    root.mkdir()
    real = root / "real"
    real.mkdir()
    assert dir_link_support(root / "alias", real) == ""

    # Containment alone is satisfied: the link resolves inside the root.
    assert op._normalise(root / "alias").is_relative_to(op._normalise(root))
    with pytest.raises(op.UnsafePathError) as excinfo:
        op.assert_contained(root, root / "alias" / "file.mp3")
    assert "link" in excinfo.value.message


def test_a_planner_refuses_to_plan_through_a_link(tmp_path, dir_link_support):
    root = tmp_path / "run"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    assert dir_link_support(root / "sub", outside) == ""
    planner = op.DestinationPlanner(root)
    with pytest.raises(op.UnsafePathError):
        planner.plan("file.mp3", subdir="sub")


def test_a_linked_destination_name_is_refused(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    target = touch(tmp_path / "target.mp3")
    reason = make_file_link(root / "file.mp3", target)
    if reason:
        pytest.skip(f"this environment cannot create a file symlink — {reason}")
    with pytest.raises(op.UnsafePathError):
        op.assert_contained(root, root / "file.mp3")


def test_link_detection_reports_false_for_a_plain_directory(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert op._is_link(plain) is False
    assert op._is_link(tmp_path / "missing") is False


def test_no_safety_check_deletes_anything(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    kept = touch(root / "existing.mp3")
    for call in (
        lambda: op.assert_contained(root, root / "x.mp3"),
        lambda: op.assert_not_input(root / "x.mp3", [kept]),
        lambda: op.assert_outside_source_trees(root / "x.mp3", [tmp_path / "src"]),
    ):
        call()
    assert kept.exists() and kept.read_bytes() == b"x"


# --------------------------------------------------------------------------- #
# H. Pure planning — flat, one root, multiple roots
# --------------------------------------------------------------------------- #


def test_flat_planning_puts_everything_in_the_run_directory(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    sources = [
        touch(tmp_path / "a" / "One.m4b"),
        touch(tmp_path / "b" / "deep" / "Two.m4b"),
    ]
    plan = op.plan_flat(run, sources)
    assert [p.destination for p in plan.items] == [run / "One.m4b", run / "Two.m4b"]
    assert all(item.destination.parent == run for item in plan.items)


def test_flat_planning_numbers_same_named_files_from_different_folders(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    sources = [
        touch(tmp_path / "a" / "Book.m4b"),
        touch(tmp_path / "b" / "Book.m4b"),
        touch(tmp_path / "c" / "Book.m4b"),
    ]
    plan = op.plan_flat(run, sources)
    assert [i.destination.name for i in plan.items] == ["Book.m4b", "Book-1.m4b", "Book-2.m4b"]


def test_flat_planning_does_not_recreate_parent_trees(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    source = touch(tmp_path / "deep" / "nested" / "tree" / "Book.m4b")
    plan = op.plan_flat(run, [source])
    assert plan.items[0].relative == PurePath("Book.m4b")


def test_flat_planning_supports_a_rename_hook(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    source = touch(tmp_path / "in" / "Book.m4b")
    plan = op.plan_flat(run, [source], rename=lambda p: p.stem + ".mp3")
    assert plan.items[0].destination.name == "Book.mp3"


def test_one_root_mirroring_preserves_the_relative_parent(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    root = tmp_path / "Library"
    sources = [
        touch(root / "Series A" / "ch1.mp3"),
        touch(root / "Series B" / "ch1.mp3"),
        touch(root / "loose.mp3"),
    ]
    plan = op.plan_mirrored(run, sources, root)
    assert [str(i.relative).replace("\\", "/") for i in plan.items] == [
        "Series A/ch1.mp3",
        "Series B/ch1.mp3",
        "loose.mp3",
    ]


def test_one_root_mirroring_keeps_same_stem_files_apart(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    root = tmp_path / "Library"
    sources = [touch(root / "A" / "ch1.mp3"), touch(root / "B" / "ch1.mp3")]
    plan = op.plan_mirrored(run, sources, root)
    assert len({i.destination for i in plan.items}) == 2
    assert all(i.destination.name == "ch1.mp3" for i in plan.items)


def test_a_source_outside_its_declared_root_is_rejected(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    root = tmp_path / "Library"
    root.mkdir()
    stray = touch(tmp_path / "Elsewhere" / "ch1.mp3")
    with pytest.raises(op.UnsafePathError) as excinfo:
        op.plan_mirrored(run, [stray], root)
    assert "not inside the folder it was imported from" in excinfo.value.message


def test_mirrored_components_are_sanitised(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    root = tmp_path / "Library"
    source = touch(root / "CON" / "ch1.mp3")
    plan = op.plan_mirrored(run, [source], root)
    assert plan.items[0].relative.parts == ("_CON", "ch1.mp3")


def test_multi_root_planning_gives_each_root_a_container(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    first, second = tmp_path / "Alpha", tmp_path / "Beta"
    grouped = [
        (first, [touch(first / "x" / "ch1.mp3")]),
        (second, [touch(second / "x" / "ch1.mp3")]),
    ]
    plan = op.plan_multi_root(run, grouped)
    assert [str(i.relative).replace("\\", "/") for i in plan.items] == [
        "Alpha/x/ch1.mp3",
        "Beta/x/ch1.mp3",
    ]


def test_multi_root_planning_disambiguates_duplicate_root_labels(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    first = tmp_path / "one" / "Books"
    second = tmp_path / "two" / "Books"
    grouped = [
        (first, [touch(first / "ch1.mp3")]),
        (second, [touch(second / "ch1.mp3")]),
    ]
    plan = op.plan_multi_root(run, grouped)
    labels = [i.relative.parts[0] for i in plan.items]
    assert labels == ["Books", "Books-1"], "one root's tree must never merge into another's"


def test_multi_root_labels_are_sanitised(tmp_path):
    """Planning is pure, so the root need not exist — which is just as well:
    Windows will not let a directory called ``NUL`` be created at all."""
    run = tmp_path / "run"
    run.mkdir()
    root = tmp_path / "NUL"
    plan = op.plan_multi_root(run, [(root, [root / "ch1.mp3"])])
    assert plan.items[0].relative.parts[0] == "_NUL"
    # (No exists() assertion: on Windows a path ending in NUL reports as
    # existing because the OS resolves the device name — which is precisely
    # the hazard the sanitiser defuses.)


def test_multi_root_labels_with_forbidden_characters_are_sanitised(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    root = tmp_path / "Books|One"
    plan = op.plan_multi_root(run, [(root, [root / "ch1.mp3"])])
    assert plan.items[0].relative.parts[0] == "Books_One"


def test_planning_never_creates_a_directory_or_file(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    root = tmp_path / "Library"
    sources = [touch(root / "A" / "ch1.mp3"), touch(root / "B" / "ch1.mp3")]
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

    op.plan_flat(run, sources)
    op.plan_mirrored(run, sources, root)
    op.plan_multi_root(run, [(root, sources)])

    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert after == before, "planning must not touch the filesystem"


def test_planning_never_modifies_an_input(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    root = tmp_path / "Library"
    source = touch(root / "A" / "ch1.mp3", b"original bytes")
    op.plan_mirrored(run, [source], root)
    assert source.read_bytes() == b"original bytes"


def test_plans_are_deterministic(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    root = tmp_path / "Library"
    sources = [touch(root / "A" / "ch1.mp3"), touch(root / "B" / "ch1.mp3")]

    def names():
        return [str(i.relative) for i in op.plan_mirrored(run, sources, root).items]

    assert names() == names()


def test_a_plan_is_immutable(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    plan = op.plan_flat(run, [touch(tmp_path / "in" / "a.mp3")])
    with pytest.raises(Exception):
        plan.items = ()
    with pytest.raises(Exception):
        plan.items[0].destination = run / "other.mp3"
    assert isinstance(plan.items, tuple)


def test_a_plan_reports_the_directories_a_caller_would_need(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    root = tmp_path / "Library"
    sources = [touch(root / "A" / "ch1.mp3"), touch(root / "A" / "ch2.mp3"),
               touch(root / "B" / "ch1.mp3")]
    plan = op.plan_mirrored(run, sources, root)
    assert plan.directories() == (run / "A", run / "B")
    assert not (run / "A").exists()


def test_no_planned_destination_escapes_its_root(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    root = tmp_path / "Library"
    sources = [touch(root / "A" / "ch1.mp3"), touch(root / "B" / "ch1.mp3")]
    for plan in (
        op.plan_flat(run, sources),
        op.plan_mirrored(run, sources, root),
        op.plan_multi_root(run, [(root, sources)]),
    ):
        for item in plan.items:
            assert op.assert_contained(run, item.destination)


def test_a_reservation_hands_out_a_scoped_planner(tmp_path):
    snapshot = snapshot_with_base(tmp_path, (tmp_path / "Base").as_posix())
    res = op.reserve_run_directory("tts", effective=snapshot)
    planner = res.planner()
    assert planner.plan("Book.mp3").parent == res.run_directory


# --------------------------------------------------------------------------- #
# I/K. Scope guards
# --------------------------------------------------------------------------- #


def test_the_module_imports_no_tk_subprocess_or_network():
    import ast

    tree = ast.parse(Path(op.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    for forbidden in ("tkinter", "subprocess", "socket", "urllib", "requests", "shutil"):
        assert not any(forbidden in name for name in imported), forbidden


def test_no_tool_panel_consumes_the_new_service_yet():
    """Phase 4 migrates the tools; Phase 3 only builds the foundation."""
    tool_modules = [
        "mp3_tools/cover_resizer.py", "mp3_tools/m4b_converter.py",
        "mp3_tools/m4b_maker.py", "mp3_tools/m4b_metadata_editor.py",
        "mp3_tools/mp3_tool.py", "tts/epub2tts_gui.py",
    ]
    for relative in tool_modules:
        source = (REPO_ROOT / "scripts" / "Universal" / relative).read_text(encoding="utf-8")
        assert "output_paths" not in source, relative
        assert "reserve_run_directory" not in source, relative


def test_the_launcher_does_not_consume_the_new_service():
    source = (REPO_ROOT / "scripts" / "Universal" / "launcher.py").read_text(encoding="utf-8")
    assert "output_paths" not in source


def test_the_legacy_wrapper_is_still_in_place_and_marked_for_removal():
    """Phase 3 must not change current tool-output behaviour."""
    source = (REPO_ROOT / "scripts" / "Universal" / "shared" / "paths.py").read_text(
        encoding="utf-8"
    )
    assert "def next_output_dir" in source
    assert "scheduled for removal in Phase 4" in source


def test_exactly_the_known_legacy_call_sites_remain(tmp_path):
    """Pins the migration: a sixth caller fails, and Phase 4 removals show up."""
    expected = {
        "mp3_tools/m4b_converter.py", "mp3_tools/m4b_maker.py",
        "mp3_tools/m4b_metadata_editor.py", "mp3_tools/mp3_tool.py",
        "tts/epub2tts_gui.py",
    }
    found = set()
    for path in (REPO_ROOT / "scripts" / "Universal").rglob("*.py"):
        if path.name == "paths.py":
            continue
        if "next_output_dir(" in path.read_text(encoding="utf-8"):
            found.add(path.relative_to(REPO_ROOT / "scripts" / "Universal").as_posix())
    assert found == expected


def test_no_cleanup_or_post_exit_behaviour_exists_anywhere():
    import ast

    for relative in ("shared/output_paths.py", "shared/preferences_ui.py", "launcher.py"):
        source = (REPO_ROOT / "scripts" / "Universal" / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert "rmtree" not in called, relative
        for word in ("Clear Downloaded Data" if relative != "shared/preferences_ui.py" else "",):
            if word:
                assert word not in source, relative


def test_the_cleanup_placeholder_is_still_disabled_and_inert():
    from shared import preferences_ui

    source = Path(preferences_ui.__file__).read_text(encoding="utf-8")
    assert 'state="disabled"' in source
    assert "CLEANUP_PLACEHOLDER_TEXT" in source
    assert "command=self.clear" not in source


def test_no_cover_source_side_or_maker_custom_destination_exists():
    for relative in ("mp3_tools/cover_resizer.py", "mp3_tools/m4b_maker.py"):
        source = (REPO_ROOT / "scripts" / "Universal" / relative).read_text(encoding="utf-8")
        assert "Save beside source images" not in source
        assert "Choose custom destination" not in source


def test_no_plan_three_importing_behaviour_arrived():
    source = Path(op.__file__).read_text(encoding="utf-8")
    for plan_three in ("Cancel Import", "Include subfolders", "def scan_", "rglob("):
        assert plan_three not in source


def test_the_version_is_unchanged():
    from shared.version import VERSION

    assert VERSION == "0.5.1"


def test_no_test_here_resolves_the_real_downloads_folder(tmp_path):
    """The suite must never plan into the maintainer's actual Downloads."""
    snapshot = snapshot_with_base(tmp_path)
    base = op.resolve_output_base(snapshot)
    assert str(tmp_path) in str(base)
    assert base != shared_paths.downloads_dir() / "Audiobook-Creation-Tool-Outputs"
