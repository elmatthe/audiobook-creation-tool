"""The shared M4B staging/publication pattern — v0.6.4 Phase 11 hardening.

``mp3_tools/m4b_staging.py`` was extracted at Phase 9 from the Maker engine so
both M4B tools run one copy of the private-staging → atomic-publication
pattern. Phase 9 proved it through the two engines; this suite is its own
contract, exercised directly and through both engines' delegation:

- staging is exactly ``<work root>/<stem>`` and the staged file directly
  inside it — anything else is refused before it is touched;
- discard removes the staging directory's own entries and nothing outside it,
  a link inside it (symlink **or** Windows junction) is removed as a link and
  never followed;
- publication refuses an already-present destination or a link, moves with
  ``os.replace`` and takes the plan-owned temporary-sibling route on another
  filesystem, so the final name never holds a partial file;
- the work root is pruned with ``rmdir`` only, and only when empty.
"""

from __future__ import annotations

import ast
import errno
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from shared import output_paths
from mp3_tools import m4b_maker_processing, m4b_metadata_processing, m4b_staging
from mp3_tools.m4b_staging import StagingError

from test_output_paths import make_dir_link, make_file_link

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
MODULE = UNIVERSAL / "mp3_tools" / "m4b_staging.py"


@dataclass(frozen=True)
class Planned:
    """The duck-typed staged output the pattern accepts: any frozen plan value."""

    book_id: str
    filename: str
    staging_dir: Path
    staged: Path
    published: Path


@pytest.fixture
def layout(tmp_path: Path):
    run = tmp_path / "Outputs" / "Tool-1"
    run.mkdir(parents=True)
    work = run / ".work"
    plan = Planned("book-1", "Book.m4b", work / "Book", work / "Book" / "Book.m4b",
                   run / "Book.m4b")
    return run, work, plan


def listing(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")} if root.exists() else set()


# --------------------------------------------------------------------------- #
# Ownership and preparation
# --------------------------------------------------------------------------- #


def test_prepare_is_idempotent_and_creates_nothing_visible(layout):
    run, work, plan = layout
    assert m4b_staging.prepare_staging(plan, work_root=work) == plan.staging_dir
    assert m4b_staging.prepare_staging(plan, work_root=work) == plan.staging_dir
    assert plan.staging_dir.is_dir()
    assert [p.name for p in run.iterdir()] == [".work"], "nothing visible in the run"


def test_a_staging_directory_not_directly_under_the_work_root_is_refused(layout, tmp_path):
    run, work, _plan = layout
    elsewhere = Planned("b", "X.m4b", tmp_path / "elsewhere" / "X", tmp_path / "elsewhere" / "X" / "X.m4b",
                        run / "X.m4b")
    nested = Planned("b", "X.m4b", work / "deep" / "X", work / "deep" / "X" / "X.m4b", run / "X.m4b")
    astray = Planned("b", "X.m4b", work / "X", work / "other" / "X.m4b", run / "X.m4b")
    for wrong in (elsewhere, nested, astray):
        with pytest.raises(StagingError) as refused:
            m4b_staging.prepare_staging(wrong, work_root=work)
        assert refused.value.stage == "staging"
        with pytest.raises(StagingError):
            m4b_staging.discard_staging(wrong, work_root=work)
        with pytest.raises(StagingError):
            m4b_staging.publish_staged(wrong, work_root=work)
    assert not work.exists(), "a refusal creates nothing"


# --------------------------------------------------------------------------- #
# Discard: bounded, link-safe
# --------------------------------------------------------------------------- #


def test_discard_removes_the_staging_tree_and_nothing_beside_it(layout):
    run, work, plan = layout
    m4b_staging.prepare_staging(plan, work_root=work)
    (plan.staging_dir / "wav").mkdir()
    (plan.staging_dir / "wav" / "01.wav").write_bytes(b"w")
    (plan.staging_dir / "list.txt").write_bytes(b"l")
    plan.staged.write_bytes(b"m4b")
    neighbour = work / "Other"
    neighbour.mkdir()
    (neighbour / "Other.m4b").write_bytes(b"theirs")
    (run / "Published.m4b").write_bytes(b"visible")
    removed = m4b_staging.discard_staging(plan, work_root=work)
    assert removed == 5, "wav/01.wav, wav, list.txt, Book.m4b, the directory itself"
    assert not plan.staging_dir.exists()
    assert (neighbour / "Other.m4b").read_bytes() == b"theirs"
    assert (run / "Published.m4b").read_bytes() == b"visible"
    assert m4b_staging.discard_staging(plan, work_root=work) == 0, "idempotent"


def test_a_directory_link_planted_inside_staging_is_removed_as_a_link_and_never_followed(
        layout, tmp_path):
    """A junction on an ordinary Windows account, a symlink elsewhere: the
    target's files survive and the link itself is gone."""
    run, work, plan = layout
    m4b_staging.prepare_staging(plan, work_root=work)
    plan.staged.write_bytes(b"m4b")
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_bytes(b"keep me")
    link = plan.staging_dir / "escape"
    reason = make_dir_link(link, victim)
    if reason:
        pytest.skip(f"this environment cannot create a directory link: {reason}")
    m4b_staging.discard_staging(plan, work_root=work)
    assert (victim / "precious.txt").read_bytes() == b"keep me", "the link was followed"
    assert not link.exists() and not plan.staging_dir.exists()


def test_a_file_link_planted_inside_staging_is_unlinked_and_its_target_kept(layout, tmp_path):
    run, work, plan = layout
    m4b_staging.prepare_staging(plan, work_root=work)
    victim = tmp_path / "victim.bin"
    victim.write_bytes(b"keep me")
    link = plan.staging_dir / "escape.bin"
    reason = make_file_link(link, victim)
    if reason:
        pytest.skip(f"this environment cannot create a file symlink: {reason}")
    m4b_staging.discard_staging(plan, work_root=work)
    assert victim.read_bytes() == b"keep me"
    assert not link.exists() and not plan.staging_dir.exists()


def test_a_staging_directory_that_is_itself_a_link_is_refused_untouched(layout, tmp_path):
    run, work, plan = layout
    work.mkdir()
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_bytes(b"keep me")
    reason = make_dir_link(plan.staging_dir, victim)
    if reason:
        pytest.skip(f"this environment cannot create a directory link: {reason}")
    with pytest.raises(StagingError):
        m4b_staging.discard_staging(plan, work_root=work)
    assert (victim / "precious.txt").read_bytes() == b"keep me"
    with pytest.raises((StagingError, output_paths.OutputPathError)):
        m4b_staging.prepare_staging(plan, work_root=work)


# --------------------------------------------------------------------------- #
# Publication: refuse, replace atomically, cross-device route
# --------------------------------------------------------------------------- #


def test_publication_refuses_an_unstaged_book_and_an_existing_destination(layout):
    run, work, plan = layout
    with pytest.raises(StagingError) as refused:
        m4b_staging.publish_staged(plan, work_root=work)
    assert refused.value.stage == "publish"
    m4b_staging.prepare_staging(plan, work_root=work)
    plan.staged.write_bytes(b"candidate")
    plan.published.write_bytes(b"someone else's")
    with pytest.raises(StagingError):
        m4b_staging.publish_staged(plan, work_root=work)
    assert plan.published.read_bytes() == b"someone else's"
    assert plan.staged.read_bytes() == b"candidate", "the candidate is retained"


def test_publication_refuses_a_destination_that_is_a_link(layout, tmp_path):
    run, work, plan = layout
    m4b_staging.prepare_staging(plan, work_root=work)
    plan.staged.write_bytes(b"candidate")
    victim = tmp_path / "victim.m4b"
    victim.write_bytes(b"keep me")
    reason = make_file_link(plan.published, victim)
    if reason:
        pytest.skip(f"this environment cannot create a file symlink: {reason}")
    with pytest.raises(StagingError):
        m4b_staging.publish_staged(plan, work_root=work)
    assert victim.read_bytes() == b"keep me"
    assert plan.staged.read_bytes() == b"candidate"


def test_publication_moves_the_candidate_whole_and_leaves_no_staging_file(layout):
    run, work, plan = layout
    m4b_staging.prepare_staging(plan, work_root=work)
    plan.staged.write_bytes(b"candidate" * 100)
    assert m4b_staging.publish_staged(plan, work_root=work) == plan.published
    assert plan.published.read_bytes() == b"candidate" * 100
    assert not plan.staged.exists()


def test_a_cross_device_work_root_takes_the_temporary_sibling_route(layout, monkeypatch):
    run, work, plan = layout
    m4b_staging.prepare_staging(plan, work_root=work)
    plan.staged.write_bytes(b"candidate")
    real_replace = os.replace
    seen: list[tuple[Path, Path]] = []

    def cross_device(src, dst, *a, **k):
        seen.append((Path(src), Path(dst)))
        if Path(src) == plan.staged:
            raise OSError(errno.EXDEV, "cross-device link")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", cross_device)
    assert m4b_staging.publish_staged(plan, work_root=work) == plan.published
    assert plan.published.read_bytes() == b"candidate"
    assert not plan.staged.exists()
    # The second replace came from a plan-owned sibling inside the destination folder.
    assert len(seen) == 2 and seen[1][0].parent == plan.published.parent
    assert seen[1][0].name.startswith(output_paths.TEMP_SIBLING_PREFIX)
    assert sorted(p.name for p in run.iterdir()) == [".work", "Book.m4b"], "no sibling left"


def test_a_failure_on_the_cross_device_route_leaves_no_partial_destination(layout, monkeypatch):
    run, work, plan = layout
    m4b_staging.prepare_staging(plan, work_root=work)
    plan.staged.write_bytes(b"candidate")

    def refuse(src, dst, *a, **k):
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(StagingError) as failed:
        m4b_staging.publish_staged(plan, work_root=work)
    assert failed.value.stage == "publish"
    assert not plan.published.exists()
    assert plan.staged.read_bytes() == b"candidate", "the candidate is retained"
    assert sorted(p.name for p in run.iterdir()) == [".work"], "no temporary sibling left"


# --------------------------------------------------------------------------- #
# Pruning
# --------------------------------------------------------------------------- #


def test_the_work_root_is_pruned_only_when_empty_and_never_through_a_link(layout, tmp_path):
    run, work, plan = layout
    m4b_staging.prepare_staging(plan, work_root=work)
    plan.staged.write_bytes(b"x")
    m4b_staging.prune_work_root(work)
    assert work.exists(), "not empty: kept"
    m4b_staging.discard_staging(plan, work_root=work)
    m4b_staging.prune_work_root(work)
    assert not work.exists()
    m4b_staging.prune_work_root(work)          # missing: a no-op
    victim = tmp_path / "victim"
    victim.mkdir()
    linked = run / "linked-work"
    if not make_dir_link(linked, victim):
        m4b_staging.prune_work_root(linked)
        assert victim.exists() and linked.exists(), "a linked work root is left alone"


# --------------------------------------------------------------------------- #
# Both engines delegate; the pattern stays pure
# --------------------------------------------------------------------------- #


def test_both_engines_delegate_their_staging_lifecycle_to_the_shared_pattern():
    for module in (m4b_maker_processing, m4b_metadata_processing):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        bodies = {node.name: ast.unparse(node) for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef)}
        assert "m4b_staging.prepare_staging" in bodies["prepare_staging"]
        assert "m4b_staging.discard_staging" in bodies["discard_staging"]
        assert "m4b_staging.publish_staged" in bodies["publish_book"]
        assert "m4b_staging.require_owned" in bodies["_require_owned"]
        assert "m4b_staging.prune_work_root" in bodies["_discard_quietly"]
        calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        for own in ("shutil.rmtree", "os.walk", "os.scandir", "os.replace", "shutil.copyfile"):
            assert own not in calls, (module.__name__, own)


def test_the_pattern_knows_nothing_of_ffmpeg_tags_covers_or_tk():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    modules = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    assert modules == {"__future__", "os", "shutil", "pathlib", "typing", "shared"}
    for banned in ("subprocess", "tkinter", "threading", "mutagen", "PIL", "ffmpeg"):
        assert not any(banned in name for name in modules), banned
    calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert "shutil.rmtree" not in calls and "os.walk" not in calls, "links are never entered"
    assert {"os.replace", "os.unlink", "os.rmdir", "os.scandir", "shutil.copyfile"} <= calls
    assert "output_paths.assert_no_link_in" in calls, "link detection is the shared authority's"
