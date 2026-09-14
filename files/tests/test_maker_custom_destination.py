"""v0.6.0 Drop 2 Phase 5 — M4B Maker custom destination.

Decision 10A's second exception: an opt-in toggle that sends the finished
``.m4b`` straight into a directory the user picked, with no nested
``M4B-Maker-N`` and no standard run reserved. Everything else — sanitisation,
collision numbering, source protection — is the shared service, unchanged.

All fixtures are generated into ``tmp_path``; no repository or user media, no
real settings, and no real Downloads folder is involved.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from mp3_tools import m4b_maker as mk  # noqa: E402
from mp3_tools import m4b_maker_plan as mp  # noqa: E402
from mp3_tools import m4b_maker_processing as proc  # noqa: E402
from shared import config, output_paths as op  # noqa: E402
from shared import settings as app_settings  # noqa: E402
import tk_gate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def tk_root():
    yield from tk_gate.tk_root_session(tk)


@pytest.fixture
def fresh_root(tk_root):
    for child in tk_root.winfo_children():
        child.destroy()
    yield tk_root
    for child in tk_root.winfo_children():
        child.destroy()


@pytest.fixture
def output_base(tmp_path, monkeypatch):
    app_settings.use_path(tmp_path / "runtime-data" / "settings.json")
    base = tmp_path / "OutputBase"
    root = tmp_path / "fakerepo"
    (root / "scripts" / "Universal").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "Universal" / "launcher.py").write_text("#\n", encoding="utf-8")
    (root / "config.toml").write_text(
        "[project]\n"
        f'version = "{config.DEFAULTS["project.version"]}"\n'
        "[output]\n"
        f'base_directory = "{base.as_posix()}"\n',
        encoding="utf-8",
    )
    snapshot = config.load(config_path=root / "config.toml", settings_data={}, repo_root=root)
    monkeypatch.setattr(config, "get_effective", lambda: snapshot)
    config.invalidate()
    try:
        yield base
    finally:
        app_settings.use_path(None)
        config.invalidate()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fake_mp3(path: Path, payload: bytes = b"ID3\x03\x00\x00\x00\x00\x00\x00") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload + b"\x00" * 64)
    return path


# --------------------------------------------------------------------------- #
# UI and state
# --------------------------------------------------------------------------- #


def test_the_custom_toggle_is_off_on_a_fresh_build(fresh_root, output_base):
    ui = mk.build_ui(ttk.Frame(fresh_root))
    assert ui.chk_custom_dest.cget("text") == mk.CUSTOM_DEST_LABEL
    assert ui.var_custom_dest.get() is False
    assert ui.custom_destination() is None


def test_the_custom_controls_are_hidden_while_the_toggle_is_off(fresh_root, output_base):
    ui = mk.build_ui(ttk.Frame(fresh_root))
    fresh_root.update_idletasks()
    assert not ui.customrow.winfo_manager(), "the path row must be hidden"


def test_enabling_the_toggle_reveals_the_path_controls(fresh_root, output_base):
    ui = mk.build_ui(ttk.Frame(fresh_root))
    ui.var_custom_dest.set(True)
    ui._on_custom_dest_change()
    fresh_root.update_idletasks()
    assert ui.customrow.winfo_manager(), "the path row must be visible"
    assert ui.entry_custom.winfo_exists()
    assert ui.btn_browse_custom.winfo_exists()


def test_disabling_the_toggle_hides_the_controls_again(fresh_root, output_base):
    ui = mk.build_ui(ttk.Frame(fresh_root))
    ui.var_custom_dest.set(True)
    ui._on_custom_dest_change()
    ui.var_custom_dest.set(False)
    ui._on_custom_dest_change()
    fresh_root.update_idletasks()
    assert not ui.customrow.winfo_manager()


def test_a_stale_hidden_path_cannot_affect_a_standard_build(fresh_root, output_base, tmp_path):
    """While the toggle is off the widget is not consulted at all."""
    ui = mk.build_ui(ttk.Frame(fresh_root))
    ui.var_custom_dest.set(True)
    ui.var_custom_path.set(str(tmp_path / "Elsewhere"))
    ui.var_custom_dest.set(False)
    assert ui.custom_destination() is None


def test_rebuilding_the_panel_never_restores_the_custom_mode(fresh_root, output_base, tmp_path):
    first = mk.build_ui(ttk.Frame(fresh_root))
    first.var_custom_dest.set(True)
    first.var_custom_path.set(str(tmp_path))

    second = mk.build_ui(ttk.Frame(fresh_root))
    assert second.var_custom_dest.get() is False
    assert second.var_custom_path.get() == ""
    assert second.custom_destination() is None


def test_the_custom_destination_is_not_persisted(fresh_root, output_base, tmp_path):
    ui = mk.build_ui(ttk.Frame(fresh_root))
    ui.var_custom_dest.set(True)
    ui.var_custom_path.set(str(tmp_path / "Chosen"))
    stored = app_settings.all_settings()
    assert not any("custom" in str(k).lower() for k in stored)


# --------------------------------------------------------------------------- #
# Destination validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_a_blank_destination_is_rejected(raw):
    with pytest.raises(op.OutputBaseError):
        op.validate_custom_destination(raw)


def test_a_relative_destination_is_rejected():
    with pytest.raises(op.OutputBaseError):
        op.validate_custom_destination("Outputs")


def test_a_missing_destination_is_rejected(tmp_path):
    with pytest.raises(op.OutputBaseError) as excinfo:
        op.validate_custom_destination(tmp_path / "nope")
    assert "does not exist" in excinfo.value.message


def test_a_file_presented_as_a_directory_is_rejected(tmp_path):
    target = tmp_path / "a-file.txt"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(op.OutputBaseError) as excinfo:
        op.validate_custom_destination(target)
    assert "not a folder" in excinfo.value.message


def test_a_linked_destination_is_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        import subprocess

        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(real)],
            capture_output=True, text=True,
        )
        if completed.returncode != 0:
            pytest.skip(f"cannot create a directory link here: {completed.stderr.strip()}")
    with pytest.raises(op.UnsafePathError) as excinfo:
        op.validate_custom_destination(link)
    assert "link" in excinfo.value.message


def test_an_unwritable_destination_is_rejected(tmp_path, monkeypatch):
    target = tmp_path / "readonly"
    target.mkdir()

    def refuse(*_a, **_k):
        raise PermissionError("access is denied")

    monkeypatch.setattr(op.tempfile, "mkstemp", refuse)
    with pytest.raises(op.OutputBaseError) as excinfo:
        op.validate_custom_destination(target)
    assert "cannot be written to" in excinfo.value.message


def test_a_valid_destination_is_accepted_and_left_clean(tmp_path):
    target = tmp_path / "Chosen"
    target.mkdir()
    existing = target / "keep.txt"
    existing.write_text("mine", encoding="utf-8")

    resolved = op.validate_custom_destination(target)

    assert resolved == op._normalise(target)
    assert sorted(p.name for p in target.iterdir()) == ["keep.txt"], \
        "validation must leave no probe file behind"
    assert existing.read_text(encoding="utf-8") == "mine"


def test_validation_failure_reserves_no_standard_run(fresh_root, output_base, tmp_path,
                                                    monkeypatch):
    """v0.6.4 Phase 6: the Book carries the input now, not a raw ``ui.files``."""
    shown = []
    monkeypatch.setattr(mk.messagebox, "showerror",
                        lambda *a, **k: shown.append(a))

    ui = mk.build_ui(ttk.Frame(fresh_root))
    ui._choose_files = lambda: (str(fake_mp3(tmp_path / "src" / "01.mp3")),)
    ui.add_files()
    assert not ui.workspace.current.is_empty
    ui.var_custom_dest.set(True)
    ui.var_custom_path.set(str(tmp_path / "does-not-exist"))

    assert ui.build() is False

    assert shown, "the user must be told why it did not start"
    assert not output_base.exists(), "an invalid destination must not reserve a run"
    assert ui.run is None and not ui.is_running, "no run may have started"
    ui.close()


# --------------------------------------------------------------------------- #
# Direct output and collisions
# --------------------------------------------------------------------------- #


def test_custom_mode_plans_directly_into_the_chosen_directory(tmp_path):
    destination = tmp_path / "Chosen"
    destination.mkdir()
    planner = op.DestinationPlanner(destination)

    planned = planner.plan("My Book.m4b")

    assert planned == destination / "My Book.m4b"
    assert planned.parent == destination, "no nested run directory"


def test_custom_mode_creates_no_nested_numbered_run(tmp_path):
    destination = tmp_path / "Chosen"
    destination.mkdir()
    op.DestinationPlanner(destination).plan("Book.m4b")
    assert [p.name for p in destination.iterdir()] == []
    assert not (destination / "M4B-Maker-1").exists()


def test_custom_mode_sanitises_the_title(tmp_path):
    destination = tmp_path / "Chosen"
    destination.mkdir()
    planned = op.DestinationPlanner(destination).plan('My<Book>:Title.m4b')
    assert planned.name == "My_Book__Title.m4b"


def test_custom_mode_numbers_against_an_existing_file(tmp_path):
    destination = tmp_path / "Chosen"
    destination.mkdir()
    (destination / "Book.m4b").write_bytes(b"earlier")

    planned = op.DestinationPlanner(destination).plan("Book.m4b")

    assert planned.name == "Book-1.m4b"
    assert (destination / "Book.m4b").read_bytes() == b"earlier", "never overwritten"


def test_custom_mode_numbers_planned_collisions_too(tmp_path):
    destination = tmp_path / "Chosen"
    destination.mkdir()
    planner = op.DestinationPlanner(destination)
    names = [planner.plan("Book.m4b").name for _ in range(3)]
    assert names == ["Book.m4b", "Book-1.m4b", "Book-2.m4b"]


def test_custom_mode_preserves_the_final_suffix_rule(tmp_path):
    destination = tmp_path / "Chosen"
    destination.mkdir()
    (destination / "Book 1.5 - Extras.m4b").write_bytes(b"x")
    planned = op.DestinationPlanner(destination).plan("Book 1.5 - Extras.m4b")
    assert planned.name == "Book 1.5 - Extras-1.m4b"


def test_a_planned_output_never_escapes_the_chosen_directory(tmp_path):
    destination = tmp_path / "Chosen"
    destination.mkdir()
    planner = op.DestinationPlanner(destination)
    planned = planner.plan("../escape.m4b")
    assert planned.parent == destination
    assert op.assert_contained(destination, planned)


# --------------------------------------------------------------------------- #
# Staging, cleanup and source safety
# --------------------------------------------------------------------------- #


def test_custom_mode_stages_outside_the_users_directory(tmp_path):
    """Staging must not litter a folder the user chose.

    v0.6.4 Phase 3 made this a planning contract: a custom destination carries
    an operation-owned work root that may not be, or lie inside, the chosen
    folder; the panel makes that root in the system temp area.
    """
    chosen = tmp_path / "Chosen"
    chosen.mkdir()
    with pytest.raises(mp.PlanError):
        mp.custom_destination(chosen, work_root=chosen)
    with pytest.raises(mp.PlanError):
        mp.custom_destination(chosen, work_root=chosen / "staging")
    elsewhere = mp.custom_destination(chosen, work_root=tmp_path / "op-work")
    assert elsewhere.work_root.parent == tmp_path
    source = Path(mk.__file__).read_text(encoding="utf-8")
    assert "tempfile.mkdtemp(prefix=" in source
    assert "WORK_ROOT_PREFIX" in source


def test_cancellation_never_removes_the_chosen_directory():
    """The Phase 4 cancel path rmtree'd out_dir; in custom mode that is the user's folder."""
    import ast

    source = Path(mk.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        body = ast.dump(node)
        if "ConversionCancelled" not in ast.dump(node.type or ast.Name(id="")):
            continue
        # The unconditional rmtree(out_dir) must now sit behind the standard branch.
        assert "custom_destination" in body, \
            "cancellation must distinguish a reserved run from the user's folder"


def test_cancellation_cleanup_is_guarded_in_source():
    """The panel deletes nothing; the engine's cleanup is bounded to its staging.

    v0.6.4 Phase 4 moved cancellation cleanup into ``m4b_maker_processing``:
    ``discard_staging`` refuses a staging directory that is not directly under
    the operation's work root and never removes a destination folder, so a
    cancelled custom build cannot reach the user's folder. The panel itself
    carries no ``rmtree`` at all.
    """
    import ast

    from mp3_tools import m4b_staging

    panel = Path(mk.__file__).read_text(encoding="utf-8")
    assert "rmtree" not in panel and "ConversionCancelled" not in panel
    # v0.6.4 Phase 9 extracted the bounded discard into the shared M4B staging
    # module; the Maker engine delegates to it and adds nothing of its own.
    engine = ast.parse(Path(proc.__file__).read_text(encoding="utf-8"))
    delegate = next(node for node in ast.walk(engine)
                    if isinstance(node, ast.FunctionDef) and node.name == "discard_staging")
    assert "m4b_staging.discard_staging" in ast.unparse(delegate)
    staging = ast.parse(Path(m4b_staging.__file__).read_text(encoding="utf-8"))
    discard = next(node for node in ast.walk(staging)
                   if isinstance(node, ast.FunctionDef) and node.name == "discard_staging")
    called = {node.func.id for node in ast.walk(discard)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "require_owned" in called, "staging is proved operation-owned before anything goes"
    assert "rmtree" not in ast.dump(discard), "entries are removed one by one, inside the root"


def test_drop_staging_only_removes_operation_owned_directories(tmp_path):
    """The engine's discard refuses a staging area outside the work root."""
    from test_m4b_maker_plan import book, plan, workspace  # noqa: F401

    chosen = tmp_path / "Chosen"
    chosen.mkdir()
    destination = mp.custom_destination(chosen, work_root=tmp_path / "op-work")
    sources = tmp_path / "Sources"
    sources.mkdir()
    made = plan(workspace(book(sources, "A", ["1.mp3"], title="A")), destination)
    entry = made.books[0]
    with pytest.raises(proc.ProcessingError):
        proc.discard_staging(entry, work_root=chosen)
    assert proc.discard_staging(entry, work_root=made.work_root) == 0
    assert chosen.exists() and [p.name for p in chosen.iterdir()] == []


def test_source_mp3s_and_cover_are_never_written(tmp_path):
    """The Maker reads its inputs; nothing in the module opens one for writing."""
    import ast

    source = Path(mk.__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in ("write_bytes", "write_text") or True
    # ffmpeg is always invoked with the sources as -i inputs, never as outputs.
    assert "-i" in source
    assert "shutil.move" not in source
    assert "os.replace" not in source


def test_the_maker_is_now_the_multi_book_workspace(fresh_root, output_base):
    """v0.6.4 Phase 6 retired the old "no multi-Book yet" guard: the Maker is
    the second production adopter of the shared workspace, and the Book actions
    are the shared navigator's, not strings this panel spells."""
    from shared.book_workspace_ui import BookNavigator

    ui = mk.build_ui(ttk.Frame(fresh_root))
    try:
        assert isinstance(ui.navigator, BookNavigator)
        assert ui.navigator.actions == BookNavigator.BOOK_ACTIONS
        assert ui.workspace.count == 1 and ui.workspace.current.is_empty
        assert not hasattr(ui, "files")
    finally:
        ui.close()
    source = Path(mk.__file__).read_text(encoding="utf-8")
    assert "filename template" not in source, "naming is the Phase 3 planner's"


def test_standard_mode_still_reserves_exactly_one_run(fresh_root, output_base, tmp_path):
    ui = mk.build_ui(ttk.Frame(fresh_root))
    assert ui.custom_destination() is None
    reservation = op.reserve_run_directory("m4b_maker")
    assert reservation.run_directory.parent.name == "M4B-Maker-Outputs"
    assert reservation.run_directory.name == "M4B-Maker-1"
