"""v0.7.0 P04A — the candidate nested layout's isolation and identity contract (plan Revision 2 §5.5).

The candidate is ``.venv/engines/qwen3/``: an independent environment held inside the app's own. **It is not
adopted.** These tests prove, with tiny real environments built from the base interpreter (``--without-pip``, about
a tenth of a second each) and with synthetic folders, what ``shared.venv_layout`` must be able to tell: that parent
and child are separate Pythons, that a child never sees the parent's packages or an ambient override, that a child
is only ever recognised at its own final path, built there, from a base interpreter whose identity was recorded and
has not changed, and that the two Qwen3 locations are named exactly.

None of this proves a real Qwen3 installation works nested; that is P04B's native proof. Every environment here is
built in ``tmp_path``. Nothing touches ``.venv`` or ``.venv-qwen3``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from shared import bootstrap
from shared import venv_layout as vl
from tts import qwen3_runtime as rt
from tts import qwen3_setup as su

from test_qwen3_runtime import make_junction, sandbox  # noqa: F401  (the sandbox fixture)

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows mechanism")

BASE_PYTHON = Path(getattr(sys, "_base_executable", sys.executable))
_PROBE = ("import json, sys; print(json.dumps({'prefix': sys.prefix, 'base_prefix': sys.base_prefix, "
          "'path': sys.path}))")


def _clean_environ() -> dict:
    env = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONSTARTUP"):
        env.pop(name, None)
    return env


def make_venv(path: Path) -> Path:
    """A real, empty environment created at its final path from the base interpreter."""
    subprocess.run([str(BASE_PYTHON), "-m", "venv", "--without-pip", str(path)], check=True,
                   capture_output=True, env=_clean_environ(), timeout=120)
    return path


def run_in(env_dir: Path, code: str, environ: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([str(vl.interpreter(env_dir)), "-c", code], capture_output=True, text=True,
                          env=_clean_environ() if environ is None else environ, timeout=60)


def probe(env_dir: Path, environ: dict | None = None) -> dict:
    result = run_in(env_dir, _PROBE, environ)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def rename(source: Path, destination: Path) -> None:
    """Rename a folder the way production does, with its bounded Windows retry.

    A just-created venv is often refused once (WinError 5, measured clearing within ~16 ms on HOME-PC), so a bare
    ``os.replace`` here would test the scanner rather than the layout.
    """
    attempts, error = bootstrap._replace_retrying(source, destination, appeared=destination.exists)
    assert error is None, f"rename refused after {attempts} attempts: {error}"


def site_packages(env_dir: Path) -> Path:
    return env_dir / ("Lib" if sys.platform == "win32" else f"lib/python{sys.version_info[0]}.{sys.version_info[1]}") \
        / "site-packages"


@pytest.fixture()
def nested(tmp_path):
    """A disposable repository root holding a real parent and a real child at the candidate path."""
    root = tmp_path / "repo"
    parent = make_venv(root / ".venv")
    child = make_venv(root.joinpath(*vl.NESTED_QWEN3.split("/")))
    # A marker package only the parent has: the probe that the child cannot see it.
    (site_packages(parent) / "parent_only_marker.py").write_text("WHO = 'parent'\n", encoding="utf-8")
    return root, parent, child


# --------------------------------------------------------------------------- #
# Independent prefixes, no package leakage
# --------------------------------------------------------------------------- #
def test_parent_and_child_are_separate_pythons_with_distinct_prefixes(nested):
    root, parent, child = nested
    p, c = probe(parent), probe(child)
    assert vl.same_path(p["prefix"], parent) and vl.same_path(c["prefix"], child)
    assert not vl.same_path(p["prefix"], c["prefix"])
    # Both stand on the base interpreter directly; the child is not stacked on the parent.
    assert vl.same_path(c["base_prefix"], p["base_prefix"])
    assert not vl.is_within(parent, c["base_prefix"])


def test_the_child_never_sees_the_parent_s_packages(nested):
    root, parent, child = nested
    assert run_in(parent, "import parent_only_marker").returncode == 0  # control: the marker is importable
    assert run_in(child, "import parent_only_marker").returncode != 0
    # The child's own folders lie inside the parent's (that is what nesting means); nothing else of the parent may.
    leaked = [entry for entry in probe(child)["path"]
              if entry and vl.is_within(parent, entry) and not vl.is_within(child, entry)]
    assert leaked == []
    assert any(vl.same_path(entry, site_packages(child)) for entry in probe(child)["path"])


def test_both_environments_are_created_without_system_site_packages(nested):
    root, parent, child = nested
    for env in (parent, child):
        assert vl.read_pyvenv_cfg(env)["include-system-site-packages"] == "false"


def test_an_ambient_pythonpath_leaks_the_parent_into_the_child_unless_the_worker_scrubs_it(nested, sandbox):
    """The negative control first: the override really does leak. Then the worker's own environment removes it."""
    root, parent, child = nested
    contaminated = {**_clean_environ(), "PYTHONPATH": str(site_packages(parent)), "VIRTUAL_ENV": str(parent),
                    "PYTHONSTARTUP": str(parent / "startup.py")}
    assert run_in(child, "import parent_only_marker", contaminated).returncode == 0  # it would leak

    scrubbed = rt.worker_environment(base=contaminated)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONSTARTUP"):
        assert name not in scrubbed
    assert scrubbed["PYTHONNOUSERSITE"] == "1"
    assert run_in(child, "import parent_only_marker", scrubbed).returncode != 0


def test_a_pythonhome_override_is_removed_before_a_child_runs(nested, sandbox):
    root, parent, child = nested
    contaminated = {**_clean_environ(), "PYTHONHOME": str(parent)}
    scrubbed = rt.worker_environment(base=contaminated)
    assert "PYTHONHOME" not in scrubbed
    assert vl.same_path(probe(child, scrubbed)["prefix"], child)


def test_pip_target_and_every_other_pip_override_are_removed_from_the_installer(sandbox, monkeypatch):
    for name, value in (("PIP_TARGET", "C:/elsewhere"), ("PIP_PREFIX", "C:/elsewhere"), ("PIP_USER", "1"),
                        ("PIP_INDEX_URL", "https://example.invalid"), ("PIP_REQUIRE_VIRTUALENV", "0")):
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PYTHONPATH", "C:/elsewhere")
    env = su.installer_environment()
    ambient = {k for k in env if k.upper().startswith("PIP_")} - {
        "PIP_CONFIG_FILE", "PIP_DISABLE_PIP_VERSION_CHECK", "PIP_NO_INPUT"}
    assert ambient == set()
    assert env["PIP_CONFIG_FILE"] == os.devnull and "PYTHONPATH" not in env


# --------------------------------------------------------------------------- #
# Identity: explicit, located, never a held or moved copy
# --------------------------------------------------------------------------- #
def _assess(child: Path, root: Path, parent: Path, recorded=None, final=None):
    return vl.assess_child(child, final_path=final or child, root=root, parent=parent,
                           recorded_base=vl.base_identity(child) if recorded is None else recorded)


def test_a_real_child_at_its_final_path_with_its_recorded_base_has_its_identity(nested):
    root, parent, child = nested
    identity = vl.base_identity(child)
    assert vl.same_path(identity["executable"], BASE_PYTHON)
    assert identity["version"] == "{}.{}.{}".format(*sys.version_info[:3])
    verdict = _assess(child, root, parent, recorded=identity)
    assert verdict.state == vl.IDENTITY_OK and verdict.identity_ok
    assert "import check is still required" in verdict.reason  # identity is not engine health


def test_a_child_carried_along_with_a_set_aside_parent_is_never_accepted_there(nested):
    """It would run (sys.prefix follows the folder), which is exactly why only identity can stop it."""
    root, parent, child = nested
    recorded = vl.base_identity(child)
    aside = root / ".venv.replaced"
    rename(parent, aside)
    held = aside / "engines" / "qwen3"
    assert vl.same_path(probe(held)["prefix"], held)  # the hazard is real: a detached copy starts
    verdict = vl.assess_child(held, final_path=child, root=root, parent=aside, recorded_base=recorded)
    assert verdict.state == vl.UNVERIFIED and "not at its own location" in verdict.reason
    # Nor is the final path, now empty, mistaken for an installation.
    assert vl.assess_child(child, final_path=child, root=root, recorded_base=recorded).state == vl.ABSENT


def test_a_child_brought_back_to_the_same_absolute_path_has_its_identity_again(nested):
    root, parent, child = nested
    recorded = vl.base_identity(child)
    aside = root / ".venv.replaced"
    rename(parent, aside)
    rename(aside, parent)
    assert _assess(child, root, parent, recorded=recorded).state == vl.IDENTITY_OK
    assert vl.same_path(probe(child)["prefix"], child)


def test_an_environment_renamed_into_the_nested_path_is_not_accepted(tmp_path):
    """What migrating ``.venv-qwen3`` by rename would produce. Environments are created at their destination."""
    root = tmp_path / "repo"
    make_venv(root / ".venv")
    legacy = make_venv(root / vl.LEGACY_QWEN3)
    final = root.joinpath(*vl.NESTED_QWEN3.split("/"))
    final.parent.mkdir(parents=True)
    rename(legacy, final)
    verdict = _assess(final, root, root / ".venv")
    assert verdict.state == vl.UNVERIFIED and "created somewhere else and moved" in verdict.reason


def test_a_child_that_sees_system_site_packages_is_broken(nested):
    root, parent, child = nested
    cfg = child / "pyvenv.cfg"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("include-system-site-packages = false",
                                                           "include-system-site-packages = true"), encoding="utf-8")
    verdict = _assess(child, root, parent)
    assert verdict.state == vl.BROKEN and "not isolated" in verdict.reason


def test_a_child_built_from_the_parent_s_interpreter_is_broken(nested):
    root, parent, child = nested
    cfg = child / "pyvenv.cfg"
    lines = [f"home = {vl.interpreter(parent).parent}" if line.startswith("home") else line
             for line in cfg.read_text(encoding="utf-8").splitlines()]
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    verdict = _assess(child, root, parent)
    assert verdict.state == vl.BROKEN and "parent environment's interpreter" in verdict.reason


@pytest.mark.parametrize("damage, state, words", [
    ("no-cfg", vl.BROKEN, "no readable pyvenv.cfg"),
    ("no-interpreter", vl.BROKEN, "interpreter is missing"),
    ("base-gone", vl.UNVERIFIED, "is missing"),
    ("not-a-folder", vl.BROKEN, "not a folder"),
])
def test_a_damaged_or_baseless_child_is_never_identity_ok(nested, damage, state, words):
    root, parent, child = nested
    recorded = vl.base_identity(child)
    cfg = child / "pyvenv.cfg"
    # Damage is built beside the fresh environment, never by deleting its files: a just-created python.exe is often
    # briefly undeletable on Windows (a scanner holds it), which would test the scanner rather than the assessment.
    if damage in ("no-cfg", "no-interpreter"):
        damaged = child.with_name(f"qwen3-{damage}")
        damaged.mkdir()
        if damage == "no-interpreter":
            (damaged / "pyvenv.cfg").write_bytes(cfg.read_bytes())
        else:
            vl.interpreter(damaged).parent.mkdir(parents=True)
            vl.interpreter(damaged).write_bytes(b"interpreter")
        child = damaged
    elif damage == "base-gone":
        gone = root / "uninstalled-python"
        cfg.write_text(f"home = {gone}\ninclude-system-site-packages = false\nversion = 3.12.10\n"
                       f"executable = {gone / 'python.exe'}\n", encoding="utf-8")
    else:
        child = child.with_name("qwen3-stray")  # a fresh venv's own python.exe may not be deletable yet
        child.write_bytes(b"stray file where the engine should be")
    verdict = vl.assess_child(child, final_path=child, root=root, parent=parent, recorded_base=recorded)
    assert verdict.state == state and words in verdict.reason


def test_an_unrecorded_base_identity_is_unverified_not_healthy(nested):
    root, parent, child = nested
    verdict = vl.assess_child(child, final_path=child, root=root, parent=parent, recorded_base=None)
    assert verdict.state == vl.UNVERIFIED and "no base-interpreter identity was recorded" in verdict.reason


@pytest.mark.parametrize("field, value", [
    ("size", -1), ("mtime_ns", 0), ("version", "3.12.9"), ("executable", "c:\\other\\python.exe"),
    ("home", "c:\\other"),
])
def test_a_changed_base_interpreter_is_unverified_not_healthy(nested, field, value):
    root, parent, child = nested
    recorded = {**vl.base_identity(child), field: value}
    verdict = _assess(child, root, parent, recorded=recorded)
    assert verdict.state == vl.UNVERIFIED and "has changed since it was installed" in verdict.reason


@windows_only
def test_a_child_reached_through_a_linked_ancestor_is_unverified(tmp_path):
    root = tmp_path / "repo"
    real_parent = make_venv(tmp_path / "elsewhere" / ".venv")
    make_venv(real_parent / "engines" / "qwen3")
    root.mkdir()
    make_junction(root / ".venv", real_parent)
    final = root.joinpath(*vl.NESTED_QWEN3.split("/"))
    verdict = vl.assess_child(final, final_path=final, root=root, recorded_base=vl.base_identity(final))
    assert verdict.state == vl.UNVERIFIED and "through a link" in verdict.reason
    assert vl.unsafe_component(root, final) == root / ".venv"


def test_a_path_outside_the_root_is_itself_the_unsafe_component(tmp_path):
    assert vl.unsafe_component(tmp_path / "repo", tmp_path / "other" / "x") == tmp_path / "other" / "x"
    assert vl.unsafe_component(tmp_path / "repo", tmp_path / "repo" / "a" / "b") is None


# --------------------------------------------------------------------------- #
# What a parent "holds"
# --------------------------------------------------------------------------- #
def test_nothing_and_an_empty_engines_folder_hold_nothing(tmp_path):
    parent = tmp_path / ".venv"
    parent.mkdir()
    assert vl.held_entries(parent) == () and not vl.holds_environments(parent)
    (parent / "engines").mkdir()
    assert vl.held_entries(parent) == () and not vl.holds_environments(parent)


@pytest.mark.parametrize("planted", ["child-env", "stray-file", "unknown-folder"])
def test_anything_under_engines_is_held_whatever_it_is(tmp_path, planted):
    parent = tmp_path / ".venv"
    engines = parent / "engines"
    engines.mkdir(parents=True)
    if planted == "child-env":
        (engines / "qwen3").mkdir()
        (engines / "qwen3" / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    elif planted == "stray-file":
        (engines / "notes.txt").write_text("x", encoding="utf-8")
    else:
        (engines / "something-else").mkdir()
    assert vl.holds_environments(parent) and vl.held_entries(parent)


def test_an_engines_entry_that_is_a_file_is_itself_held(tmp_path):
    parent = tmp_path / ".venv"
    parent.mkdir()
    (parent / "engines").write_bytes(b"x")
    assert vl.held_entries(parent) == ("engines",) and vl.holds_environments(parent)


@windows_only
def test_an_engines_junction_is_held_and_never_listed_through(tmp_path):
    parent = tmp_path / ".venv"
    parent.mkdir()
    target = tmp_path / "elsewhere"
    target.mkdir()
    make_junction(parent / "engines", target)
    assert vl.held_entries(parent) == ("engines",) and vl.holds_environments(parent)


def test_an_unreadable_engines_folder_counts_as_holding_something(tmp_path, monkeypatch):
    parent = tmp_path / ".venv"
    (parent / "engines").mkdir(parents=True)

    def refused(path):
        raise PermissionError(13, "Access is denied", str(path))

    monkeypatch.setattr(vl.os, "scandir", refused)
    assert vl.held_entries(parent) is None and vl.holds_environments(parent)


# --------------------------------------------------------------------------- #
# The two Qwen3 locations, exactly
# --------------------------------------------------------------------------- #
def test_the_two_locations_are_named_exactly_and_the_production_path_is_still_legacy():
    assert vl.LEGACY_QWEN3 == ".venv-qwen3" and vl.NESTED_QWEN3 == ".venv/engines/qwen3"
    assert rt.venv_dir() == rt.repo_root() / vl.LEGACY_QWEN3  # P04A flips nothing


@pytest.mark.parametrize("present, legacy, nested", [
    ((), False, False),
    ((".venv-qwen3",), True, False),
    ((".venv/engines/qwen3",), False, True),
    ((".venv-qwen3", ".venv/engines/qwen3"), True, True),
])
def test_legacy_and_nested_are_recognised_without_guessing(tmp_path, present, legacy, nested):
    root = tmp_path / "repo"
    for decoy in (".venv-qwen3-old", ".venv-qwen3.act67-preserved-x", ".venv/engines/qwen3.bak", ".venv/qwen3",
                  ".venv/engines/qwen3-new"):
        root.joinpath(*decoy.split("/")).mkdir(parents=True)
    for relative in present:
        root.joinpath(*relative.split("/")).mkdir(parents=True, exist_ok=True)
    found = vl.qwen3_layouts(root)
    assert (found.legacy is not None, found.nested is not None) == (legacy, nested)
    assert found.both == (legacy and nested)
