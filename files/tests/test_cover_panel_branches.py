"""Cover Image panel branches that had no automated check — v0.7.2 Phase 6, ACT72-050.

A run folder that cannot be reserved, and the remembered Add Files / Add Folder folder. The real panel through its own
methods; ``filedialog`` and ``messagebox`` are recorded at the module the panel calls, so the panel's decision is what is
proved here. The real Replace confirmation is driven by real input in the native journey ``cover.replace-confirmation``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared import output_paths  # noqa: E402
from shared import settings as app_settings  # noqa: E402

from artwork import cover_resizer as cr  # noqa: E402

from test_cover_jobs import (  # noqa: E402,F401  (fixtures are collected by name)
    InlineRunner,
    _clean_capability_cache,
    capture_dialog,
    import_files,
    make_image,
    make_panel,
    output_base,
    sha,
    tk_root,
)


def test_a_run_folder_that_cannot_be_reserved_starts_nothing_and_says_why(make_panel, tmp_path, monkeypatch, output_base):
    errors = capture_dialog(monkeypatch, "showerror")
    runner = InlineRunner()
    panel = make_panel(job_runner=runner)
    image = make_image(tmp_path / "in" / "a.png")
    before = sha(image)
    import_files(panel, image)
    shown = panel.var_outdir.get()

    def refuse(tool_key, **kwargs):
        raise output_paths.OutputPathError("The output folder cannot be created.", "denied for this test")

    monkeypatch.setattr(output_paths, "reserve_run_directory", refuse)
    assert panel.start_resize() is None
    assert errors == [("Output folder", "The output folder cannot be created.")]
    assert runner.calls == [], "no worker was handed a run"
    assert not panel._busy.is_set() and panel._last_run_dir is None and panel.var_outdir.get() == shown
    assert not output_base.exists() or not any(output_base.rglob("*.*")), "nothing written"
    assert sha(image) == before and sorted(p.name for p in image.parent.iterdir()) == ["a.png"]


def test_a_plan_refused_after_reserving_gives_the_empty_run_folder_back(make_panel, tmp_path, monkeypatch, output_base):
    """ACT72-061 (new in v0.7.2 Phase 6): the "Output folder" message appeared, but the folder just reserved stayed, so the
    next run became Cover-Image-2 beside an empty Cover-Image-1. Every other tool releases it."""
    errors = capture_dialog(monkeypatch, "showerror")
    runner = InlineRunner()
    panel = make_panel(job_runner=runner)
    import_files(panel, make_image(tmp_path / "in" / "a.png"))

    def refuse(*args, **kwargs):
        raise output_paths.OutputPathError("A destination could not be planned.", "refused for this test")

    monkeypatch.setattr(cr, "plan_destinations", refuse)
    assert panel.start_resize() is None
    assert errors == [("Output folder", "A destination could not be planned.")]
    assert runner.calls == [] and panel._last_run_dir is None
    tool = output_base / "Cover-Image-Outputs"
    assert not tool.exists() or not any(tool.iterdir()), "the empty run folder it reserved is given back"


def test_add_files_and_add_folder_remember_their_folder_and_a_vanished_one_falls_back_to_home(
        make_panel, tmp_path, monkeypatch, output_base):
    """``output_base`` points the settings layer at this test's own file, so nothing here reaches the owner's."""
    first = tmp_path / "Covers"
    image = make_image(first / "a.png")
    second = tmp_path / "More"
    make_image(second / "b.png")
    home = tmp_path / "TheHome"
    home.mkdir()
    opened: list[tuple[str, str]] = []

    def askopenfilenames(**kwargs):
        opened.append(("files", kwargs["initialdir"]))
        return (str(image),)

    def askdirectory(**kwargs):
        opened.append(("folder", kwargs["initialdir"]))
        return str(second)

    monkeypatch.setattr(cr.filedialog, "askopenfilenames", askopenfilenames)
    monkeypatch.setattr(cr.filedialog, "askdirectory", askdirectory)
    monkeypatch.setattr(cr.Path, "home", classmethod(lambda cls: home))
    panel = make_panel(choose_files=None, choose_folder=None)
    panel.importer.add_files()
    assert opened == [("files", str(home))], "nothing remembered yet: the home folder"
    assert app_settings.get(cr.KEY_INPUT_DIR) == str(first)
    panel.importer.add_folder()
    panel._pump.tick()
    assert opened[-1] == ("folder", str(first)), "Add Folder opens where Add Files chose"
    assert app_settings.get(cr.KEY_INPUT_DIR) == str(second)
    panel.importer.add_files()
    assert opened[-1] == ("files", str(second)), "and Add Files where Add Folder chose"
    app_settings.set(cr.KEY_INPUT_DIR, str(tmp_path / "Gone"))
    monkeypatch.setattr(cr.filedialog, "askopenfilenames", lambda **kwargs: opened.append(("files", kwargs["initialdir"])) or ())
    panel.importer.add_files()
    assert opened[-1] == ("files", str(home)), "a folder that is gone falls back to home"
    assert app_settings.get(cr.KEY_INPUT_DIR) == str(tmp_path / "Gone"), "a cancelled dialog saves nothing"
