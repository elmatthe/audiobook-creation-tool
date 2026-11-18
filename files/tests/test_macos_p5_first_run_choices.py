"""v0.8.0 P5-F -- the macOS counterpart of ``setup.first-run-choices-and-cancel`` cannot PASS on a wrong root or interpreter, a wrong
roster or default, a text cut at an edge, missing evidence, an unapproved setup activity, the wrong exit status, a leftover process
or a changed copy, bystander or checkout.

Pure tests of ``helpers/first_run_journey.py`` (what the journey decides with), of the journey's wiring, of the setup launcher's
tripwires (run headless, no window) and of the map as it stands, on every platform that has them: no desktop, no installation, nothing
deleted. The positive control asks a real disposable copy of the committed code, in ``tmp_path``, where setup would write; every
negative control changes one fact and must be refused.
"""

from __future__ import annotations

import copy as copier
import inspect
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gate_locator import GATE_DIR, REPO_ROOT

sys.path.insert(0, str(GATE_DIR))
from helpers import acceptance_report as ar  # noqa: E402
from helpers import first_run_journey as frj  # noqa: E402

sys.path.remove(str(GATE_DIR))

SCENARIO = "setup.first-run-choices-and-cancel"
BASE_PYTHON = REPO_ROOT / "files" / "runtime-data" / "python" / "bin" / "python3.12"


# --------------------------------------------------------------------------------------------------------------------- #
#  Isolation: the preflight
# --------------------------------------------------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """A disposable copy of the committed ``scripts/`` in a scratch folder, and what its own code says about it. The facts the probe
    would give on the app's base Python are rebuilt here from the copy's own code on this interpreter, with the interpreter's path
    pinned to where a first run's lives, so the isolation rules are judged on a real copy without needing that interpreter."""
    work = Path(os.path.realpath(tmp_path_factory.mktemp("frc")))
    copy = work / "copy" / "app"
    listed = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--", "scripts"], capture_output=True, check=True).stdout
    for name in [item for item in listed.decode("utf-8").split("\0") if item]:
        (copy / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / name, copy / name)
    env = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "PYTHONHOME")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    facts = frj.copy_facts(copy, python=sys.executable, env=env)
    interpreter = REPO_ROOT / "files" / "runtime-data" / "python" / "bin" / "python3.12"
    facts = {**facts, "platform": "darwin", "probe_interpreter": str(interpreter), "probe_is_a_venv": False}
    protected = frj.protected_locations(REPO_ROOT, home=work / "home")
    protected["runtime_data"] = REPO_ROOT / "files" / "runtime-data"
    return {"work": work, "copy": copy, "facts": facts, "interpreter": interpreter, "protected": protected}


def judge(world, *, facts=None, copy=None, scratch=None, links=None, real_root=REPO_ROOT, interpreter=None):
    """The preflight's verdict. ``is_file`` is not what these tests are about, so a real file stands in for the interpreter when the
    app's own base Python is not on this machine (a CI box); where it is, the real one is judged."""
    chosen = Path(interpreter or world["interpreter"])
    return frj.isolation_problems(facts if facts is not None else world["facts"], copy=copy or world["copy"],
                                  scratch=scratch or world["work"], real_root=real_root, protected=world["protected"],
                                  interpreter=chosen, links={} if links is None else links)


def with_fact(world, **changes):
    return {**json.loads(json.dumps(world["facts"])), **changes}


def without_the_interpreter_file(problems):
    return [item for item in problems if "does not exist" not in item]


def test_a_real_copy_names_only_itself_and_runs_on_the_apps_own_base_python(world):
    facts = world["facts"]
    assert Path(facts["repo_root"]) == world["copy"] and Path(facts["bootstrap_module"]) == world["copy"] / "scripts" / "shared" / "bootstrap.py"
    assert without_the_interpreter_file(judge(world)) == []


def test_a_root_or_setup_code_that_is_not_the_copys_is_refused(world):
    assert any("says its root is" in p for p in judge(world, facts=with_fact(world, repo_root=str(REPO_ROOT))))
    real_bootstrap = str(REPO_ROOT / "scripts" / "shared" / "bootstrap.py")
    assert any("not the copy's own bootstrap.py" in p for p in judge(world, facts=with_fact(world, bootstrap_module=real_bootstrap)))


@pytest.mark.parametrize("name", ["virtual_environment", "portable_binaries", "runtime_data", "logs", "app_python"])
def test_every_mutable_path_in_the_real_checkout_is_refused(world, name):
    real = {"virtual_environment": REPO_ROOT / ".venv", "portable_binaries": REPO_ROOT / "files" / "bin",
            "runtime_data": REPO_ROOT / "files" / "runtime-data", "logs": REPO_ROOT / "files" / "runtime-data" / "logs",
            "app_python": REPO_ROOT / "files" / "runtime-data" / "python" / "bin" / "python3.12"}[name]
    mutable = {**world["facts"]["mutable"], name: str(real)}
    problems = judge(world, facts=with_fact(world, mutable=mutable))
    assert any(name in p and ("is not the copy's own" in p or "inside the real checkout" in p) for p in problems), problems


def test_a_missing_mutable_path_is_refused(world):
    mutable = {key: value for key, value in world["facts"]["mutable"].items() if key != "logs"}
    assert any("logs" in p and "named no folder" in p for p in judge(world, facts=with_fact(world, mutable=mutable)))


def test_a_copy_outside_the_scratch_or_overlapping_the_checkout_or_behind_a_link_is_refused(world, tmp_path):
    assert any("not inside the gate's scratch" in p for p in judge(world, scratch=world["work"] / "elsewhere"))
    assert any("overlaps" in p for p in judge(world, real_root=world["copy"].parent))
    redirected = tmp_path / "redirect"
    try:
        redirected.symlink_to(world["copy"].parent)
    except OSError:  # a Windows account without the right to make links: the other two refusals above are still judged
        pytest.skip("cannot make a symbolic link here")
    behind = redirected / "app"
    assert any("goes through a link" in p for p in judge(world, copy=behind, scratch=tmp_path))


def test_any_link_in_the_copy_is_refused_before_launch(world):
    problems = judge(world, links={"scripts/shared/escape": str(REPO_ROOT / "files")})
    assert any("holds a link before anything runs" in p for p in problems)
    assert any("holds a link" in p for p in judge(world, links={"files/runtime-data/models": "/tmp/anywhere"}))


def test_an_interpreter_that_is_not_the_apps_own_base_python_is_refused(world):
    inside_copy = world["copy"] / "files" / "runtime-data" / "python" / "bin" / "python3.12"
    assert any("inside the copy" in p or "not the app's own base Python" in p for p in judge(world, interpreter=inside_copy))
    venv = REPO_ROOT / ".venv" / "bin" / "python"
    problems = judge(world, interpreter=venv)
    assert any("not the app's own base Python" in p for p in problems) and any("cleanup target" in p for p in problems)
    assert any("not the app's own base Python" in p for p in judge(world, interpreter=Path(sys.executable)))
    assert any("not the app's own base Python" in p for p in judge(world, interpreter=Path("/usr/bin/python3")))


def test_each_rule_holds_on_its_own_not_only_through_an_overlapping_one(world):
    """Rules that overlap are each held to a case only they can refuse: with the copy standing in as the checkout, its own paths are
    "inside the real checkout" and an interpreter under its runtime-data is "inside the copy" -- while still the right place for a base."""
    copy = world["copy"]
    as_checkout = judge(world, real_root=copy, interpreter=copy / "files" / "runtime-data" / "python" / "bin" / "python3.12")
    assert any("inside the real checkout" in p for p in as_checkout), as_checkout
    assert any("is inside the copy, which setup writes into" in p for p in as_checkout), as_checkout


def test_a_probe_on_another_interpreter_or_in_a_venv_or_as_another_platform_is_refused(world):
    assert any("not the interpreter the window will use" in p for p in judge(world, facts=with_fact(world, probe_interpreter="/usr/bin/python3")))
    assert any("virtual environment" in p for p in judge(world, facts=with_fact(world, probe_is_a_venv=True)))
    assert any("not as a Mac" in p for p in judge(world, facts=with_fact(world, platform="win32")))


# --------------------------------------------------------------------------------------------------------------------- #
#  The roster and the defaults
# --------------------------------------------------------------------------------------------------------------------- #
KOKORO_NOTE = "Natural English voices that run on this computer (CPU or GPU)."
OMNI_NOTE = ("Six more cloned voices from a separate engine, on this Mac's GPU (Apple Silicon). NON-COMMERCIAL: the model weights are "
             "CC-BY-NC and its audio tokenizer has its own licence; the full terms are shown before anything is downloaded.")


def shown(boxes=None, labels=None):
    boxes = boxes if boxes is not None else [{"text": "Kokoro voices (up to 344.7 MB)", "selected": True, "y": 100},
                                             {"text": "OmniVoice — Six Cloned Voices (up to 3.5 GB)", "selected": False, "y": 160}]
    labels = labels if labels is not None else [{"text": "Welcome", "y": 10}, {"text": KOKORO_NOTE, "y": 120}, {"text": OMNI_NOTE, "y": 180}]
    return boxes, labels


def test_the_approved_mac_roster_passes():
    assert frj.roster_problems(*shown()) == []
    assert not any(frj.roster_findings(*shown()).values())


def test_the_roster_agrees_with_the_copys_own_code_and_figures(world):
    from shared import bootstrap

    facts = {"choices": [[c, label, d, n] for c, label, d, n in bootstrap.optional_choices_for("darwin")], "offered": ["kokoro", "omnivoice"],
             "estimates": {"kokoro": "344.7 MB", "omnivoice": "3.5 GB"}}
    assert frj.roster_problems(*shown(), facts=facts) == []
    assert any("estimate" in p for p in frj.roster_problems(*shown(), facts={**facts, "estimates": {"kokoro": "344.7 MB", "omnivoice": "6.9 GB"}}))
    assert any("engine policy offers" in p for p in frj.roster_problems(*shown(), facts={**facts, "offered": ["kokoro", "chatterbox", "omnivoice"]}))
    windows = [[c, label, d, n] for c, label, d, n in bootstrap.optional_choices_for("win32")]
    assert any("offers" in p for p in frj.roster_problems(*shown(), facts={**facts, "choices": windows}))


@pytest.mark.parametrize("extra", ["Chatterbox Turbo voices (up to 4.9 GB)", "Qwen3 CustomVoice voices (Aiden, Ryan) (up to 4 GB)",
                                   "Qwen3 Cloned Voices (six bundled voices) (up to 4 GB)"])
def test_a_choice_a_mac_does_not_offer_cannot_pass(extra):
    boxes, labels = shown()
    boxes.append({"text": extra, "selected": False, "y": 220})
    found = frj.roster_findings(boxes, labels)
    assert found["choices"] and found["absent"], found


def test_a_note_that_names_another_engine_or_platform_cannot_pass():
    boxes, labels = shown()
    labels[1] = {"text": "Both Qwen3 choices share one voice engine (about 3.1 GB).", "y": 120}
    assert frj.roster_findings(boxes, labels)["absent"]
    boxes, labels = shown()
    labels[2] = {"text": OMNI_NOTE.replace("this Mac's GPU (Apple Silicon)", "Windows with an NVIDIA GPU"), "y": 180}
    found = frj.roster_findings(boxes, labels)
    assert found["absent"] and found["descriptions"]


def test_a_wrong_order_or_missing_choice_cannot_pass():
    boxes, labels = shown()
    swapped = [{**boxes[1], "y": 100}, {**boxes[0], "y": 160}]
    assert frj.roster_findings(swapped, labels)["choices"]
    assert frj.roster_findings(boxes[:1], labels)["choices"]
    assert frj.roster_findings([], labels)["choices"]


@pytest.mark.parametrize("kokoro,omni", [(False, False), (True, True), (False, True)])
def test_a_wrong_default_cannot_pass(kokoro, omni):
    boxes, labels = shown()
    boxes[0]["selected"], boxes[1]["selected"] = kokoro, omni
    assert frj.roster_findings(boxes, labels)["defaults"]


def test_a_wrong_or_missing_estimate_cannot_pass():
    boxes, labels = shown()
    boxes[0]["text"] = "Kokoro voices"
    assert frj.roster_findings(boxes, labels)["estimates"]
    boxes, labels = shown()
    boxes[1]["text"] = "OmniVoice — Six Cloned Voices (up to 6.9 GB)"
    assert frj.roster_findings(boxes, labels)["estimates"]


@pytest.mark.parametrize("missing", ["NON-COMMERCIAL", "CC-BY-NC", "audio tokenizer has its own licence",
                                     "full terms are shown before anything is downloaded", "Apple Silicon"])
def test_an_omnivoice_note_without_its_licensing_disclosure_cannot_pass(missing):
    boxes, labels = shown()
    labels[2] = {"text": OMNI_NOTE.replace(missing, "").replace("  ", " "), "y": 180}
    assert any(missing in line for line in frj.roster_findings(boxes, labels)["descriptions"])


# --------------------------------------------------------------------------------------------------------------------- #
#  Clicks, geometry and text
# --------------------------------------------------------------------------------------------------------------------- #
def test_a_click_that_changed_the_wrong_box_or_none_cannot_pass():
    assert frj.selection_problems([False, False], [False, False], step="Kokoro") == []
    assert frj.selection_problems([True, False], [False, False], step="Kokoro")
    assert frj.selection_problems([False, True], [False, False], step="Kokoro")


def test_a_click_that_changed_another_control_cannot_pass():
    widget = {"path": ".b", "class": "TButton", "text": "Begin Setup", "disabled": False, "viewable": True}
    box = {"path": ".c", "class": "TCheckbutton", "text": "Kokoro", "disabled": False, "viewable": True, "selected": True}
    before = frj.window_signature([widget, box])
    assert frj.unrelated_problems(before, frj.window_signature([widget, {**box, "selected": False}]), step="x") == [], "its own state"
    assert frj.unrelated_problems(before, frj.window_signature([{**widget, "disabled": True}, box]), step="x")
    assert frj.unrelated_problems(before, frj.window_signature([{**widget, "text": "Install"}, box]), step="x")
    assert frj.unrelated_problems(before, frj.window_signature([box]), step="x")
    assert frj.unrelated_problems(before, frj.window_signature([widget, box, {**widget, "path": ".new"}]), step="x")


def _widgets():
    def item(cls, text, x, y, width, height):
        return {"class": cls, "text": text, "x": x, "y": y, "width": width, "height": height, "viewable": True, "disabled": False}

    return [item("TCheckbutton", "Kokoro", 52, 277, 213, 20), item("TLabel", "note", 74, 297, 500, 20),
            item("TCheckbutton", "OmniVoice", 52, 329, 303, 20), item("TLabel", "licence", 74, 349, 500, 52),
            item("TButton", "Cancel", 520, 520, 82, 28), item("TButton", "Begin Setup", 400, 520, 114, 28)]


WINDOW = {"x": 34, "y": 95, "width": 660, "height": 600}


def test_a_window_with_everything_inside_passes():
    inside = [{**w, "x": w["x"] + 34, "y": w["y"] + 95} for w in _widgets()]
    assert frj.geometry_problems(WINDOW, inside, size=(660, 600)) == []


def test_a_control_or_label_outside_the_window_cannot_pass():
    inside = [{**w, "x": w["x"] + 34, "y": w["y"] + 95} for w in _widgets()]
    for index in (0, 3, 4):
        moved = copier.deepcopy(inside)
        moved[index]["x"] = WINDOW["x"] + WINDOW["width"] - 10
        assert any("outside the window" in p for p in frj.geometry_problems(WINDOW, moved, size=(660, 600))), index
    low = copier.deepcopy(inside)
    low[5]["y"] = WINDOW["y"] + WINDOW["height"] - 5
    assert any("outside the window" in p for p in frj.geometry_problems(WINDOW, low, size=(660, 600)))


def test_overlapping_unusable_or_missing_controls_and_a_wrong_size_cannot_pass():
    inside = [{**w, "x": w["x"] + 34, "y": w["y"] + 95} for w in _widgets()]
    overlap = copier.deepcopy(inside)
    overlap[4]["x"], overlap[4]["y"] = overlap[5]["x"] + 10, overlap[5]["y"]
    assert any("overlaps" in p for p in frj.geometry_problems(WINDOW, overlap, size=(660, 600)))
    disabled = copier.deepcopy(inside)
    disabled[4]["disabled"] = True
    assert any("cannot be used" in p for p in frj.geometry_problems(WINDOW, disabled, size=(660, 600)))
    assert any("only 3 controls" in p for p in frj.geometry_problems(WINDOW, inside[:1] + inside[4:], size=(660, 600)))
    assert any("not 700x600" in p for p in frj.geometry_problems(WINDOW, inside, size=(700, 600)))


def test_a_label_that_lost_the_end_of_a_line_or_a_line_cannot_pass():
    """The case the picture review cannot see: the licence line given 602 px when its widest line needed 611 (found natively at 660x600)."""
    good = {"text": "Six more cloned voices", "wraplength": 612, "width": 602, "reqwidth": 600, "height": 52, "reqheight": 52}
    assert frj.text_clip_problems([good]) == []
    assert frj.text_clip_problems([{**good, "reqwidth": 611}]) and "cut by 9 px" in frj.text_clip_problems([{**good, "reqwidth": 611}])[0]
    assert frj.text_clip_problems([{**good, "reqheight": 68}])
    assert frj.text_clip_problems([{**good, "reqwidth": 603}]) == [], "one pixel is Tk's own rounding"


# --------------------------------------------------------------------------------------------------------------------- #
#  What the process did: nothing, and 2
# --------------------------------------------------------------------------------------------------------------------- #
QUIET = [{"kind": "started"}, {"kind": "exit", "code": 2}]
EXITED = {"exited": True, "exit_status": 2, "windows_after": [], "orphans": [], "groups_occupied": [], "tk_off_thread": [], "stderr_tail": ""}
STATUS = {"succeeded": 0, "failed": 1, "cancelled_before_begin": 2}


def test_a_window_that_only_started_and_exited_passes():
    assert frj.activity_problems(QUIET, []) == []


@pytest.mark.parametrize("kind", ["run-setup-called", "launch-gui", "open-folder", "startfile", "network-attempt"])
def test_any_setup_launch_folder_or_network_activity_cannot_pass(kind):
    assert any(kind in p for p in frj.activity_problems([QUIET[0], {"kind": kind}, QUIET[1]], []))


def test_a_child_process_or_a_missing_start_or_exit_cannot_pass():
    assert any("child process: pip" in p for p in frj.activity_problems(QUIET, [{"program": "pip", "pid": 9}]))
    assert any("one start and one exit" in p for p in frj.activity_problems([QUIET[0]], []))
    assert any("one start and one exit" in p for p in frj.activity_problems([QUIET[0], QUIET[1], QUIET[1]], []))


def test_the_cancellation_status_passes_and_nothing_else_does():
    assert frj.exit_problems(EXITED, QUIET, status_map=STATUS) == []
    for status in (0, 1, 3, -9, None):
        assert frj.exit_problems({**EXITED, "exit_status": status}, QUIET, status_map=STATUS), status
    assert any("completed installation" in p for p in frj.exit_problems({**EXITED, "exit_status": 0}, QUIET))
    assert any("failed setup" in p for p in frj.exit_problems({**EXITED, "exit_status": 1}, QUIET))


def test_an_exit_the_window_recorded_differently_or_not_at_all_cannot_pass():
    assert any("own record" in p for p in frj.exit_problems(EXITED, [QUIET[0], {"kind": "exit", "code": 1}], status_map=STATUS))
    assert any("own record" in p for p in frj.exit_problems(EXITED, [QUIET[0]], status_map=STATUS))
    assert any("did not exit" in p for p in frj.exit_problems({**EXITED, "exited": False}, QUIET))


def test_production_statuses_that_are_not_distinct_or_not_the_cancel_status_cannot_pass():
    assert any("not distinct" in p for p in frj.exit_problems(EXITED, QUIET, status_map={**STATUS, "failed": 2}))
    assert any("maps a cancel" in p for p in frj.exit_problems(EXITED, QUIET, status_map={**STATUS, "cancelled_before_begin": 1}))


def test_a_status_the_real_production_function_gives_is_the_one_the_journey_expects():
    from shared import bootstrap

    assert bootstrap.setup_exit_code(started=False, done=False, ok=False) == frj.CANCELLED_STATUS == bootstrap.EXIT_SETUP_CANCELLED
    assert bootstrap.setup_exit_code(started=True, done=True, ok=True) != frj.CANCELLED_STATUS
    assert bootstrap.setup_exit_code(started=True, done=True, ok=False) != frj.CANCELLED_STATUS


def test_nothing_may_be_left_running():
    assert frj.leftover_problems(EXITED, still_running=[], occupied_groups=[], processes=[]) == []
    cases = [({**EXITED, "windows_after": [{"title": "Setup"}]}, [], [], []), ({**EXITED, "orphans": [{"pid": 7}]}, [], [], []),
             (EXITED, [123], [], []), (EXITED, [], [4242], []), ({**EXITED, "tk_off_thread": [{"call": "update"}]}, [], [], []),
             ({**EXITED, "stderr_tail": "Traceback (most recent call last)"}, [], [], []),
             (EXITED, [], [], ["123 123 /x/python3.12 -I -B /scratch/copy/app/helper.py"])]
    for facts, running, groups, processes in cases:
        assert frj.leftover_problems(facts, still_running=running, occupied_groups=groups, processes=processes), facts


# --------------------------------------------------------------------------------------------------------------------- #
#  What changed on disk
# --------------------------------------------------------------------------------------------------------------------- #
BEFORE = {"scripts/launcher.py": "sha256:1", "scripts/shared/bootstrap.py": "sha256:2", "config.toml": "sha256:3"}
LOG = "files/runtime-data/logs/setup_2026-11-18.log"


def test_an_untouched_copy_passes_and_so_does_its_own_dated_setup_log():
    assert frj.outcome_problems(BEFORE, dict(BEFORE)) == []
    assert frj.outcome_problems(BEFORE, {**BEFORE, LOG: "sha256:9"}, log_texts={LOG: "===== Setup run =====\nRepo root: /x\n"}) == []


def test_a_changed_or_removed_entry_of_the_copy_cannot_pass():
    assert any("changed" in p for p in frj.outcome_problems(BEFORE, {**BEFORE, "config.toml": "sha256:x"}))
    assert any("removed" in p for p in frj.outcome_problems(BEFORE, {k: v for k, v in BEFORE.items() if k != "config.toml"}))


@pytest.mark.parametrize("new", [".venv/pyvenv.cfg", ".venv/", "files/bin/ffmpeg", "files/runtime-data/models/huggingface/x",
                                 "files/runtime-data/python-packages/a.whl", "files/runtime-data/nltk_data/t", "files/runtime-data/python/bin/python3.12",
                                 "files/runtime-data/settings.json", "files/runtime-data/optional-setup/plan.json", "files/surprise.txt",
                                 "files/runtime-data/logs/other.log", "files/runtime-data/logs/setup_2026-11-18.log.bak"])
def test_anything_new_but_the_dated_setup_log_cannot_pass(new):
    assert frj.outcome_problems(BEFORE, {**BEFORE, new: "sha256:9"}), new


def test_a_setup_log_that_names_a_step_or_more_than_one_log_cannot_pass():
    for text in ("Downloading torch", "pip install -r requirements.txt", "Installing the package"):
        assert any("names a step" in p for p in frj.outcome_problems(BEFORE, {**BEFORE, LOG: "sha256:9"}, log_texts={LOG: text})), text
    two = {**BEFORE, LOG: "sha256:9", "files/runtime-data/logs/setup_2026-11-19.log": "sha256:8"}
    assert any("more than one" in p for p in frj.outcome_problems(BEFORE, two, log_texts={LOG: "x", "files/runtime-data/logs/setup_2026-11-19.log": "x"}))
    assert any("was not read" in p for p in frj.outcome_problems(BEFORE, {**BEFORE, LOG: "sha256:9"}))


def test_a_copy_that_already_holds_an_installation_is_not_a_first_run_copy():
    """Unchanged is not enough: an environment, binaries or models that were there before the window opened mean the copy is not the
    fresh installation this journey claims to cancel, so even an identical before and after is refused."""
    for present in (".venv/pyvenv.cfg", "files/bin/ffmpeg", "files/runtime-data/models/x"):
        seeded = {**BEFORE, present: "sha256:7"}
        assert any("exists in the copy" in p for p in frj.outcome_problems(seeded, dict(seeded))), present


def test_a_changed_bystander_or_checkout_cannot_pass():
    assert frj.tree_problems("the bystander", {"a": "sha256:1"}, {"a": "sha256:1"}) == []
    assert frj.tree_problems("the bystander", {"a": "sha256:1"}, {"a": "sha256:2"})
    assert frj.tree_problems("the bystander", {"a": "sha256:1"}, {"a": "sha256:1", "b": "sha256:2"})
    assert frj.tree_problems("the real checkout", {"environment": "tree:1", "settings": None}, {"environment": "tree:2", "settings": None})
    assert frj.tree_problems("the real checkout", {"settings": None}, {"settings": "sha256:7"})


def test_the_protected_locations_include_the_environment_models_logs_settings_code_and_outputs(tmp_path):
    protected = frj.protected_locations(REPO_ROOT, home=tmp_path)
    assert set(protected) == {"environment", "portable_binaries", "models", "logs", "settings", "code", "default_outputs"}
    assert protected["environment"] == REPO_ROOT / ".venv" and protected["code"] == REPO_ROOT / "scripts"


# --------------------------------------------------------------------------------------------------------------------- #
#  Evidence: what a PASS must carry
# --------------------------------------------------------------------------------------------------------------------- #
def _complete_entry() -> dict:
    names = ["isolation preflight: x", "the real first-run window: x", "exactly two choices: x", "approved estimates: x",
             "licensing disclosure and descriptions: x", "no engine a Mac does not offer: x", "default: x", "a real click changes only: x",
             "restored to their defaults: x", "at 660x600: every control is wholly on screen", "at 660x600: no text is cut",
             "Cancel before Begin Setup: x", "cancelled, not failed: x", "nothing was started: x", "no owned process: x",
             "the copy is byte-identical: x", "a second installation: x", "the real checkout's data: x"]
    return {"checks": [{"name": name, "ok": True} for name in names],
            "screenshots": [{"name": f"{name}.png", "captured": True, "review": "PASS"} for name in frj.REQUIRED_PICTURES]}


def test_a_complete_entry_passes_and_each_missing_check_or_picture_cannot():
    entry = _complete_entry()
    assert frj.entry_problems(entry) == []
    for needle in frj.REQUIRED_CHECKS:
        trimmed = {**entry, "checks": [c for c in entry["checks"] if needle not in c["name"]]}
        assert any(needle in p for p in frj.entry_problems(trimmed)), needle
        failed = {**entry, "checks": [{**c, "ok": False} if needle in c["name"] else c for c in entry["checks"]]}
        assert any("failed" in p for p in frj.entry_problems(failed)), needle
    for name in frj.REQUIRED_PICTURES:
        assert any(name in p for p in frj.entry_problems({**entry, "screenshots": [s for s in entry["screenshots"] if s["name"] != f"{name}.png"]}))
        assert any(name in p for p in frj.entry_problems({**entry, "screenshots": [{**s, "review": "FAIL"} if s["name"] == f"{name}.png" else s
                                                                                    for s in entry["screenshots"]]}))


SHA = "b" * 40


def _entry(**changes) -> dict:
    return {"id": SCENARIO, "status": "PASS", "layers": ["native", "visual"], "tier": "geometry", "sessions": ["setup"], "native_inputs": 5,
            "checks": [{"name": "isolation preflight", "ok": True}], "screenshots": [], "notes": {"exits": []}, **changes}


def _with_actions(tmp_path: Path) -> Path:
    (tmp_path / SCENARIO).mkdir(parents=True, exist_ok=True)
    (tmp_path / SCENARIO / "setup-actions.jsonl").write_text(json.dumps({"kind": "input", "action": "click"}) + "\n", encoding="utf-8")
    return tmp_path


def test_the_judge_refuses_a_pass_without_a_picture_a_failed_check_input_or_a_worker_thread_call(tmp_path):
    root = _with_actions(tmp_path)
    required = ("journey-checks", "real-screenshots")
    assert any("no picture" in p for p in ar._darwin_evidence_problems(_entry(), root, required, SHA))
    assert any("failed checks" in p for p in ar._darwin_evidence_problems(_entry(checks=[{"name": "x", "ok": False}]), root, ("journey-checks",), SHA))
    assert any("no real input" in p for p in ar._darwin_evidence_problems(_entry(native_inputs=0), root, ("journey-checks",), SHA))
    off = _entry(notes={"exits": [{"tk_off_thread": [{"call": "update"}]}]})
    assert any("worker thread called Tk" in p for p in ar._darwin_evidence_problems(off, root, ("journey-checks",), SHA))


def test_dialog_contract_cannot_be_claimed_by_a_journey_that_answers_no_file_dialog(tmp_path):
    """Cancel before Begin Setup answers no file or folder dialog, so its map entry names journey checks and real pictures only."""
    problems = ar._darwin_evidence_problems(_entry(), _with_actions(tmp_path), ("dialog-contract",), SHA)
    assert any("answered no file or folder dialog" in p for p in problems)


# --------------------------------------------------------------------------------------------------------------------- #
#  The journey's wiring, and the launcher's tripwires
# --------------------------------------------------------------------------------------------------------------------- #
def _journeys_setup():
    sys.path.insert(0, str(GATE_DIR))
    try:
        from journeys import setup
    finally:
        sys.path.remove(str(GATE_DIR))
    return setup


def test_the_journey_dispatches_to_the_mac_branch_and_names_every_check_and_picture_a_pass_requires():
    setup = _journeys_setup()
    assert "first_run_cancel_macos(context)" in inspect.getsource(setup.first_run_cancel)
    assert "sys.platform == \"darwin\"" in inspect.getsource(setup.first_run_cancel)
    source = inspect.getsource(setup.first_run_cancel_macos)
    for needle in frj.REQUIRED_CHECKS:
        assert needle in source, f"the journey has no check naming {needle!r}, so entry_problems would always refuse its PASS"
    assert 'screenshot("first-run-choices")' in source and 'screenshot("first-run-both-ticked")' in source
    assert 'screenshot(f"first-run-{size[0]}x{size[1]}")' in source, "one picture per size"
    sized = {name for name in frj.REQUIRED_PICTURES if name not in ("first-run-choices", "first-run-both-ticked")}
    assert sized == {f"first-run-{w}x{h}" for w, h in setup.MACOS_SIZES}, "a size the journey shows is a picture a PASS must carry"
    assert (660, 600) in setup.MACOS_SIZES and (760, 680) in setup.MACOS_SIZES, "the window's minimum and its opening size are both shown"


def test_the_journey_never_presses_begin_setup():
    setup = _journeys_setup()
    source = inspect.getsource(setup.first_run_cancel_macos)
    pressed = [line.strip() for line in source.splitlines() if "press(" in line and not line.strip().startswith(("def press", '"""'))]
    allowed = {"press(box_named(label))", 'press(one(session, "TButton", "Cancel"))'}
    assert pressed and set(pressed) <= allowed, f"the journey presses only a voice box and Cancel: {pressed}"
    assert "Begin Setup" in source, "it is looked for (still offered, enabled), never pressed"


def test_the_windows_body_of_the_journey_is_unchanged_by_the_mac_branch():
    setup = _journeys_setup()
    source = inspect.getsource(setup.first_run_cancel)
    assert "start_setup(context, copy, \"setup\")" in source and "SETUP_LAUNCHER" in inspect.getsource(setup.start_setup)
    assert "MACOS_SETUP_LAUNCHER" not in inspect.getsource(setup.start_setup)


@pytest.mark.skipif(sys.platform != "darwin" or not BASE_PYTHON.is_file(), reason="the launcher loads the macOS adapter on the app's base Python")
def test_the_setup_launchers_tripwires_record_and_refuse_without_a_window(tmp_path):
    """Run the launcher's own setup with its window start replaced by deliberate attempts: the install, a connection to an unroutable
    address, a name lookup and a folder reveal. Each must be refused and recorded; nothing is installed or reached."""
    work = Path(os.path.realpath(tmp_path))
    setup = _journeys_setup()
    app = setup.make_copy(work / "copy" / "app")
    launcher = (GATE_DIR / "adapters" / "macos" / "setup_launcher.py").read_text(encoding="utf-8")
    here = str(GATE_DIR / "adapters" / "macos")
    launcher = launcher.replace("HERE = Path(__file__).resolve().parent\nREPO_ROOT = HERE.parents[4]",
                                f"HERE = Path({here!r})\nREPO_ROOT = HERE.parents[4]")
    start = "    tk.Tk = ObservedTk\n    code = bootstrap.run_with_gui()\n    note(\"exit\", code=code)\n    return code\n"
    assert launcher.count(start) == 1
    attempts = ("    import socket as _s\n    for attempt in (lambda: _s.create_connection(('192.0.2.1', 80), timeout=1),\n"
                "                    lambda: _s.getaddrinfo('example.invalid', 80), lambda: bootstrap.run_setup(None, None),\n"
                "                    lambda: bootstrap._open_folder(Path('/tmp')), lambda: bootstrap.launch_gui(None)):\n"
                "        try:\n            attempt()\n        except BaseException as exc:\n            print('refused', type(exc).__name__)\n"
                "    return 0\n")
    path = work / "tripwires.py"
    path.write_text(launcher.replace(start, attempts), encoding="utf-8")
    config = {"app_root": str(app), "record": str(work / "record.jsonl"), "runtime_dir": str(work / "w" / "runtime"),
              "channel_file": str(work / "channel.json"), "pictures_dir": str(work / "pictures")}
    (work / "w").mkdir()
    (work / "config.json").write_text(json.dumps(config), encoding="utf-8")
    done = subprocess.run([str(BASE_PYTHON), "-I", "-B", str(path), str(work / "config.json")], capture_output=True, text=True, timeout=120,
                          cwd=str(work / "w"))
    assert done.returncode == 0, done.stderr[-800:]
    kinds = [json.loads(line)["kind"] for line in (work / "record.jsonl").read_text(encoding="utf-8").splitlines()]
    assert kinds[0] == "started" and "run-setup-called" in kinds and "open-folder" in kinds and "launch-gui" in kinds
    assert kinds.count("network-attempt") == 2, kinds
    assert done.stdout.count("refused") == 3, "the install and the two network attempts are refused; the two stand-ins only record"
    assert not (app / ".venv").exists() and not (app / "files").exists()
    assert frj.activity_problems([{"kind": k} for k in kinds] + [{"kind": "exit", "code": 2}], []), "and the judge refuses that record"


# --------------------------------------------------------------------------------------------------------------------- #
#  The map: this scenario stays pending until a genuine native PASS on the committed code
# --------------------------------------------------------------------------------------------------------------------- #
POLICY = json.loads((GATE_DIR / "verification.json").read_text(encoding="utf-8"))
DARWIN = POLICY["acceptance"]["darwin_map"]


def test_the_scenario_is_a_registered_journey_with_a_mac_branch_and_a_darwin_map_entry():
    sys.path.insert(0, str(GATE_DIR))
    try:
        import acceptance_runner

        scenarios = acceptance_runner.load_scenarios()
    finally:
        sys.path.remove(str(GATE_DIR))
    assert SCENARIO in scenarios and scenarios[SCENARIO].tool == "setup"
    entry = DARWIN[SCENARIO]
    assert entry["class"] == "automated" and entry["journey"] == SCENARIO and entry["driver"] == "adapters/macos"


def test_a_pending_scenario_is_reported_not_run_and_is_not_an_automated_pass(tmp_path):
    """Until its native run PASSES on the committed code, the runner reports NOT RUN and the darwin judge refuses it."""
    from types import SimpleNamespace

    sys.path.insert(0, str(GATE_DIR))
    try:
        import acceptance_runner
    finally:
        sys.path.remove(str(GATE_DIR))
    entry = DARWIN[SCENARIO]
    if not entry.get("pending_phase"):
        pytest.skip("the scenario has completed: the transition tests own it now")
    shape = SimpleNamespace(id=SCENARIO, tool="setup", layers=("native", "visual"), tier="geometry", summary="")
    assert acceptance_runner._not_run_on_macos(shape, entry)["status"] == "NOT RUN"
    required, optional = POLICY["acceptance"]["required_scenarios"], POLICY["acceptance"]["optional_scenarios"]
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"schema_version": 1, "token": "t", "finished": True, "registered": required + optional,
                                  "scenarios": [_entry()], "unknown": []}), encoding="utf-8")
    verdict = ar.judge_darwin(report, token="t", wanted=[SCENARIO], required=required, optional=optional,
                              evidence_root=_with_actions(tmp_path / "evidence"), returncode=0, ended="exited", darwin_map=DARWIN,
                              manual_evidence=None, sha=SHA)
    assert verdict.status != "PASS", "even a PASS entry is not an automated pass while the map says pending"


def test_the_pending_set_is_the_two_first_run_journeys():
    pending = {sid: entry["pending_phase"] for sid, entry in DARWIN.items() if entry.get("pending_phase")}
    assert pending == {"setup.first-run-refuses-a-folder-too-deep": "P5", "setup.first-run-choices-and-cancel": "P5"}
