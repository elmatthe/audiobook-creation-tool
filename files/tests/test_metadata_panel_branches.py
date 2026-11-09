"""M4B Metadata Editor panel branches that had no automated check — v0.7.2 Phase 6, ACT72-053.

Import Folder's "Replace the current Books?" question, a run folder that cannot be reserved, a plan refused after its run
was reserved, the all-unreadable refusal releasing its run folder, Clear Log and the per-action divider, and the remembered
file, folder and image folders. The real panel through its own methods on real M4B files; message boxes and dialogs are
the seams the panel takes, so the panel's decision and wording are what is proved here, not a native dialog.
"""

from __future__ import annotations

from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared import output_paths  # noqa: E402
from shared import settings as app_settings  # noqa: E402
from shared.job_control import JobState  # noqa: E402

from m4b.metadata import m4b_metadata_editor as editor  # noqa: E402
from m4b.metadata import m4b_metadata_workflow as wf  # noqa: E402
from m4b.metadata.m4b_metadata_plan import EditorAction  # noqa: E402

from test_m4b_metadata_editor_ui import (  # noqa: E402,F401  (fixtures are collected by name)
    container,
    import_folder,
    library,
    make_panel,
    output_base,
    run_action,
    tk_root,
    windows_theme,
)
from test_m4b_metadata_processing import png, sha  # noqa: E402

SAVE = editor.ACTION_LABELS[EditorAction.SAVE_TAGS]


def settle(panel, rounds: int = 20) -> None:
    for _ in range(rounds):
        panel._pump.tick()
        if not panel._coordinator.is_active:
            return


def sources_of(panel) -> list[str]:
    return [wf.source_of(book).path.name for book in panel.workspace.books if wf.source_of(book) is not None]


def runs_under(output_base: Path) -> list[str]:
    tool = output_base / "M4B-Metadata-Outputs"
    return sorted(path.name for path in tool.iterdir()) if tool.exists() else []


def workers(panel) -> list:
    return [thread for thread in panel._thread_factory.made if str(getattr(thread, "name", "")).startswith("m4b-metadata-")]


@pytest.fixture
def isolated_settings(tmp_path):
    app_settings.use_path(tmp_path / "runtime-data" / "settings.json")
    try:
        yield
    finally:
        app_settings.use_path(None)


# --------------------------------------------------------------------------- import (ACT.METADATA.IMPORT)


def test_import_folder_asks_before_replacing_books_and_no_keeps_them(make_panel, container, tmp_path):
    asked: list[tuple[str, str]] = []
    answer = {"value": False}
    panel = make_panel(confirm=lambda title, message: asked.append((title, message)) or answer["value"])
    import_folder(panel, library(container, tmp_path / "Library"))
    settle(panel)
    assert asked == [], "a pristine workspace is replaced without a question"
    before = sources_of(panel)
    assert before == ["Alpha.m4b", "Beta.m4b", "Gamma.m4a"]
    other = tmp_path / "Other"
    other.mkdir()
    (other / "Delta.m4b").write_bytes(container.read_bytes())
    chosen: list[int] = []
    panel._choose_folder = lambda: chosen.append(1) or (str(other),)
    panel.import_folder()
    settle(panel)
    assert [title for title, _ in asked] == ["Replace the current Books?"]
    assert "one Book per file" in asked[0][1]
    assert chosen == [] and sources_of(panel) == before, "No keeps every Book and opens no folder dialog"
    answer["value"] = True
    panel.import_folder()
    settle(panel)
    assert len(asked) == 2 and chosen == [1] and sources_of(panel) == ["Delta.m4b"]


# --------------------------------------------------------------------------- starting a run (ACT.METADATA.RUN-START)


def test_a_run_folder_that_cannot_be_reserved_starts_nothing_and_says_why(make_panel, container, tmp_path, monkeypatch,
                                                                          output_base):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    settle(panel)
    hashes = {name: sha(path) for name, path in ((p.name, p) for p in (tmp_path / "Library").rglob("*.m4*"))}

    def refuse(tool_key, **kwargs):
        raise output_paths.OutputPathError("The output folder cannot be created.", "denied for this test")

    monkeypatch.setattr(output_paths, "reserve_run_directory", refuse)
    assert panel.save() is False
    assert make_panel.dialogs[-1] == ("error", "The output folder cannot be created.")
    assert workers(panel) == [] and panel.last_plan is None and panel.run is None and not panel.is_running
    assert {p.name: sha(p) for p in (tmp_path / "Library").rglob("*.m4*")} == hashes


def test_a_plan_refused_after_reserving_releases_the_empty_run_and_says_why(make_panel, container, tmp_path,
                                                                            monkeypatch, output_base):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    settle(panel)

    def refuse(*args, **kwargs):
        raise editor.mp.PlanError("two Books would write the same file")

    monkeypatch.setattr(editor.mp, "plan_run", refuse)
    assert panel.save() is False
    assert make_panel.dialogs[-1] == ("error", f"{SAVE}: two Books would write the same file")
    assert runs_under(output_base) == [], "the run it reserved was empty and is released"
    assert workers(panel) == [] and panel.last_plan is None and not panel.is_running


def test_when_no_imported_file_can_be_read_the_reserved_run_is_released(make_panel, tmp_path, output_base):
    """ACT.METADATA.UNREADABLE: the refusal used to be checked only for "no .m4b written" by a journey."""
    root = tmp_path / "Unreadable"
    root.mkdir()
    (root / "Broken One.m4b").write_bytes(b"not an mp4 container at all")
    (root / "Broken Two.m4b").write_bytes(b"\x00" * 512)
    panel = make_panel()
    import_folder(panel, root)
    settle(panel)
    assert panel.log.summary[-1].endswith("2 could not be read and will be skipped."), panel.log.summary[-1]
    assert panel.save() is False
    assert make_panel.dialogs[-1] == ("warning", "None of the imported files could be read, so there is nothing to write.")
    assert runs_under(output_base) == [], "the run folder it reserved is released"
    assert workers(panel) == [] and panel.last_plan is None
    assert (root / "Broken One.m4b").read_bytes() == b"not an mp4 container at all"


# --------------------------------------------------------------------------- activity log (ACT.METADATA.ACTIVITY-LOG)


def test_each_action_starts_under_its_own_divider_and_clear_log_clears_only_the_view(make_panel, container, tmp_path,
                                                                                    output_base):
    panel = make_panel()
    import_folder(panel, library(container, tmp_path / "Library"))
    settle(panel)
    assert run_action(panel, "save") is True
    first_run = panel.last_plan.run_directory
    assert panel.last_result.state is JobState.SUCCEEDED
    panel.surface.set_shared_text("genre", "New")
    assert run_action(panel, "save") is True
    second_run = panel.last_plan.run_directory
    assert first_run != second_run and panel.last_result.state is JobState.SUCCEEDED
    summary = list(panel.log.summary)
    first = f"{editor.DIVIDER_MARK} {SAVE} — {first_run.name}"
    second = f"{editor.DIVIDER_MARK} {SAVE} — {second_run.name}"
    assert first in summary and second in summary, summary
    a, b = summary.index(first), summary.index(second)
    assert a < b and any(line.startswith(SAVE + ":") for line in summary[a + 1:b]), "the first action's lines sit under its divider"
    assert any(line.startswith(SAVE + ":") for line in summary[b + 1:]), "and the second's under its own, after them"
    result = panel.last_result
    outputs = sorted(path.name for path in second_run.rglob("*") if path.is_file())
    panel.clear_log()
    assert panel.log.summary == () and panel.log.details == ()
    assert panel.log.summary_text.get("1.0", "end-1c") == "" and panel.log.details_text.get("1.0", "end-1c") == ""
    assert panel.last_result is result
    assert sorted(path.name for path in second_run.rglob("*") if path.is_file()) == outputs, "outputs stay"
    panel._pump.tick()
    assert panel.log.summary == (), "a re-render of the same run puts nothing back"


# --------------------------------------------------------------------------- remembered folders (ACT.METADATA.REMEMBERED-FOLDERS)


def test_file_folder_and_image_choices_are_remembered_and_a_vanished_folder_falls_back_to_home(
        make_panel, container, tmp_path, monkeypatch, isolated_settings):
    library_root = library(container, tmp_path / "Library")
    images = tmp_path / "Images"
    picture = png(images / "cover.png")
    home = tmp_path / "TheHome"
    home.mkdir()
    opened: list[tuple[str, str]] = []

    def askdirectory(**kwargs):
        opened.append(("folder", kwargs["initialdir"]))
        return str(library_root)

    def askopenfilenames(**kwargs):
        opened.append(("files", kwargs["initialdir"]))
        return (str(library_root / "More" / "Gamma.m4a"),)

    def ask_artwork(parent, *, initialdir=None, title=""):
        opened.append(("image", str(initialdir)))
        return str(picture)

    monkeypatch.setattr(editor.filedialog, "askdirectory", askdirectory)
    monkeypatch.setattr(editor.filedialog, "askopenfilenames", askopenfilenames)
    monkeypatch.setattr(editor.m4b_artwork_ui, "ask_artwork", ask_artwork)
    monkeypatch.setattr(editor.Path, "home", classmethod(lambda cls: home))
    panel = make_panel(choose_folder=None, choose_files=None, choose_artwork=None)

    panel.import_folder()
    settle(panel)
    assert opened[-1] == ("folder", str(home)) and app_settings.get(editor.KEY_INPUT_DIR) == str(library_root)
    panel.add_files()
    settle(panel)
    assert opened[-1] == ("files", str(library_root)), "the file dialog opens where the folder dialog chose"
    assert app_settings.get(editor.KEY_INPUT_DIR) == str(library_root / "More")
    panel.choose_shared_artwork()
    assert opened[-1] == ("image", str(home)) and app_settings.get(editor.KEY_COVER_DIR) == str(images)
    panel.choose_shared_artwork()
    assert opened[-1] == ("image", str(images)), "the image dialog opens where the last image was"

    picture.unlink()
    images.rmdir()
    panel.choose_shared_artwork()
    assert opened[-1] == ("image", str(home)), "a folder that is gone falls back to home"
    monkeypatch.setattr(editor.filedialog, "askdirectory", lambda **kwargs: opened.append(("folder", kwargs["initialdir"])) or "")
    app_settings.set(editor.KEY_INPUT_DIR, str(tmp_path / "Gone"))
    panel.import_folder()
    assert opened[-1] == ("folder", str(home))
