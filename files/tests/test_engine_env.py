"""v0.8.2 Phase 5A — ``shared.engine_env``: what every independent engine environment (``.venv-engines/<key>``) shares.

Identity (this copy's own uv-built environment on its managed CPython, at its own place, through no link), the receipt
that binds it to its project's lock and that interpreter, and the retirement of an earlier version's environment to the
set-aside folder (a rename, never a delete). Every root here is ``tmp_path``; no process is started.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from shared import engine_env, uv_runner, venv_layout

from test_qwen3_runtime import make_engine_project, make_managed_python, make_uv_engine

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Qwen3, the one engine under .venv-engines since "
                                "Phase 5A, is Windows-only; OmniVoice, Kokoro and Chatterbox follow in 5B-5D")
KEY = "qwen3"


@pytest.fixture()
def root(tmp_path, monkeypatch):
    make_managed_python(tmp_path, monkeypatch)
    make_engine_project(tmp_path)
    return tmp_path


def built(root: Path) -> Path:
    return make_uv_engine(engine_env.env_dir(root, KEY), root)


def _cfg(folder: Path, **changes) -> None:
    lines = []
    for line in (folder / "pyvenv.cfg").read_text(encoding="utf-8").splitlines():
        key = line.partition("=")[0].strip()
        if key in changes:
            if changes[key] is not None:
                lines.append(f"{key} = {changes[key]}")
            changes.pop(key)
        else:
            lines.append(line)
    (folder / "pyvenv.cfg").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_the_registry_names_its_place_and_its_project(root):
    assert engine_env.env_dir(root, KEY) == root / ".venv-engines" / "qwen3"
    assert engine_env.project_dir(root, KEY) == root / "scripts" / "tts" / "engines" / "qwen3"
    assert engine_env.env_python(root, KEY, "win32") == root / ".venv-engines" / "qwen3" / "Scripts" / "python.exe"
    assert engine_env.env_dir(root, "omnivoice") == root / ".venv-engines" / "omnivoice"  # v0.8.2 Phase 5B
    assert engine_env.project_dir(root, "omnivoice") == root / "scripts" / "tts" / "engines" / "omnivoice"
    for key in ("kokoro", "chatterbox"):  # in the app's own environment until 5C/5D
        with pytest.raises(ValueError, match="no environment of its own"):
            engine_env.env_dir(root, key)
    engine_env.check(root, KEY)  # this copy's own place and project
    (engine_env.project_dir(root, KEY) / "uv.lock").unlink()
    with pytest.raises(uv_runner.TargetRefused):
        engine_env.check(root, KEY)


def test_a_uv_built_environment_on_the_managed_python_is_its_own(root):
    built(root)
    assert engine_env.identity_problem(root, KEY) == ""


DAMAGES = {
    "not installed": (lambda r, f: None, "not installed"),
    "a file, not a folder": (lambda r, f: f.write_bytes(b"x"), "not a folder"),
    "no pyvenv.cfg": (lambda r, f: (make_uv_engine(f, r), (f / "pyvenv.cfg").unlink()), "no readable pyvenv.cfg"),
    "sees the system's packages": (lambda r, f: (make_uv_engine(f, r), _cfg(f, **{
        "include-system-site-packages": "true"})), "not isolated"),
    "not built by uv": (lambda r, f: (make_uv_engine(f, r), _cfg(f, uv=None)), "not built by uv"),
    "no interpreter": (lambda r, f: (make_uv_engine(f, r), venv_layout.interpreter(f).unlink()), "interpreter is missing"),
    "built on another Python": (lambda r, f: (make_uv_engine(f, r), _cfg(f, home=r / "elsewhere")), ""),
    "the managed Python is gone": (lambda r, f: (make_uv_engine(f, r),
                                                 uv_runner.managed_python(r).unlink()), ""),
    "the managed Python is another build": (lambda r, f: (make_uv_engine(f, r), (
        uv_runner.managed_python_home(r, "win32") / "BUILD").write_text("19990101", encoding="ascii")), ""),
}


@pytest.mark.parametrize("damage", list(DAMAGES))
def test_an_environment_that_cannot_be_shown_to_be_its_own_is_refused_with_a_reason(root, damage):
    harm, words = DAMAGES[damage]
    folder = engine_env.env_dir(root, KEY)
    folder.parent.mkdir(parents=True, exist_ok=True)
    harm(root, folder)
    problem = engine_env.identity_problem(root, KEY)
    assert problem and words in problem, problem


def test_a_moved_or_copied_environment_is_never_its_own(root):
    built(root)
    elsewhere = root / "copy-of-engine"
    make_uv_engine(elsewhere, root)
    assert "not at its own location" in engine_env.identity_problem(root, KEY, elsewhere)


def test_an_environment_reached_through_a_link_is_refused(root, tmp_path_factory):
    from test_qwen3_runtime import make_junction

    decoy = tmp_path_factory.mktemp("decoy")
    make_uv_engine(decoy / "qwen3", root)
    make_junction(root / ".venv-engines", decoy)
    assert "link" in engine_env.identity_problem(root, KEY)


def test_the_receipt_vouches_only_for_the_lock_and_python_it_was_written_for(root):
    built(root)
    assert engine_env.receipt_problem(root, KEY) == "it has no installation receipt (the last install did not finish)"
    receipt = engine_env.write_receipt(root, KEY, health={"probe": "ok"})
    assert receipt["engine"] == KEY and receipt["manager"] == "uv" and receipt["uv"] == uv_runner.UV_VERSION
    assert receipt["lock"] == engine_env.lock_identity(root, KEY) and receipt["profile"] == uv_runner.PROFILE_USER
    assert engine_env.read_receipt(root, KEY) == receipt and engine_env.receipt_problem(root, KEY) == ""
    assert not list(engine_env.env_dir(root, KEY).glob("*.tmp"))  # written whole, through a temporary file

    lock = engine_env.project_dir(root, KEY) / "uv.lock"
    original = lock.read_bytes()
    lock.write_bytes(original + b"# another lock\n")
    assert "different version of its package lock" in engine_env.receipt_problem(root, KEY)
    lock.write_bytes(original.replace(b"\n", b"\r\n"))  # line endings alone change nothing
    assert engine_env.receipt_problem(root, KEY) == ""

    build = uv_runner.managed_python_home(root, "win32") / "BUILD"
    pinned = build.read_text(encoding="ascii")
    build.write_text("19990101", encoding="ascii")
    assert "Python it was built on has changed" in engine_env.receipt_problem(root, KEY)
    build.write_text(pinned, encoding="ascii")

    engine_env.invalidate_receipt(root, KEY)
    assert engine_env.read_receipt(root, KEY) is None and "no installation receipt" in engine_env.receipt_problem(root,
                                                                                                                 KEY)
    engine_env.invalidate_receipt(root, KEY)  # nothing there: still fine


def test_a_receipt_written_for_another_engine_or_schema_is_no_receipt(root):
    built(root)
    engine_env.write_receipt(root, KEY, health={})
    path = engine_env.receipt_path(root, KEY)
    path.write_text(path.read_text(encoding="utf-8").replace('"engine": "qwen3"', '"engine": "omnivoice"'),
                    encoding="utf-8")
    assert engine_env.read_receipt(root, KEY) is None
    path.write_text("not json", encoding="utf-8")
    assert engine_env.read_receipt(root, KEY) is None


def _earlier_engine(root: Path) -> Path:
    nested = root / ".venv" / "engines" / "qwen3"
    (nested / "Lib" / "site-packages" / "torch").mkdir(parents=True)
    (nested / "Lib" / "site-packages" / "torch" / "__init__.py").write_text("# torch", encoding="utf-8")
    (nested / "pyvenv.cfg").write_text("home = C:/base\n", encoding="utf-8")
    return nested


def test_retiring_an_earlier_environment_moves_it_whole_beside_a_note_and_deletes_nothing(root):
    nested = _earlier_engine(root)
    before = sorted(p.relative_to(nested).as_posix() for p in nested.rglob("*"))
    moved = engine_env.retire(root, KEY, nested, label="nested-qwen3", note="kept for you\n")

    assert not os.path.lexists(nested)
    holder = moved.parent
    assert holder.parent == root / "files" / "runtime-data" / "qwen3" / "set-aside"
    assert holder.name.startswith("nested-qwen3-") and moved.name == "qwen3"
    assert sorted(p.relative_to(moved).as_posix() for p in moved.rglob("*")) == before
    assert (holder / engine_env.RETIRED_NOTE_NAME).read_text(encoding="utf-8") == "kept for you\n"
    second = engine_env.retire(root, KEY, _earlier_engine(root), label="nested-qwen3", note="x")
    assert second.parent != holder  # each retirement gets its own folder; nothing is overwritten


def test_a_folder_that_cannot_be_moved_stays_exactly_where_it_was(root, monkeypatch):
    nested = _earlier_engine(root)
    before = sorted(p.relative_to(nested).as_posix() for p in nested.rglob("*"))

    def in_use(src, dst):
        raise PermissionError(32, "The process cannot access the file because it is being used", str(src))

    monkeypatch.setattr(engine_env.os, "replace", in_use)
    with pytest.raises(OSError):
        engine_env.retire(root, KEY, nested, label="nested-qwen3", note="x")
    assert sorted(p.relative_to(nested).as_posix() for p in nested.rglob("*")) == before
    aside = engine_env.set_aside_dir(root, KEY)
    assert not aside.exists() or list(aside.iterdir()) == []  # no empty holder left behind


def test_nothing_that_is_not_a_real_folder_of_this_app_is_retired(root, tmp_path_factory):
    with pytest.raises(OSError):
        engine_env.retire(root, KEY, root / ".venv" / "engines" / "qwen3", label="nested-qwen3", note="x")  # absent
    outside = tmp_path_factory.mktemp("outside")
    with pytest.raises(OSError):
        engine_env.retire(root, KEY, outside, label="nested-qwen3", note="x")
    assert outside.is_dir() and not engine_env.set_aside_dir(root, KEY).exists()


def test_the_commands_go_through_the_one_uv_wrapper_for_this_engine_only(root):
    venv = engine_env.venv_command(root, KEY, "win32")
    assert venv[:2] == [str(uv_runner.uv_exe(root, "win32")), "venv"]
    assert venv_layout.same_path(venv[2], engine_env.env_dir(root, KEY))
    sync = engine_env.sync_command(root, KEY, platform="win32")
    assert sync[:2] == [str(uv_runner.uv_exe(root, "win32")), "sync"] and "--no-cache" in sync
    assert sync[sync.index("--project") + 1] == str(engine_env.project_dir(root, KEY))
    offline = engine_env.sync_command(root, KEY, offline=True, no_cache=False, reinstall=["torch"], platform="win32")
    assert "--offline" in offline and "--no-cache" not in offline and "torch" in offline
    assert engine_env.offline_miss(["error: Network connectivity is disabled, but the requested data wasn't found"])
    assert not engine_env.offline_miss(["Installed 89 packages in 17.02s"])
