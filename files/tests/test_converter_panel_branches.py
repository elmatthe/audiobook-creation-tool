"""M4B Converter panel branches that had no automated check — v0.7.2 Phase 6, ACT72-051.

Convert with an FFmpeg pair nobody proved, a typed MP3 quality or Start # outside its range or not a number, and Open
Output Folder before and after a run and when the folder cannot be made. The real panel with the shared media stubs
(``install_conversion_stubs``: only the child-spawning call is replaced, so the encoder's real command line is read back).
The error dialog is recorded at ``messagebox``; that a native dialog appears is the journeys' business.
"""

from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")

from shared import output_paths  # noqa: E402

from m4b.converter import m4b_converter  # noqa: E402

from test_m4b_converter_importing import add_files, books  # noqa: E402
from test_m4b_conversion_plan import StubThread  # noqa: E402
from test_m4b_converter_jobs import (  # noqa: E402,F401  (fixtures are collected by name)
    logger,
    make_panel,
    output_base,
    run_env,
    start,
    tk_root,
    work,
)


@pytest.fixture
def dialogs(monkeypatch):
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(m4b_converter.messagebox, "showerror", lambda title, message, **kw: seen.append((title, message)))
    monkeypatch.setattr(m4b_converter.messagebox, "showwarning", lambda title, message, **kw: seen.append((title, message)))
    return seen


def type_into(widget, text: str) -> None:
    """What typing does to the box: its text replaced, through the widget, not the variable."""
    widget.delete(0, "end")
    widget.insert(0, text)


# --------------------------------------------------------------------------- FFmpeg (ACT.CONVERTER.FFMPEG-READY)


def test_convert_with_an_ffmpeg_nobody_proved_says_so_and_starts_nothing(make_panel, tmp_path, run_env, dialogs,
                                                                          monkeypatch, output_base):
    monkeypatch.setattr(m4b_converter.ffmpeg_utils, "verified_ffmpeg", lambda: False)
    monkeypatch.setattr(m4b_converter.ffmpeg_utils, "status_line", lambda: "FFmpeg was found but not proved on this machine.")
    panel = make_panel()
    source, = books(tmp_path / "src", "A.m4b")
    add_files(panel, source)
    panel.start_convert()
    assert dialogs == [("FFmpeg is not ready", "FFmpeg was found but not proved on this machine.")]
    assert StubThread.started == [], "no worker"
    assert panel.run_snapshot is None and not panel._busy.is_set(), "nothing was frozen and the panel is not busy"
    assert not output_base.exists() or not any(output_base.rglob("*")), "no run folder and no output"
    assert run_env["commands"] == []
    assert source.read_bytes() == b"not an audiobook"


# --------------------------------------------------------------------------- typed values (QUALITY, NUMBERING)


@pytest.mark.parametrize("typed, frozen", [("15", 9), ("9", 9), ("-3", 0), ("0", 0), ("4.7", 4), ("abc", 2), ("", 2)])
def test_a_typed_quality_is_held_to_0_to_9_and_anything_else_is_the_default(make_panel, tmp_path, run_env, typed,
                                                                              frozen):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    type_into(panel.entry_quality, typed)
    assert panel.read_options().quality == frozen
    work(panel, tmp_path, run_env)
    assert panel.run_snapshot.tool_options["quality"] == frozen
    encodes = [argv for argv in run_env["commands"] if "-q:a" in argv]
    assert encodes and all(argv[argv.index("-q:a") + 1] == str(frozen) for argv in encodes), encodes


@pytest.mark.parametrize("typed, frozen", [("0", 1), ("-5", 1), ("abc", 1), ("", 1), ("2.5", 2), ("7", 7)])
def test_a_typed_start_number_below_one_or_not_a_number_starts_at_one(make_panel, tmp_path, run_env, typed, frozen):
    panel = make_panel()
    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    panel.var_auto_num.set(True)
    type_into(panel.entry_start_num, typed)
    assert panel.read_options().start_number == frozen
    start(panel)
    assert panel.run_snapshot.tool_options["start_number"] == frozen


# --------------------------------------------------------------------------- Open Output Folder (ACT.CONVERTER.OUTPUT-FOLDER)


def test_open_output_folder_reveals_the_tool_folder_then_the_run_and_explains_a_refusal(
        make_panel, tmp_path, run_env, dialogs, monkeypatch, output_base):
    revealed: list = []
    monkeypatch.setattr(m4b_converter.sp, "reveal_in_file_manager", revealed.append)
    panel = make_panel()
    panel.open_outdir()
    tool_folder = output_paths.ensure_tool_parent(m4b_converter.TOOL_KEY)
    assert revealed == [tool_folder] and tool_folder.is_dir() and not any(tool_folder.iterdir()), \
        "before any run: the tool's own folder, made so the person lands somewhere real, and no run reserved"

    def refused(tool_key, effective=None):
        raise output_paths.OutputPathError("The output folder cannot be created.", "denied for this test")

    with monkeypatch.context() as patch:
        patch.setattr(m4b_converter.output_paths, "ensure_tool_parent", refused)
        panel.open_outdir()
    assert revealed == [tool_folder], "a folder that cannot be made is never replaced by a reveal of something else"
    assert dialogs == [("Output folder", "The output folder cannot be created.")]

    add_files(panel, *books(tmp_path / "src", "A.m4b"))
    work(panel, tmp_path, run_env)
    run = panel.output_dir()
    assert run != tool_folder and run.is_dir()
    panel.open_outdir()
    assert revealed[-1] == run, "after a run: that run's own folder"
