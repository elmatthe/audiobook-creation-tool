"""One TTS output filename policy, collision safety and the registry-error diagnostic — v0.7.0 P02B.

Every narration route names its file ``<source-stem>-<frozen display label>.mp3``: Edge direct and folder, Kokoro,
Chatterbox, Qwen3 presets and clones, and the standalone ``batch_convert`` helper (its own tests live in
``test_batch_convert_folders.py``). The label is frozen by value when a run is accepted, so a renamed or reordered
registry never moves a run, its retry or its engine. Collisions are resolved by the shared planner's ``stem-1.mp3``
numbering — never by a backend or voice-id suffix — and a name that cannot fit is refused before any synthesis.

The panel tests drive the real :class:`TtsPanel` and real destination planning; only the engine entry points are
stubbed, so nothing synthesises, downloads or loads a model. Every registry edit is a disposable in-memory copy (or a
disposable file for the import-time refusal); the tracked roster, the six reference WAVs and the 28 preview WAVs are
never touched.
"""

from __future__ import annotations

import ast
import importlib.abc
import importlib.util
import sys
import unicodedata
from dataclasses import replace
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from shared import output_paths as op  # noqa: E402
from tts import epub2tts_gui as panel_module  # noqa: E402
from tts import output_names as on  # noqa: E402
from tts import voice_registry as vr  # noqa: E402

from test_tts_importing import make_panel, output_base, sources, stubs, tk_root  # noqa: E402,F401
from test_tts_jobs import (  # noqa: E402,F401
    accept,
    direct_panel,
    failing_stubs,
    folder_panel,
    relative,
    run_attempt,
)
from test_chatterbox_integration import ChatterboxStub  # noqa: E402
from test_qwen3_gui import Qwen3Stub, panel_kwargs, select  # noqa: E402
from test_voice_labels import PERMUTATIONS, REVERSED, SHIPPED_KEYS, relabelled  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"

#: The default voice's shipped label, written as a literal so the tests state the contract.
STEFFAN = "Edge Male - Steffan (en-US)"
#: A Windows budget without long-path support, passed explicitly so the limit is tested on every machine.
WINDOWS_SHORT = on.NameBudget(path_limit=259, directory_limit=247, windows=True)
POSIX = on.NameBudget(path_limit=1023, directory_limit=1023, windows=False)
#: Room a planned name must leave: the collision suffix and the engines' temporary publish name.
HEADROOM = len("-10000") + len(".0123abcd.part")


def engines(stubs, monkeypatch):
    """Every engine entry point stubbed; returns the per-backend call logs and the panel's status seams."""
    chatterbox = ChatterboxStub().install(monkeypatch)
    qwen3 = Qwen3Stub().install(monkeypatch)
    stubs.install_kokoro(monkeypatch)
    calls = {"edge": stubs.conversion_jobs, "kokoro": stubs.kokoro_calls,
             "chatterbox": chatterbox.calls, "qwen3": qwen3.calls}
    return calls, chatterbox, qwen3, panel_kwargs(qwen3, chatterbox)


def published(run: Path) -> list[str]:
    """Every file actually left in a run directory, relative and sorted."""
    return sorted(relative(p, run) for p in run.rglob("*") if p.is_file())


# --------------------------------------------------------------------------- #
# A. The policy itself
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("label", [v.display_label for v in vr.VOICES])
def test_every_shipped_label_names_its_file_exactly(label):
    name = on.canonical_name(Path("Book.pdf"), label)
    assert name == f"Book-{label}.mp3"
    assert op.sanitize_component(name) == name, "the shared sanitiser leaves a planned name alone"


def test_the_name_is_stem_dash_label_and_nothing_else():
    """Negative control: no backend, no voice id and no Edge "(speaker)" suffix is ever added."""
    voices = relabelled(list(range(28)))
    for entry in voices:
        name = on.canonical_name(Path("Book.txt"), entry.display_label)
        assert name == f"Book-{entry.display_label}.mp3"
        assert entry.voice_id not in name and entry.backend not in name and "(" not in name


@pytest.mark.parametrize("label,expected", [
    ('a<b>c:d"e/f\\g|h?i*j', "a_b_c_d_e_f_g_h_i_j"),  # every Windows-forbidden character and both separators
    ("AC/DC", "AC_DC"),                               # a separator inside a label never cuts the name short
    ("Line\tbreak\x7f", "Linebreak"),                 # controls are dropped, as the shared sanitiser does
    ("  padded  ", "padded"),
    ("Dr.", "Dr."),                                   # a trailing dot is legal before ".mp3"
    ("Narrator (Calm), v2 — ok!", "Narrator (Calm), v2 — ok!"),
    ("Ünïcödé 書 🎧", "Ünïcödé 書 🎧"),
    ("bad\ud800half", "bad_half"),                    # an unpaired surrogate cannot be stored or logged
])
def test_a_label_is_cleaned_on_its_own_and_otherwise_kept_verbatim(label, expected):
    name = on.canonical_name(Path("Book.txt"), label)
    assert name == f"Book-{expected}.mp3"
    assert op.sanitize_component(name) == name


def test_cleaning_the_whole_name_at_once_would_lose_the_stem():
    """Why the stem and label are cleaned separately: the shared component sanitiser keeps only the last path element."""
    assert op.sanitize_component("Book-AC/DC.mp3") == "DC.mp3"
    assert on.canonical_name(Path("Book.txt"), "AC/DC") == "Book-AC_DC.mp3"


def test_unicode_composition_is_normalised_so_two_spellings_are_one_name():
    composed, decomposed = "Café", unicodedata.normalize("NFD", "Café")
    assert composed != decomposed
    assert on.canonical_name(Path(f"{decomposed}.txt"), "L") == on.canonical_name(Path(f"{composed}.txt"), "L")
    assert on.canonical_name(Path("x.txt"), decomposed) == "x-Café.mp3"


@pytest.mark.parametrize("stem,expected", [
    ("CON", "CON-L.mp3"),                    # "CON-L" is not a device name: kept as written
    ("nul.backup", "_nul.backup-L.mp3"),     # Windows reads "nul" before the first dot
    ("COM1 .notes", "_COM1 .notes-L.mp3"),   # trailing spaces before that dot are ignored by Windows too
    ("lpt9.x", "_lpt9.x-L.mp3"),
    ("CONSOLE.x", "CONSOLE.x-L.mp3"),
])
def test_windows_device_names_are_guarded_only_where_windows_would_see_one(stem, expected):
    assert on.canonical_name(Path(f"{stem}.txt"), "L") == expected


def test_an_unusable_label_is_refused_rather_than_invented():
    with pytest.raises(on.OutputNameError):
        on.canonical_name(Path("x.txt"), "\x01\x02")
    assert issubclass(on.OutputNameError, op.OutputPathError), "the panel's existing refusal path catches it"


def test_a_long_stem_is_shortened_from_its_end_and_only_as_far_as_needed():
    folder = Path("C:/") / ("d" * 150)
    label = "Qwen3 - Female 1"
    name = on.planned_name(Path("S" * 300 + ".txt"), label, folder, budget=WINDOWS_SHORT)
    assert name.endswith(f"-{label}.mp3"), "the label is never cut"
    assert len(str(folder / name)) + HEADROOM == 259, "exactly as much stem as fits"
    assert on.planned_name(Path("S" * 300 + ".txt"), label, folder, budget=WINDOWS_SHORT) == name  # deterministic
    short = on.planned_name(Path("Short.txt"), label, folder, budget=WINDOWS_SHORT)
    assert short == f"Short-{label}.mp3", "a name that fits is not touched"


def test_the_component_limit_applies_even_without_a_path_limit():
    unlimited = on.NameBudget(path_limit=None, directory_limit=None, windows=True)
    name = on.planned_name(Path("S" * 400 + ".txt"), STEFFAN, Path("C:/x"), budget=unlimited)
    assert len(name) == 255 - HEADROOM and name.endswith(f"-{STEFFAN}.mp3")
    # The longest collision variant and the longest temporary publish name still fit one component.
    assert len(op.numbered_variant(name, op.MAX_COLLISION_ATTEMPTS) + ".0123abcd.part") <= 255


def test_lengths_are_counted_the_way_each_platform_counts_them():
    emoji = "🎧" * 200  # two UTF-16 units and four UTF-8 bytes each
    windows = on.planned_name(Path(f"{emoji}.txt"), "L", Path("C:/x"),
                              budget=on.NameBudget(None, None, windows=True))
    posix = on.planned_name(Path(f"{emoji}.txt"), "L", Path("/x"), budget=POSIX)
    assert len(windows.encode("utf-16-le")) // 2 <= 255 - HEADROOM < len(windows.encode("utf-16-le")) // 2 + 2
    assert len(posix.encode("utf-8")) <= 255 - HEADROOM
    assert set(windows[:-len("-L.mp3")]) == {"🎧"} == set(posix[:-len("-L.mp3")]), "never half a character"


def test_an_impossible_name_or_folder_is_refused_before_synthesis():
    with pytest.raises(on.OutputNameError, match="too long"):
        on.planned_name(Path("x.txt"), "L" * 300, Path("C:/x"), budget=WINDOWS_SHORT)
    with pytest.raises(on.OutputNameError, match="output folder path is too long"):
        on.planned_name(Path("x.txt"), "L", Path("C:/") / ("d" * 250), budget=WINDOWS_SHORT)
    # A label that fits only without the headroom is refused too: the collision suffix must always have room.
    folder = Path("C:/") / ("d" * 200)
    room = 259 - len(str(folder)) - 1 - HEADROOM
    with pytest.raises(on.OutputNameError):
        on.planned_name(Path("x.txt"), "L" * (room - len("-.mp3")), folder, budget=WINDOWS_SHORT)
    assert on.planned_name(Path("x.txt"), "L" * (room - len("x-.mp3")), folder, budget=WINDOWS_SHORT)


# --------------------------------------------------------------------------- #
# B. Planning with the shared planner (real collision service, real disk checks)
# --------------------------------------------------------------------------- #


def test_sanitised_and_case_only_collisions_are_numbered_by_the_shared_planner(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    planner = op.DestinationPlanner(run)
    sources_ = [Path("a/A?B.txt"), Path("b/A*B.txt"), Path("c/book.txt"), Path("d/BOOK.pdf")]
    plan = on.plan_named(op.plan_flat, run, sources_, label="L", planner=planner)
    assert [d.name for d in plan.destinations] == ["A_B-L.mp3", "A_B-L-1.mp3", "book-L.mp3", "BOOK-L-1.mp3"]


def test_existing_files_including_case_variants_are_never_chosen(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "one-l.mp3").write_bytes(b"earlier, different case")
    (run / "two-L-1.mp3").write_bytes(b"earlier numbered")
    (run / "two-L.mp3").write_bytes(b"earlier")
    plan = on.plan_named(op.plan_flat, run, [Path("x/one.txt"), Path("x/two.txt")], label="L",
                         planner=op.DestinationPlanner(run))
    assert [d.name for d in plan.destinations] == ["one-L-1.mp3", "two-L-2.mp3"]


def test_the_folder_finding_pass_reserves_nothing(tmp_path):
    run = tmp_path / "run"
    planner = op.DestinationPlanner(run, check_filesystem=False)
    on.plan_named(op.plan_flat, run, [Path("x/a.txt")], label="L", planner=planner)
    assert planner.planned_count == 1, "only the real name, never the probe placeholder"
    assert planner.plan("probe.mp3").name == "probe.mp3"


def test_long_names_in_a_deep_mirrored_tree_leave_room_for_the_suffix(tmp_path):
    root = tmp_path / "Library"
    deep = root / ("Series " + "s" * 40) / ("Book " + "b" * 40)
    files = [deep / f"{'Chapter ' + 'c' * 200}.txt", deep / f"{'Chapter ' + 'c' * 200}.pdf"]
    run = Path("C:/R") / ("r" * 40)
    plan = on.plan_named(op.plan_mirrored, run, files, root, label=STEFFAN, budget=WINDOWS_SHORT,
                         planner=op.DestinationPlanner(run, check_filesystem=False))
    first, second = plan.destinations
    assert first.parent == second.parent == run / deep.relative_to(root)
    assert first.name.endswith(f"-{STEFFAN}.mp3") and second.name.endswith(f"-{STEFFAN}-1.mp3")
    assert op.split_suffix(second.name)[0] == op.split_suffix(first.name)[0] + "-1", "same shortened stem, numbered"
    assert len(str(first)) + HEADROOM == 259 and len(str(second)) + HEADROOM <= 261


# --------------------------------------------------------------------------- #
# C. Every route through the real panel, with stubbed engine entry points
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["shipped", "reversed", "interleaved"])
def test_all_28_voices_name_their_file_by_the_selected_label_through_the_panel(
        make_panel, output_base, tmp_path, stubs, monkeypatch, name):
    """Shipped labels, then "1".."28" in reversed and interleaved order: each voice's file carries its own label."""
    order = PERMUTATIONS[name]
    calls, _cbx, _qw, kwargs = engines(stubs, monkeypatch)
    voices = [vr.VOICES[i] for i in order] if name == "shipped" else relabelled(order)
    monkeypatch.setattr(vr, "VOICES", voices)
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt", **kwargs)

    reached = []
    for entry in voices:
        before = {backend: len(log) for backend, log in calls.items()}
        select(panel, entry.display_label)
        params = run_attempt(panel)
        run = params["run_directory"]
        options = params["snapshot"].tool_options
        assert (options["backend"], options["voice_id"], options["label"]) == (*entry.key, entry.display_label)
        ran = [backend for backend, log in calls.items() if len(log) == before[backend] + 1]
        assert ran == [entry.backend], (entry.key, ran)
        expected = f"one-{entry.display_label}.mp3"
        assert [item["destination"].name for item in params["items"]] == [expected]
        if entry.backend != "edge":
            assert calls[entry.backend][-1]["output"] == str(run / expected), "the engine wrote the planned path"
        assert published(run) == [expected], "nothing else, and no engine-private name, was published"
        reached.append(entry.key)
    assert reached == [SHIPPED_KEYS[i] for i in order]


def test_an_edge_folder_file_reaches_the_batch_worker_under_its_planned_name(
        make_panel, output_base, tmp_path, stubs):
    panel, _folders = folder_panel(make_panel, tmp_path)
    params = run_attempt(panel)
    run = params["run_directory"]
    targets = sorted(relative(item["out_mp3"], run) for item in stubs.batch_items)
    assert targets == [f"01-{STEFFAN}.mp3", f"Book A/02-{STEFFAN}.mp3"]
    assert published(run) == targets


def test_same_stem_pdf_and_txt_mixed_direct_and_folder_imports_stay_distinct(
        make_panel, output_base, tmp_path, stubs):
    direct = sources(tmp_path / "Loose", "Book.pdf", "Book.txt")
    root = tmp_path / "Library"
    sources(root, "Book.pdf")
    sources(root / "Sub", "Book.txt")
    panel = make_panel(choose_files=lambda: direct, choose_folder=lambda: (root,))
    panel.importer.add_files()
    panel.importer.add_folder()
    panel._pump.tick()

    params = run_attempt(panel)
    run = params["run_directory"]
    placed = [(item["source"].name, item["direct"], relative(item["destination"], run)) for item in params["items"]]
    assert placed == [
        ("Book.pdf", True, f"Book-{STEFFAN}.mp3"),
        ("Book.txt", True, f"Book-{STEFFAN}-1.mp3"),
        ("Book.pdf", False, f"Book-{STEFFAN}-2.mp3"),   # a folder's top level shares the run root with direct files
        ("Book.txt", False, f"Sub/Book-{STEFFAN}.mp3"),
    ]
    assert published(run) == sorted(p for _s, _d, p in placed)


def test_several_folder_roots_keep_their_containers_with_same_stem_pdf_and_txt(
        make_panel, output_base, tmp_path, stubs):
    roots = []
    for name in ("Books", "More"):
        roots.append(tmp_path / name)
        sources(roots[-1], "Book.pdf", "Book.txt")
    pending = list(roots)
    panel = make_panel(choose_folder=lambda: (pending.pop(0),) if pending else ())
    for _ in roots:
        panel.importer.add_folder()
        panel._pump.tick()
    params = run_attempt(panel)
    run = params["run_directory"]
    assert sorted(relative(item["destination"], run) for item in params["items"]) == [
        f"Books/Book-{STEFFAN}-1.mp3", f"Books/Book-{STEFFAN}.mp3",
        f"More/Book-{STEFFAN}-1.mp3", f"More/Book-{STEFFAN}.mp3",
    ]


def test_case_only_and_unicode_spelling_collisions_get_separate_files(
        make_panel, output_base, tmp_path, stubs):
    composed, decomposed = "Café", unicodedata.normalize("NFD", "Café")
    chosen = (sources(tmp_path / "A", "book.txt") + sources(tmp_path / "B", "BOOK.txt")
              + sources(tmp_path / "C", f"{composed}.txt") + sources(tmp_path / "D", f"{decomposed}.txt"))
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    params = run_attempt(panel)
    names = [item["destination"].name for item in params["items"]]
    assert names == [f"book-{STEFFAN}.mp3", f"BOOK-{STEFFAN}-1.mp3",
                     f"{composed}-{STEFFAN}.mp3", f"{composed}-{STEFFAN}-1.mp3"]
    assert len(published(params["run_directory"])) == 4


def test_a_duplicate_occurrence_on_a_local_engine_gets_its_own_file(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    calls, _cbx, _qw, kwargs = engines(stubs, monkeypatch)
    chosen = sources(tmp_path / "Loose", "twice.txt")
    panel = make_panel(choose_files=lambda: chosen, confirm_large_result=lambda outcome: True, **kwargs)
    panel.importer.add_files()
    panel.importer.options.set_allow_duplicates(True)
    panel.importer.add_files()
    panel._pump.tick()
    select(panel, "Qwen3 - Male 2")
    params = run_attempt(panel)
    run = params["run_directory"]
    assert sorted(Path(c["output"]).name for c in calls["qwen3"]) == [
        "twice-Qwen3 - Male 2-1.mp3", "twice-Qwen3 - Male 2.mp3"]
    assert published(run) == ["twice-Qwen3 - Male 2-1.mp3", "twice-Qwen3 - Male 2.mp3"]


def test_planning_never_chooses_an_input_or_an_existing_file(make_panel, output_base, tmp_path, stubs):
    """Planned straight into the source folder itself: inputs and an earlier output both survive by construction."""
    folder = tmp_path / "Loose"
    chosen = sources(folder, "one.txt", "one.pdf")
    (folder / f"one-{STEFFAN}.mp3").write_bytes(b"an earlier output")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    files = run_attempt(panel)["snapshot"].files

    planned = panel_module.plan_destinations(files, folder, label=STEFFAN)
    destinations = [entry.destination for entry in planned.values()]
    assert sorted(d.name for d in destinations) == [f"one-{STEFFAN}-1.mp3", f"one-{STEFFAN}-2.mp3"]
    for destination in destinations:
        op.assert_not_input(destination, chosen)
    assert (folder / f"one-{STEFFAN}.mp3").read_bytes() == b"an earlier output"


def test_the_panel_plans_with_the_machine_budget_unless_one_is_given(make_panel, output_base, tmp_path, stubs):
    chosen = sources(tmp_path / "Loose", f"{'Chapter ' * 8}.txt")
    panel = make_panel(choose_files=lambda: chosen)
    panel.importer.add_files()
    files = run_attempt(panel)["snapshot"].files
    run = tmp_path / ("r" * (183 - len(str(tmp_path)) - 1))  # a deep run folder; nothing long is created on disk
    assert len(str(run)) == 183
    roomy = panel_module.plan_destinations(files, run, label=STEFFAN,
                                           budget=on.NameBudget(path_limit=None, directory_limit=None, windows=True))
    planned = panel_module.plan_destinations(files, run, label=STEFFAN, budget=WINDOWS_SHORT)
    (full,), (entry,) = roomy.values(), planned.values()
    assert full.destination.name == f"Chapter Chapter Chapter Chapter Chapter Chapter Chapter Chapter-{STEFFAN}.mp3"
    assert len(str(entry.destination)) + HEADROOM == 259
    assert entry.destination.name.endswith(f"-{STEFFAN}.mp3")
    assert full.destination.name.startswith(entry.destination.name[:-len(f"-{STEFFAN}.mp3")])


def test_an_impossible_label_is_refused_at_the_button_and_leaves_nothing(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    errors = []
    monkeypatch.setattr(panel_module.messagebox, "showerror", lambda *a, **k: errors.append(a))
    steffan = vr.voice_by_key("edge", "en-US-SteffanNeural")
    monkeypatch.setattr(vr, "VOICES", [replace(steffan, display_label="L" * 300)] + vr.VOICES[1:])
    panel, _chosen = direct_panel(make_panel, tmp_path, "one.txt")
    select(panel, "L" * 300)

    assert accept(panel) == {}, "no worker was started"
    assert errors and errors[0][0] == "Output folder" and "too long" in errors[0][1]
    assert stubs.conversion_jobs == [] and stubs.batch_items == []
    tool_parent = output_base / op.tool_parent_name("tts")
    assert not any(tool_parent.iterdir()), "the reserved run folder was released, not left empty"


# --------------------------------------------------------------------------- #
# D. Frozen identity, label, options and destinations across a registry edit
# --------------------------------------------------------------------------- #


def test_a_retry_after_relabelling_and_reordering_keeps_its_label_engine_and_destination(
        make_panel, output_base, tmp_path, failing_stubs, monkeypatch):
    panel, _chosen = direct_panel(make_panel, tmp_path, "good.txt", "bad.txt")
    first = run_attempt(panel)
    run = first["run_directory"]
    frozen = dict(first["snapshot"].tool_options)
    planned = {item["source"].name: item["destination"] for item in first["items"]}
    assert planned == {"good.txt": run / f"good-{STEFFAN}.mp3", "bad.txt": run / f"bad-{STEFFAN}.mp3"}
    planned["good.txt"].write_bytes(b"the first success")

    # The maintainer renames and reorders every voice, and the dropdown moves on, before Retry Failed.
    monkeypatch.setattr(vr, "VOICES", relabelled(REVERSED))
    select(panel, "27")  # Andrew, under a new name and a new position; Steffan is now "28"
    failing_stubs.marker = "never"
    second = run_attempt(panel, panel.retry_failed)

    assert [item["destination"] for item in second["items"]] == [planned["bad.txt"]]
    assert dict(second["snapshot"].tool_options) == frozen, "label, identity and every option frozen by value"
    assert (second["backend"], second["voice_id"], second["speaker"]) == ("edge", "en-US-SteffanNeural",
                                                                         "en-US-SteffanNeural")
    assert failing_stubs.conversion_jobs[-1]["speaker"] == "en-US-SteffanNeural"
    assert planned["good.txt"].read_bytes() == b"the first success"
    assert published(run) == [f"bad-{STEFFAN}.mp3", f"good-{STEFFAN}.mp3"], "no name from the new labels"


def test_a_qwen3_clone_retry_keeps_its_frozen_label_after_a_rename(
        make_panel, output_base, tmp_path, stubs, monkeypatch):
    calls, _cbx, qwen3, kwargs = engines(stubs, monkeypatch)
    qwen3.failing = "bad"
    panel, _chosen = direct_panel(make_panel, tmp_path, "good.txt", "bad.txt", **kwargs)
    select(panel, "Qwen3 - Female 1")
    first = run_attempt(panel)
    run = first["run_directory"]
    assert published(run) == ["good-Qwen3 - Female 1.mp3"]

    clone = vr.voice_by_key("qwen3", "qwen3-female-1")
    monkeypatch.setattr(vr, "VOICES", [replace(clone, display_label="Narrator Q")]
                        + [v for v in vr.VOICES if v.key != clone.key])
    qwen3.failing = ""
    run_attempt(panel, panel.retry_failed)

    assert calls["qwen3"][-1]["voice_id"] == "qwen3-female-1"
    assert Path(calls["qwen3"][-1]["output"]) == run / "bad-Qwen3 - Female 1.mp3"
    assert published(run) == ["bad-Qwen3 - Female 1.mp3", "good-Qwen3 - Female 1.mp3"]
    # A new run, by contrast, takes the new label: the old one was frozen, not hard-coded.
    select(panel, "Narrator Q")
    fresh = run_attempt(panel)
    assert sorted(item["destination"].name for item in fresh["items"]) == [
        "bad-Narrator Q.mp3", "good-Narrator Q.mp3"]


def test_the_label_is_frozen_with_the_other_run_options():
    options = panel_module.freeze_tts_options(
        speaker="s", backend="kokoro", voice_id="af_heart", label="Kokoro Female (Default) - Heart (en-US)",
        rate="+0%", resume=False, overwrite=False, bitrate="128k", workers=1, kokoro_speed=1.0, end_pause=0,
        paragraph_pause=1, pause_kw={})
    assert options["label"] == "Kokoro Female (Default) - Heart (en-US)"
    with pytest.raises(TypeError):
        panel_module.freeze_tts_options(  # a run cannot be frozen without the label that names its files
            speaker="s", backend="kokoro", voice_id="af_heart", rate="+0%", resume=False, overwrite=False,
            bitrate="128k", workers=1, kokoro_speed=1.0, end_pause=0, paragraph_pause=1, pause_kw={})


def test_destinations_are_planned_from_the_frozen_label_not_the_live_dropdown():
    run_job = next(n for n in ast.walk(ast.parse((SCRIPTS / "tts" / "epub2tts_gui.py").read_text(encoding="utf-8")))
                   if isinstance(n, ast.FunctionDef) and n.name == "_start_frozen")  # v0.7.0: run_job's second half
    call = next(n for n in ast.walk(run_job)
                if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "plan_destinations")
    label = next(k.value for k in call.keywords if k.arg == "label")
    assert ast.unparse(label) == "snapshot.tool_options['label']"


# --------------------------------------------------------------------------- #
# E. The five other tools keep their names
# --------------------------------------------------------------------------- #

NON_TTS_PACKAGES = ("m4b", "mp3", "artwork")


def test_no_other_tool_reaches_the_tts_naming_policy():
    from source_probe import application_python_files

    checked = {package: 0 for package in NON_TTS_PACKAGES}
    for path in application_python_files(SCRIPTS):
        package = path.relative_to(SCRIPTS).parts[0]
        if package not in checked:
            continue
        checked[package] += 1
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(n == "tts" or n.startswith("tts.") for n in names), (path, names)
    assert all(checked.values()), checked  # every non-TTS package was really walked


def test_the_shared_naming_other_tools_use_is_unchanged():
    assert op.sanitize_component('Book: "Vol 1"?.m4b') == "Book_ _Vol 1__.m4b"
    assert op.sanitize_component("CON.m4b") == "_CON.m4b"
    assert op.numbered_variant("Book.m4b", 1) == "Book-1.m4b"
    planner = op.DestinationPlanner(Path("C:/run"), check_filesystem=False)
    plan = op.plan_flat(Path("C:/run"), [Path("a/Book.m4b"), Path("b/book.m4b")], planner=planner)
    assert [d.name for d in plan.destinations] == ["Book.m4b", "book-1.m4b"]


# --------------------------------------------------------------------------- #
# F. An invalid registry: an actionable diagnostic, TTS unavailable, five tools unaffected
# --------------------------------------------------------------------------- #


def _registry_error():
    """A genuine VoiceRegistryError from a disposable invalid roster (the tracked one is never edited)."""
    with pytest.raises(vr.VoiceRegistryError) as caught:
        vr.check_registry(vr.VOICES + [vr.VOICES[0]])
    return caught.value


def test_a_registry_error_names_the_problem_and_the_file_and_never_blames_dependencies():
    import launcher

    spec = next(t for t in launcher.TOOLS if t.key == "tts")
    exc = _registry_error()
    assert launcher.is_voice_registry_error(exc)
    message = launcher.load_error_message(spec, exc, "Traceback ...")
    assert str(exc) in message and "edge/en-US-SteffanNeural" in message
    assert "scripts/tts/voice_registry.py" in message and "stays unavailable" in message
    for misleading in ("dependency", "reinstall", "requirements", "Traceback"):
        assert misleading not in message, misleading


@pytest.mark.parametrize("exc", [
    ModuleNotFoundError("No module named 'edge_tts'"),
    ImportError("DLL load failed while importing _isfinite"),
    ValueError("The voice list in tts/voice_registry.py cannot be used"),     # right words, wrong class
    type("VoiceRegistryError", (ValueError,), {"__module__": "someone.else"})("spoof"),
])
def test_a_genuine_dependency_failure_keeps_the_reinstall_advice(exc):
    import launcher

    spec = next(t for t in launcher.TOOLS if t.key == "tts")
    assert not launcher.is_voice_registry_error(exc)
    message = launcher.load_error_message(spec, exc, "Traceback (details)")
    assert "reinstall requirements" in message and "Traceback (details)" in message


class _DisposableRegistry(importlib.abc.MetaPathFinder):
    """Serves ``tts.voice_registry`` from a disposable file, so the real import path meets an invalid roster."""

    def __init__(self, path: Path):
        self.path = path

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "tts.voice_registry":
            return importlib.util.spec_from_file_location(fullname, self.path)
        return None


def test_the_launcher_shows_the_registry_error_and_builds_the_other_five_tools(tk_root, tmp_path, monkeypatch):
    import launcher
    from shared import paths, settings

    source = (SCRIPTS / "tts" / "voice_registry.py").read_text(encoding="utf-8")
    anchor = "\ncheck_registry(VOICES)\n"
    assert source.count(anchor) == 1
    broken = tmp_path / "voice_registry.py"
    broken.write_text(source.replace(anchor, "\nVOICES = VOICES + [VOICES[0]]" + anchor), encoding="utf-8")

    monkeypatch.setattr(paths, "SETTINGS_FILE", tmp_path / "settings.json")
    settings.invalidate()
    monkeypatch.setattr(sys, "meta_path", [_DisposableRegistry(broken)] + sys.meta_path)
    for name in ("tts.voice_registry", "tts.epub2tts_gui"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    shown = []
    real_show = launcher.LauncherApp._show_load_error
    monkeypatch.setattr(launcher.LauncherApp, "_show_load_error",
                        lambda self, c, spec, exc: (shown.append((spec.key, exc)), real_show(self, c, spec, exc)))
    for child in tk_root.winfo_children():
        child.destroy()
    try:
        app = launcher.LauncherApp(tk_root)
        tools = [t.key for t in app._available_tools()]
        assert tools == ["tts", "m4b_converter", "mp3_tool", "m4b_maker", "cover", "m4b_metadata"]
        statuses = {}
        for key in tools:
            app.select_tool(key)
            statuses[key] = app.status_var.get()
        tk_root.update_idletasks()
        assert set(app.containers) == set(tools)

        assert [key for key, _exc in shown] == ["tts"], "only TTS failed; the five other tools built normally"
        exc = shown[0][1]
        assert type(exc).__name__ == "VoiceRegistryError" and launcher.is_voice_registry_error(exc)
        assert "edge/en-US-SteffanNeural" in str(exc)
        texts = [w.get("1.0", "end") for w in _walk(app.containers["tts"]) if isinstance(w, tk.Text)]
        assert len(texts) == 1 and "scripts/tts/voice_registry.py" in texts[0]
        assert "reinstall" not in texts[0] and "dependency" not in texts[0]
        assert not [w for w in _walk(app.containers["tts"]) if type(w).__name__ == "TtsPanel"], "TTS stays unavailable"
        for key in tools[1:]:
            assert statuses[key].endswith("— ready."), (key, statuses[key])
            assert not [w for w in _walk(app.containers[key]) if isinstance(w, tk.Text)
                        and "Could not load" in w.get("1.0", "end")], key
    finally:
        for child in tk_root.winfo_children():
            child.destroy()
        settings.invalidate()


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)
