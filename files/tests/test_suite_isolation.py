"""PRE-PLAN-6 Phase 1 — the suite must not write real production state.

**What went wrong.** Running the gate rewrote the developer's real
``.venv/.requirements-state.json``. Traced mechanically rather than guessed:
three tests drove ``run_setup`` with every install step stubbed but left
``bootstrap.VENV_DIR`` pointing at the real checkout, so the stamp written at the
end of setup landed in the real environment. Separately, ``bootstrap`` opened the
dated setup log at *import* time, and ``shared.logging_setup`` wrote a real
``session_*.log`` whenever a test built the launcher.

**Why it mattered.** The stamp write was harmless only because the fingerprint
happened to match. A suite that can write the real stamp can write a **false**
one — an environment recorded as reconciled when it is not — which is exactly the
invariant the requirements work exists to protect. And a production log
interleaving pytest temp paths with real runs is worth less when a user sends it
in to diagnose a real failure.

**The fix has three parts**, all in ``conftest.py`` and the culprit tests, plus
one production change (``SetupLog`` opens its file on first use, not at
construction). This module proves the guard is real and still armed — a guard
that has quietly become a no-op is worse than none, because it reads as coverage.
"""

from __future__ import annotations

import ast
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from shared import bootstrap, paths

import conftest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# --------------------------------------------------------------------------- #
# A. The guard watches the right things
# --------------------------------------------------------------------------- #
def test_the_guard_watches_the_real_requirements_stamp():
    assert (REPO_ROOT / ".venv" / ".requirements-state.json") in \
        set(conftest._GUARDED_PATHS.values())


def test_the_guard_watches_the_real_uv_receipt_and_profile_choice_every_test():
    """v0.8.2 Phase 4: the receipt the launch trusts and the profile every sync keeps."""
    from shared import bootstrap

    watched = {conftest._GUARDED_PATHS[name] for name in conftest._PER_TEST_GUARDED}
    assert REPO_ROOT / ".venv" / bootstrap.REQUIREMENTS_STATE_NAME in watched
    assert bootstrap.PROFILE_FILE in watched


def test_the_guard_watches_the_real_independent_engine_environments_every_test():
    """v0.8.2 Phase 5A: ``.venv-engines`` (a one-level listing), the Qwen3 engine's marker and its receipt."""
    from shared import engine_env

    watched = {conftest._GUARDED_PATHS[name] for name in conftest._PER_TEST_GUARDED}
    assert {REPO_ROOT / ".venv-engines", engine_env.env_dir(REPO_ROOT, "qwen3") / "pyvenv.cfg",
            engine_env.receipt_path(REPO_ROOT, "qwen3")} <= watched
    assert "the real independent engine environments" in conftest._SHALLOW_GUARDED


def test_the_guard_watches_the_real_setup_log_directory():
    assert (REPO_ROOT / "files" / "runtime-data" / "logs") in \
        set(conftest._GUARDED_PATHS.values())


def test_the_guard_watches_the_real_settings_file_around_every_test():
    assert conftest._GUARDED_PATHS["the real settings file"] == REPO_ROOT / "files" / "runtime-data" / "settings.json"
    assert "the real settings file" in conftest._PER_TEST_GUARDED


def test_the_guard_watches_all_the_real_runtime_data_once_per_session():
    assert conftest._GUARDED_PATHS["the real runtime data"] == REPO_ROOT / "files" / "runtime-data"
    assert "the real runtime data" not in conftest._PER_TEST_GUARDED


def _runtime_data_like(tmp_path):
    root = tmp_path / "runtime-data"
    (root / "python" / "Lib" / "multiprocessing" / "__pycache__").mkdir(parents=True)
    (root / "python" / "Lib" / "multiprocessing" / "__init__.py").write_text("x", encoding="utf-8")
    (root / "python" / "Lib" / "multiprocessing" / "__pycache__" / "context.cpython-312.pyc").write_bytes(b"old")
    (root / "python" / "Lib" / "encodings").mkdir()
    (root / "python" / "Lib" / "encodings" / "__init__.py").write_text("x", encoding="utf-8")
    (root / "python" / "python.exe").write_bytes(b"exe")
    (root / "python" / "python312.dll").write_bytes(b"dll")  # names the bundled interpreter cache tag: cpython-312
    for module in ("multiprocessing/heap", "multiprocessing/context"):
        (root / "python" / "Lib" / f"{module}.py").write_text("x", encoding="utf-8")
    (root / "python" / "Lib" / "encodings" / "idna.py").write_text("x", encoding="utf-8")
    (root / "logs").mkdir()
    (root / "settings.json").write_text("{}", encoding="utf-8")
    return root


def test_the_bundled_pythons_own_bytecode_cache_is_not_production_state(tmp_path):
    """Checkpoint F1: the interpreter writes a standard-library .pyc the first time a module is imported (the first real
    spawn the Edge publication tests make), and that is not a test writing production state. The control: with nothing
    written the fingerprint is stable; a new .pyc, a rewritten .pyc and a whole new __pycache__ folder inside the bundled
    interpreter do not change it."""
    root = _runtime_data_like(tmp_path)
    named = lambda: conftest._fingerprint_named("the real runtime data", root)  # noqa: E731
    before = named()
    assert named() == before, "the control: an untouched tree fingerprints the same twice"
    cache = root / "python" / "Lib" / "multiprocessing" / "__pycache__"
    (cache / "heap.cpython-312.pyc").write_bytes(b"first written")
    (cache / "context.cpython-312.pyc").write_bytes(b"rewritten, longer")
    (root / "python" / "Lib" / "encodings" / "__pycache__").mkdir(parents=True)
    (root / "python" / "Lib" / "encodings" / "__pycache__" / "idna.cpython-312.pyc").write_bytes(b"new")
    assert named() == before


def test_nothing_else_in_runtime_data_is_excused_by_the_bytecode_rule(tmp_path):
    """The rule is narrow: the interpreter's own files, a .pyc outside a __pycache__ folder, a __pycache__ anywhere but
    below python/, and every other file in runtime-data still change the fingerprint."""
    changes = {
        "a rewritten interpreter file": lambda root: (root / "python" / "python.exe").write_bytes(b"exe, changed"),
        "a new library module": lambda root: (root / "python" / "Lib" / "multiprocessing" / "evil.py").write_text(
            "x", encoding="utf-8"),
        "a pyc that is not in a __pycache__": lambda root: (root / "python" / "Lib" / "stray.pyc").write_bytes(b"x"),
        "a __pycache__ outside python": lambda root: ((root / "logs" / "__pycache__").mkdir(),
                                                      (root / "logs" / "__pycache__" / "x.pyc").write_bytes(b"x")),
        "a rewritten settings file": lambda root: (root / "settings.json").write_text('{"a": 1}', encoding="utf-8"),
        "a new log": lambda root: (root / "logs" / "setup.log").write_text("x", encoding="utf-8"),
    }
    for number, (label, change) in enumerate(changes.items()):
        root = _runtime_data_like(tmp_path / str(number))
        before = conftest._fingerprint_named("the real runtime data", root)
        change(root)
        assert conftest._fingerprint_named("the real runtime data", root) != before, label


def test_only_genuine_stdlib_bytecode_is_excused_inside_the_bundled_cache(tmp_path):
    """Reviews M3 and R2. Each case writes beside a legitimate .pyc in the bundled standard library cache, so a guard
    that skipped the folder, or any .pyc-shaped name, would pass none of the negative ones. Positive controls (an
    expected first-import .pyc, a rewrite of an existing one, an optimised one) leave the fingerprint unchanged."""
    lib = lambda root: root / "python" / "Lib"  # noqa: E731
    cache = lambda root: lib(root) / "multiprocessing" / "__pycache__"  # noqa: E731

    def write(path, data=b"x"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    changes = {
        "(positive) the expected heap .pyc": (False, lambda r: write(cache(r) / "heap.cpython-312.pyc")),
        "(positive) a rewrite of an existing .pyc": (False, lambda r: write(
            cache(r) / "context.cpython-312.pyc", b"rewritten, longer")),
        "(positive) an optimised .pyc": (False, lambda r: write(cache(r) / "heap.cpython-312.opt-2.pyc")),
        "(positive) a cache folder created by a first import": (False, lambda r: write(
            lib(r) / "encodings" / "__pycache__" / "idna.cpython-312.pyc")),
        "a foreign interpreter tag": (True, lambda r: write(cache(r) / "heap.cpython-311.pyc")),
        "another implementation tag": (True, lambda r: write(cache(r) / "heap.pypy-39.pyc")),
        "a cache-named .pyc with no source module": (True, lambda r: write(cache(r) / "ghost.cpython-312.pyc")),
        "an optimised .pyc with no source module": (True, lambda r: write(cache(r) / "ghost.cpython-312.opt-1.pyc")),
        "a nested __pycache__ directory": (True, lambda r: (cache(r) / "__pycache__").mkdir()),
        "a file inside a nested __pycache__": (True, lambda r: write(cache(r) / "__pycache__" / "heap.cpython-312.pyc")),
        "an unexpected JSON file": (True, lambda r: write(cache(r) / "unexpected-state.json", b"{}")),
        "an unexpected source file": (True, lambda r: write(cache(r) / "evil.py")),
        "an unexpected text file": (True, lambda r: write(cache(r) / "notes.txt")),
        "an extensionless file": (True, lambda r: write(cache(r) / "heap")),
        "a pyc with no interpreter tag": (True, lambda r: write(cache(r) / "heap.pyc")),
        "an atomic-write leftover": (True, lambda r: write(cache(r) / "heap.cpython-312.pyc.123")),
        "a pyc-named directory": (True, lambda r: (cache(r) / "heap.cpython-312.pyc").mkdir()),
        "a pyc whose source is a directory": (True, lambda r: (
            (lib(r) / "multiprocessing" / "dirmod.py").mkdir(), write(cache(r) / "dirmod.cpython-312.pyc"))),
        "a good pyc in Scripts": (True, lambda r: (
            write(r / "python" / "Scripts" / "pip.py"), write(r / "python" / "Scripts" / "__pycache__" / "pip.cpython-312.pyc"))),
        "a good pyc directly under python/ (not Lib)": (True, lambda r: (
            write(r / "python" / "site.py"), write(r / "python" / "__pycache__" / "site.cpython-312.pyc"))),
        "a good pyc under python-packages": (True, lambda r: (
            write(r / "python-packages" / "pkg" / "m.py"),
            write(r / "python-packages" / "pkg" / "__pycache__" / "m.cpython-312.pyc"))),
    }
    for number, (label, (detected, change)) in enumerate(changes.items()):
        root = _runtime_data_like(tmp_path / str(number))
        before = conftest._fingerprint_named("the real runtime data", root)
        change(root)
        after = conftest._fingerprint_named("the real runtime data", root)
        assert (after != before) is detected, label


def _site_packages_like(tmp_path, folder="site-packages", *, preexisting_cache=False):
    """A bundled Python whose Lib holds a third-party pip. ``__init__.py`` exists BEFORE any snapshot."""
    root = _runtime_data_like(tmp_path)
    pip = root / "python" / "Lib" / folder / "pip"
    (pip / "_vendor" / "rich").mkdir(parents=True)
    (pip / "__init__.py").write_text("x", encoding="utf-8")
    (pip / "_vendor" / "rich" / "__init__.py").write_text("x", encoding="utf-8")
    if preexisting_cache:
        (pip / "__pycache__").mkdir()
    return root, pip


@pytest.mark.parametrize("folder", ["site-packages", "Site-Packages", "SITE-PACKAGES"])
@pytest.mark.parametrize("name", ["__init__.cpython-312.pyc", "__init__.cpython-312.opt-1.pyc", "__init__.cpython-312.opt-2.pyc"])
@pytest.mark.parametrize("preexisting_cache", [False, True])
def test_bytecode_under_site_packages_is_never_excused(tmp_path, folder, name, preexisting_cache):
    """Review R3 (Codex): site-packages is third-party, not the standard library. A correct-tag .pyc with its source
    beside it, in a new or an existing __pycache__, at any case of the folder name, still changes the fingerprint."""
    root, pip = _site_packages_like(tmp_path, folder, preexisting_cache=preexisting_cache)
    before = conftest._fingerprint_named("the real runtime data", root)
    (pip / "__pycache__").mkdir(exist_ok=True)
    (pip / "__pycache__" / name).write_bytes(b"unrelated bytes")
    assert conftest._fingerprint_named("the real runtime data", root) != before


def test_a_bare_site_packages_cache_folder_and_a_nested_third_party_package_register(tmp_path):
    root, pip = _site_packages_like(tmp_path)
    before = conftest._fingerprint_named("the real runtime data", root)
    (pip / "__pycache__").mkdir()
    assert conftest._fingerprint_named("the real runtime data", root) != before, "the cache folder itself"
    root, pip = _site_packages_like(tmp_path / "nested")
    before = conftest._fingerprint_named("the real runtime data", root)
    cache = pip / "_vendor" / "rich" / "__pycache__"
    cache.mkdir()
    (cache / "__init__.cpython-312.pyc").write_bytes(b"x")
    assert conftest._fingerprint_named("the real runtime data", root) != before, "a nested third-party package"


def test_stdlib_bytecode_stays_excused_beside_a_site_packages_tree(tmp_path):
    root, _ = _site_packages_like(tmp_path)
    before = conftest._fingerprint_named("the real runtime data", root)
    cache = root / "python" / "Lib" / "multiprocessing" / "__pycache__"
    (cache / "heap.cpython-312.pyc").write_bytes(b"first written")
    (cache / "heap.cpython-312.opt-1.pyc").write_bytes(b"optimised")
    assert conftest._fingerprint_named("the real runtime data", root) == before


def _managed_like(root):
    """v0.8.2 Phase 4: uv's managed interpreter beside the legacy one, the same build."""
    home = root.joinpath(*conftest._MANAGED_PYTHON_PARTS)
    (home / "Lib" / "json" / "__pycache__").mkdir(parents=True)
    (home / "Lib" / "json" / "decoder.py").write_text("x", encoding="utf-8")
    (home / "Lib" / "site-packages" / "pip" / "__pycache__").mkdir(parents=True)
    (home / "Lib" / "site-packages" / "pip" / "util.py").write_text("x", encoding="utf-8")
    (home / "python312.dll").write_bytes(b"dll")
    return home


def test_the_managed_interpreter_folder_is_the_pinned_one():
    from shared import uv_runner

    assert conftest._MANAGED_PYTHON_PARTS == ("uv", "python", uv_runner.pins("win32").python_key)
    assert conftest._MANAGED_MINOR_LINK_PARTS == ("uv", "python", uv_runner.pins("win32").python_minor_key)


def test_bytecode_seen_through_uvs_minor_version_link_is_excused_too(tmp_path):
    """uv keeps a ``cpython-3.12-...`` link to the managed interpreter and the runtime-data walk follows links, so the
    same first-import bytecode also appears under the link's name (the Phase 4 focused run failed on exactly that)."""
    root = _runtime_data_like(tmp_path)
    home = _managed_like(root)
    link = root.joinpath(*conftest._MANAGED_MINOR_LINK_PARTS)
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(home), str(link))  # a junction needs no privilege, as uv's own does not
    else:
        link.symlink_to(home, target_is_directory=True)
    before = conftest._fingerprint_named("the real runtime data", root)
    (home / "Lib" / "json" / "__pycache__" / "decoder.cpython-312.pyc").write_bytes(b"x")
    assert conftest._fingerprint_named("the real runtime data", root) == before
    (home / "Lib" / "json" / "stray.txt").write_text("x", encoding="utf-8")
    assert conftest._fingerprint_named("the real runtime data", root) != before, "anything else still counts"


def test_the_managed_pythons_own_first_import_bytecode_is_excused_and_nothing_else(tmp_path):
    root = _runtime_data_like(tmp_path)
    home = _managed_like(root)
    before = conftest._fingerprint_named("the real runtime data", root)
    (home / "Lib" / "json" / "__pycache__" / "decoder.cpython-312.pyc").write_bytes(b"x")
    assert conftest._fingerprint_named("the real runtime data", root) == before
    (home / "Lib" / "site-packages" / "pip" / "__pycache__" / "util.cpython-312.pyc").write_bytes(b"x")
    assert conftest._fingerprint_named("the real runtime data", root) != before, "site-packages is never excused"


def test_a_new_cache_folder_in_a_nested_managed_stdlib_package_is_excused(tmp_path):
    """Seen in the Phase 4 focused run: the managed interpreter's first import of xml.dom.minidom made
    ``Lib/xml/dom/__pycache__`` where there was none."""
    root = _runtime_data_like(tmp_path)
    home = _managed_like(root)
    package = home / "Lib" / "xml" / "dom"
    package.mkdir(parents=True)
    (package / "minidom.py").write_text("x", encoding="utf-8")
    before = conftest._fingerprint_named("the real runtime data", root)
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "minidom.cpython-312.pyc").write_bytes(b"x")
    assert conftest._fingerprint_named("the real runtime data", root) == before


def _managed_like_macos(root):
    """v0.8.2 Phase 4 macOS acceptance: uv's managed interpreter in the Apple Silicon layout (``lib/python3.12``, the cache
    tag named by ``lib/libpython3.12.dylib``), beside the Windows-shaped legacy folder of ``_runtime_data_like``."""
    home = root.joinpath(*conftest._MANAGED_PYTHON_PARTS_MACOS)
    stdlib = home / "lib" / "python3.12"
    (stdlib / "json" / "__pycache__").mkdir(parents=True)
    (stdlib / "json" / "decoder.py").write_text("x", encoding="utf-8")
    (stdlib / "site-packages" / "pip" / "__pycache__").mkdir(parents=True)
    (stdlib / "site-packages" / "pip" / "util.py").write_text("x", encoding="utf-8")
    (home / "lib" / "libpython3.12.dylib").write_bytes(b"dylib")
    return home


def test_the_macos_managed_interpreter_folder_is_the_pinned_one():
    from shared import uv_runner

    assert conftest._MANAGED_PYTHON_PARTS_MACOS == ("uv", "python", uv_runner.pins("darwin").python_key)
    assert conftest._MANAGED_MINOR_LINK_PARTS_MACOS == ("uv", "python", uv_runner.pins("darwin").python_minor_key)


def test_the_macos_managed_pythons_own_first_import_bytecode_is_excused_and_nothing_else(tmp_path):
    """Found natively: from a new uv dev environment on HOME-MacOS, a test's ``-m venv`` made the managed interpreter
    compile its standard library (``venv``, ``ensurepip``, ``xmlrpc`` ...) and the session guard failed the run."""
    root = _runtime_data_like(tmp_path)
    home = _managed_like_macos(root)
    assert conftest._bundled_cache_tag(root) == "cpython-312"
    before = conftest._fingerprint_named("the real runtime data", root)
    stdlib = home / "lib" / "python3.12"
    (stdlib / "json" / "__pycache__" / "decoder.cpython-312.pyc").write_bytes(b"x")
    (stdlib / "xmlrpc").mkdir()
    (stdlib / "xmlrpc" / "client.py").write_text("x", encoding="utf-8")
    after_source = conftest._fingerprint_named("the real runtime data", root)
    assert after_source != before, "a new source file is not bytecode"
    (stdlib / "xmlrpc" / "__pycache__").mkdir()
    (stdlib / "xmlrpc" / "__pycache__" / "client.cpython-312.pyc").write_bytes(b"x")
    assert conftest._fingerprint_named("the real runtime data", root) == after_source
    (stdlib / "site-packages" / "pip" / "__pycache__" / "util.cpython-312.pyc").write_bytes(b"x")
    assert conftest._fingerprint_named("the real runtime data", root) != after_source, "site-packages is never excused"


def test_macos_bytecode_seen_through_uvs_minor_version_link_is_excused_and_a_foreign_tag_is_not(tmp_path):
    root = _runtime_data_like(tmp_path)
    home = _managed_like_macos(root)
    link = root.joinpath(*conftest._MANAGED_MINOR_LINK_PARTS_MACOS)
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(home), str(link))
    else:
        link.symlink_to(home, target_is_directory=True)
    before = conftest._fingerprint_named("the real runtime data", root)
    cache = home / "lib" / "python3.12" / "json" / "__pycache__"
    (cache / "decoder.cpython-312.pyc").write_bytes(b"x")
    assert conftest._fingerprint_named("the real runtime data", root) == before
    (cache / "decoder.cpython-313.pyc").write_bytes(b"x")
    assert conftest._fingerprint_named("the real runtime data", root) != before, "another interpreter's tag counts"


def test_a_macos_managed_interpreter_disagreeing_on_the_tag_excuses_nothing(tmp_path):
    root = _runtime_data_like(tmp_path)
    home = _managed_like_macos(root)
    (home / "lib" / "libpython3.12.dylib").rename(home / "lib" / "libpython3.13.dylib")
    assert conftest._bundled_cache_tag(root) is None
    (home / "lib" / "libpython3.13.dylib").unlink()
    assert conftest._bundled_cache_tag(root) is None, "a present interpreter folder naming no tag excuses nothing"


def test_the_two_interpreters_must_agree_on_the_cache_tag(tmp_path):
    root = _runtime_data_like(tmp_path)
    home = _managed_like(root)
    assert conftest._bundled_cache_tag(root) == "cpython-312"
    (home / "python312.dll").rename(home / "python313.dll")
    assert conftest._bundled_cache_tag(root) is None


def test_a_bundled_python_with_no_identifiable_cache_tag_excuses_nothing(tmp_path):
    root = _runtime_data_like(tmp_path)
    (root / "python" / "python312.dll").unlink()
    before = conftest._fingerprint_named("the real runtime data", root)
    (root / "python" / "Lib" / "multiprocessing" / "__pycache__" / "heap.cpython-312.pyc").write_bytes(b"x")
    assert conftest._fingerprint_named("the real runtime data", root) != before


def test_the_cache_tag_follows_the_bundled_interpreter_not_the_test_interpreter(tmp_path):
    root = _runtime_data_like(tmp_path)
    assert conftest._bundled_cache_tag(root) == "cpython-312"
    (root / "python" / "python312.dll").rename(root / "python" / "python313.dll")
    assert conftest._bundled_cache_tag(root) == "cpython-313"
    before = conftest._fingerprint_named("the real runtime data", root)
    cache = root / "python" / "Lib" / "multiprocessing" / "__pycache__"
    (cache / "heap.cpython-313.pyc").write_bytes(b"x")
    assert conftest._fingerprint_named("the real runtime data", root) == before
    (cache / "heap.cpython-312.pyc").write_bytes(b"x")
    assert conftest._fingerprint_named("the real runtime data", root) != before


def test_a_link_in_the_bundled_cache_is_not_excused(tmp_path):
    """A real link named like a good .pyc still registers. It skips only where this account cannot create links; the
    skip reason is the one verification.json bounds at one."""
    root = _runtime_data_like(tmp_path)
    cache = root / "python" / "Lib" / "multiprocessing" / "__pycache__"
    before = conftest._fingerprint_named("the real runtime data", root)
    try:
        (cache / "heap.cpython-312.pyc").symlink_to(root / "settings.json")
    except OSError as error:
        if getattr(error, "winerror", None) != 1314:  # ERROR_PRIVILEGE_NOT_HELD; anything else is a real problem
            raise
        pytest.skip("Windows refused to create a real symbolic link in the bundled-Python cache (WinError 1314: this "
                    "account does not hold the symbolic-link privilege), so the isolation guard link control cannot "
                    "be exercised here")
    assert conftest._fingerprint_named("the real runtime data", root) != before


def test_the_link_test_skips_only_on_winerror_1314_and_with_its_own_policy_reason(tmp_path, monkeypatch):
    """Other filesystem errors fail normally; the 1314 skip carries exactly the reason verification.json bounds at one.
    No link is simulated as created: the test body is driven with a symlink_to that refuses."""
    from test_macos_p1b_gate import ISOLATION_LINK_REASON

    def refuse(winerror):
        def symlink_to(self, *args, **kwargs):
            error = OSError(winerror, "refused")
            error.winerror = winerror
            raise error
        return symlink_to

    monkeypatch.setattr(Path, "symlink_to", refuse(1314))
    with pytest.raises(pytest.skip.Exception) as skipped:
        test_a_link_in_the_bundled_cache_is_not_excused(tmp_path / "a")
    assert str(skipped.value) == ISOLATION_LINK_REASON or skipped.value.msg == ISOLATION_LINK_REASON
    for other in (5, 183, 1):
        monkeypatch.setattr(Path, "symlink_to", refuse(other))
        with pytest.raises(OSError):
            test_a_link_in_the_bundled_cache_is_not_excused(tmp_path / f"b{other}")


def test_the_bytecode_predicate_refuses_links_and_irregular_entries_without_needing_a_real_link(tmp_path):
    root = _runtime_data_like(tmp_path)

    class Entry:
        def __init__(self, *, link=False, directory=False, file=True):
            self._link, self._dir, self._file = link, directory, file

        def is_symlink(self):
            return self._link

        def is_dir(self, follow_symlinks=True):
            return self._dir

        def is_file(self, follow_symlinks=True):
            return self._file

    ok = "python/Lib/multiprocessing/__pycache__/heap.cpython-312.pyc"
    cache = "python/Lib/multiprocessing/__pycache__"
    accept = lambda rel, entry: conftest._bundled_python_bytecode(rel, entry, root=root, tag="cpython-312")  # noqa: E731
    assert accept(ok, Entry())
    assert accept(cache, Entry(directory=True, file=False))
    assert not accept(ok, Entry(link=True)), "a link named like a .pyc"
    assert not accept(cache, Entry(link=True, directory=True, file=False)), "a junction"
    assert not accept(ok, Entry(file=False)), "not a regular file"
    assert not accept(cache + "/__pycache__", Entry(directory=True, file=False))
    assert not accept(ok, None)


def test_the_bytecode_rule_applies_to_the_runtime_data_tree_alone(tmp_path):
    """Another guarded tree that happens to hold a python/__pycache__ keeps counting it."""
    root = _runtime_data_like(tmp_path)
    before = conftest._fingerprint_named("the real Qwen3 job folder", root)
    (root / "python" / "Lib" / "multiprocessing" / "__pycache__" / "heap.cpython-312.pyc").write_bytes(b"new")
    assert conftest._fingerprint_named("the real Qwen3 job folder", root) != before


# --------------------------------------------------------------------------- #
# B. The guard can actually detect a change
# --------------------------------------------------------------------------- #
def test_a_rewritten_file_changes_its_fingerprint(tmp_path):
    target = tmp_path / "stamp.json"
    target.write_text('{"a": 1}', encoding="utf-8")
    before = conftest._fingerprint(target)

    target.write_text('{"a": 22}', encoding="utf-8")

    assert conftest._fingerprint(target) != before


def test_a_new_file_changes_a_watched_directorys_fingerprint(tmp_path):
    watched = tmp_path / "logs"
    watched.mkdir()
    before = conftest._fingerprint(watched)

    (watched / "setup_2026-09-03.log").write_text("run", encoding="utf-8")

    assert conftest._fingerprint(watched) != before


def test_a_missing_path_fingerprints_as_nothing_rather_than_raising(tmp_path):
    """A checkout with no .venv must not be a special case."""
    assert conftest._fingerprint(tmp_path / "not-here") is None


# --------------------------------------------------------------------------- #
# C. Isolation is actually in force during this very test
# --------------------------------------------------------------------------- #
def test_setup_logging_is_redirected_away_from_the_real_logs_directory():
    real = REPO_ROOT / "files" / "runtime-data" / "logs"
    assert bootstrap.LOGS_DIR != real
    assert paths.LOGS_DIR != real


def test_writing_a_setup_log_line_lands_in_the_sandbox():
    """Behavioural: the shared logger writes, and not into the real tree.

    The autouse guard re-checks the real log directory when this test ends, so
    if the redirect ever stopped working this test fails twice over.
    """
    bootstrap.LOG.line("phase-1 isolation probe")

    assert bootstrap.LOG.path.is_relative_to(bootstrap.LOGS_DIR)
    assert bootstrap.LOG.path.exists()
    assert "phase-1 isolation probe" in bootstrap.LOG.path.read_text(encoding="utf-8")


def test_importing_bootstrap_creates_no_log_file_of_its_own(tmp_path, monkeypatch):
    """The production half: constructing a SetupLog must touch no filesystem.

    This is what made every test that merely imported ``bootstrap`` append to the
    production log.
    """
    monkeypatch.setattr(bootstrap, "LOGS_DIR", tmp_path / "logs")

    log = bootstrap.SetupLog()

    assert not (tmp_path / "logs").exists()
    log.line("now it may exist")
    assert (tmp_path / "logs").is_dir()


def test_the_header_is_still_the_first_thing_written(tmp_path, monkeypatch):
    """Deferring the open must not reorder what a user reads in the log."""
    monkeypatch.setattr(bootstrap, "LOGS_DIR", tmp_path / "logs")
    log = bootstrap.SetupLog()

    log.line("first real line")

    text = log.path.read_text(encoding="utf-8")
    assert "===== Setup run" in text
    assert text.index("===== Setup run") < text.index("first real line")
    assert text.index("Repo root:") < text.index("first real line")


def test_the_run_header_is_written_once_per_logger(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "LOGS_DIR", tmp_path / "logs")
    log = bootstrap.SetupLog()

    log.line("a")
    log.line("b")

    assert log.path.read_text(encoding="utf-8").count("===== Setup run") == 1


# --------------------------------------------------------------------------- #
# D. The stamp guard is content-aware, not just metadata-aware
#
# (size, mtime_ns) caught the accidental writer that was actually found, because
# rewriting the stamp moves its timestamp. It is not a content-integrity proof:
# a stamp falsified in place -- a different requirements_sha256 of the same
# length, with the timestamp put back -- is byte-different and metadata-identical.
# That is the shape a *false* success stamp would have, which is the thing this
# guard exists to catch, so the single-file fingerprint hashes content.
#
# The directory fingerprint deliberately does not hash: it covers the real logs
# directory, checked once per session, where anything written necessarily changes
# a size or a timestamp.
# --------------------------------------------------------------------------- #
def test_a_same_size_rewrite_with_a_restored_timestamp_is_still_caught(tmp_path):
    stamp = tmp_path / ".requirements-state.json"
    stamp.write_text('{"requirements_sha256": "aaaa"}', encoding="utf-8")
    before_stat = stamp.stat()
    before = conftest._fingerprint(stamp)

    # Same length, different content -- a falsified stamp.
    stamp.write_text('{"requirements_sha256": "bbbb"}', encoding="utf-8")
    # ...and the timestamp put back, so metadata alone learns nothing.
    os.utime(stamp, ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))

    after = conftest._fingerprint(stamp)

    assert stamp.stat().st_size == before_stat.st_size
    assert stamp.stat().st_mtime_ns == before_stat.st_mtime_ns
    assert after != before, "a same-size, same-mtime content change slipped past"


def test_the_file_fingerprint_carries_a_content_hash(tmp_path):
    stamp = tmp_path / ".requirements-state.json"
    stamp.write_text('{"a": 1}', encoding="utf-8")

    size, mtime_ns, digest = conftest._fingerprint(stamp)

    assert size == stamp.stat().st_size
    assert mtime_ns == stamp.stat().st_mtime_ns
    assert digest == hashlib.sha256(stamp.read_bytes()).hexdigest()


def test_identical_content_fingerprints_identically(tmp_path):
    """The guard must not cry wolf on a rewrite that changed nothing."""
    stamp = tmp_path / ".requirements-state.json"
    stamp.write_text('{"a": 1}', encoding="utf-8")
    before = conftest._fingerprint(stamp)
    stat = stamp.stat()

    stamp.write_text('{"a": 1}', encoding="utf-8")
    os.utime(stamp, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    assert conftest._fingerprint(stamp) == before


def test_the_directory_fingerprint_stays_metadata_only(tmp_path):
    """Cost boundary: no hashing of the log tree."""
    watched = tmp_path / "logs"
    watched.mkdir()
    (watched / "setup.log").write_text("x", encoding="utf-8")

    entries = conftest._fingerprint(watched)

    assert entries == (("setup.log", 1, (watched / "setup.log").stat().st_mtime_ns),)


def test_the_guard_watches_the_real_import_proof():
    assert (REPO_ROOT / ".venv" / ".import-proof.json") in \
        set(conftest._GUARDED_PATHS.values())


def test_both_venv_records_are_checked_around_every_test():
    """Per-test attribution for the two small files; the log tree is per-session."""
    per_test = set(conftest._PER_TEST_GUARDED)
    assert "the real requirements stamp" in per_test
    assert "the real import proof" in per_test
    assert "the real setup log directory" not in per_test


# --------------------------------------------------------------------------- #
# F. PRE-PLAN-6 Phase 6, row 17 — the FFmpeg state the guard used to miss
#
# Phases 3 to 5 gave the suite three more ways to write production state: the
# runtime pin, an installed build under files/bin, and the staging tree. None of
# them was guarded. That was not hypothetical — an intermediate Phase-5 run
# created files/runtime-data/ffmpeg-staging/9.0.1 and the suite did not notice;
# it was found by hand afterwards. The absence of those two trees is what
# Phase 7's real acceptance runs against, so absence is the thing protected.
# --------------------------------------------------------------------------- #
def test_the_guard_watches_the_real_ffmpeg_pin():
    assert (REPO_ROOT / "files" / "runtime-data" / "ffmpeg-state.json") in \
        set(conftest._GUARDED_PATHS.values())


def test_the_guard_watches_the_real_installed_build():
    assert (REPO_ROOT / "files" / "bin") in set(conftest._GUARDED_PATHS.values())


def test_the_guard_watches_the_real_staging_tree():
    assert (REPO_ROOT / "files" / "runtime-data" / "ffmpeg-staging") in \
        set(conftest._GUARDED_PATHS.values())


def test_the_ffmpeg_paths_are_attributed_to_the_test_that_touched_them():
    """Per-test, not per-session: a pin or a build has one culprit worth naming.

    Affordable because on a machine in the preserved condition both trees are
    absent, so the check is a single failed stat.
    """
    per_test = set(conftest._PER_TEST_GUARDED)
    assert "the real FFmpeg pin" in per_test
    assert "the real installed FFmpeg build" in per_test
    assert "the real FFmpeg staging tree" in per_test


def test_a_path_appearing_where_there_was_none_is_detected(tmp_path):
    """Absence is a value, not a gap. Creating the tree must compare unequal.

    This is the exact shape of the Phase-5 leak: nothing existed, then a
    directory did.
    """
    absent = tmp_path / "ffmpeg-staging"
    before = conftest._fingerprint(absent)
    assert before is None

    (absent / "9.0.1").mkdir(parents=True)

    assert conftest._fingerprint(absent) != before


def test_a_path_disappearing_is_detected(tmp_path):
    """The other direction: a guard that only catches writes is half a guard."""
    present = tmp_path / "bin"
    (present / "ffmpeg" / "9.0.1" / "bin").mkdir(parents=True)
    (present / "ffmpeg" / "9.0.1" / "bin" / "ffmpeg.exe").write_text(
        "x", encoding="utf-8")
    before = conftest._fingerprint(present)
    assert before is not None

    import shutil
    shutil.rmtree(present)

    assert conftest._fingerprint(present) != before


def test_a_change_deep_in_a_versioned_tree_cannot_hide(tmp_path):
    """``files/bin`` is ``ffmpeg/<version>/bin/ffmpeg.exe`` — three levels down.

    A single-level listing of ``files/bin`` would report the same tuple whether
    or not a whole FFmpeg build had appeared underneath it, because only the
    ``ffmpeg`` directory name is visible at the top. That is why the fingerprint
    recurses.
    """
    root = tmp_path / "bin"
    (root / "ffmpeg" / "9.0.1" / "bin").mkdir(parents=True)
    before = conftest._fingerprint(root)

    (root / "ffmpeg" / "9.0.1" / "bin" / "ffmpeg.exe").write_text(
        "binary", encoding="utf-8")

    assert conftest._fingerprint(root) != before, \
        "a build appearing three directories down was invisible to the guard"


def test_an_emptied_directory_does_not_look_like_an_absent_one(tmp_path):
    """Removing the only file must not fingerprint the same as never existing."""
    root = tmp_path / "staging"
    (root / "9.0.1").mkdir(parents=True)
    (root / "9.0.1" / "part").write_text("x", encoding="utf-8")
    populated = conftest._fingerprint(root)

    (root / "9.0.1" / "part").unlink()
    emptied = conftest._fingerprint(root)

    assert emptied != populated
    assert emptied is not None, "an existing empty tree read as absent"


def test_a_nested_empty_directory_is_itself_recorded(tmp_path):
    """A staging tree is created before anything lands in it, and that counts."""
    root = tmp_path / "staging"
    root.mkdir()
    before = conftest._fingerprint(root)

    (root / "9.0.1").mkdir()

    assert conftest._fingerprint(root) != before


def test_the_guard_reads_the_real_filesystem_not_a_patched_one(monkeypatch,
                                                               tmp_path):
    """A test that fakes ``os.scandir`` must not also fake what the guard sees.

    ``conftest`` captures the real ``os.scandir``/``os.stat`` at import, before
    any test can replace them. Without that, a module proving some walk
    tolerates a vanishing file would blind the guard for the duration.
    """
    target = tmp_path / "tree"
    target.mkdir()
    (target / "a").write_text("x", encoding="utf-8")
    expected = conftest._fingerprint(target)

    def exploding(*args, **kwargs):
        raise AssertionError("the guard used the monkeypatched os.scandir")

    monkeypatch.setattr(os, "scandir", exploding)

    assert conftest._fingerprint(target) == expected


# --------------------------------------------------------------------------- #
#  PRE-PLAN-6 Phase 7 — a fixture must not outlive itself
#
#  Phase 7 spent the preserved missing-FFmpeg condition, and two test-only
#  defects that the absence had been hiding turned red the moment a real pair
#  existed. Both are the same shape as the production-state defects above: state
#  that is process-wide, written by one test, and never given back.
#
#  1. ``test_m4b_probe_encoding`` sandboxed its whole module with a
#     ``pytestmark``, so the three tests whose entire purpose is to run a REAL
#     ffmpeg against a REAL generated book were handed a stub text file instead.
#  2. ``configure_pydub()`` writes into pydub's own module globals. Nothing
#     restored them, so a test that pinned a sandbox pair left pydub pointing
#     inside its ``tmp_path`` — which pytest then deleted — and the next consumer
#     to call ``AudioSegment.export`` inherited it. That consumer was
#     ``kokoro_synth``, which never calls ``configure_pydub()`` itself.
# --------------------------------------------------------------------------- #

PROBE_ENCODING = Path(__file__).parent / "test_m4b_probe_encoding.py"

#: The tests in that module that must run against the REAL proved pair.
REAL_MEDIA_TESTS = frozenset({
    "test_the_generated_book_really_defeats_the_ansi_codepage",
    "test_the_production_probe_reads_a_real_book_with_unicode_titles",
    "test_a_real_unicode_book_is_usable_rather_than_refused",
})


def _probe_encoding_tree() -> ast.Module:
    return ast.parse(PROBE_ENCODING.read_text(encoding="utf-8"))


def _sandbox_marks(node: ast.FunctionDef) -> list[str]:
    """Decorators on *node* that apply the sandbox pair, however they spell it.

    AST rather than substring matching, per the Phase-6 rule: the module-level
    alias means the mark can legitimately appear as a bare ``@sandboxed`` or as
    the full ``@pytest.mark.usefixtures("pinned_ffmpeg")``, and a docstring that
    merely mentions either is not a decorator.
    """
    found = []
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "sandboxed":
            found.append("sandboxed")
        elif isinstance(decorator, ast.Call):
            args = [a.value for a in decorator.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if "pinned_ffmpeg" in args:
                found.append(ast.unparse(decorator.func))
    return found


def test_the_probe_module_does_not_sandbox_itself_wholesale():
    """No module-level mark may apply the sandbox pair to every test in the file.

    This is the defect exactly: a ``pytestmark`` cannot be opted out of, so every
    real-media test added to that module afterwards is silently captured.
    """
    offenders = []
    for node in _probe_encoding_tree().body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "pytestmark" not in names:
            continue
        if "pinned_ffmpeg" in ast.unparse(node.value):
            offenders.append(ast.unparse(node))
    assert offenders == [], (
        "test_m4b_probe_encoding applies the sandbox pair module-wide again: "
        f"{offenders}")


def _module_level_sandbox() -> list[str]:
    """Any module-level ``pytestmark`` that applies the sandbox pair.

    Counted as applying to *every* test in the file, because that is what pytest
    does with it — which is the whole reason the original defect was invisible.
    """
    marks = []
    for node in _probe_encoding_tree().body:
        if (isinstance(node, ast.Assign)
                and any(t.id == "pytestmark" for t in node.targets
                        if isinstance(t, ast.Name))
                and "pinned_ffmpeg" in ast.unparse(node.value)):
            marks.append(ast.unparse(node))
    return marks


def test_the_real_media_tests_are_not_handed_a_stub():
    """The three generated-media tests must not receive the sandbox pair.

    Checked against both routes it can arrive by — a decorator on the test, and a
    module-level mark that reaches it without naming it.
    """
    captured = {}
    module_wide = _module_level_sandbox()
    for node in ast.walk(_probe_encoding_tree()):
        if isinstance(node, ast.FunctionDef) and node.name in REAL_MEDIA_TESTS:
            marks = _sandbox_marks(node) + module_wide
            if marks:
                captured[node.name] = marks
    assert captured == {}, (
        f"generated-media tests were handed the sandbox pair: {captured}")


def test_every_real_media_test_is_actually_present():
    """Guards the guard: a rename must not silently empty the set above."""
    defined = {node.name for node in ast.walk(_probe_encoding_tree())
               if isinstance(node, ast.FunctionDef)}
    missing = REAL_MEDIA_TESTS - defined
    assert missing == set(), f"REAL_MEDIA_TESTS names tests that no longer exist: {missing}"


def test_the_command_building_tests_still_get_a_pinned_pair():
    """Narrowing the scope must not have removed the pair the others need.

    ``probe_source`` builds its argv from ``ffprobe_cmd()`` before it consults an
    injected runner, so every test that reaches it needs *a* pinned pair even
    though it executes nothing. Those must still opt in explicitly.
    """
    unsandboxed = []
    for node in ast.walk(_probe_encoding_tree()):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("test_") or node.name in REAL_MEDIA_TESTS:
            continue
        calls = {sub.func.attr for sub in ast.walk(node)
                 if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)}
        if "probe_source" in calls and not _sandbox_marks(node):
            unsandboxed.append(node.name)
    assert unsandboxed == [], (
        "these build a probe command line but were left without a pinned pair: "
        f"{unsandboxed}")


def test_the_runtime_trust_boundary_is_still_pinned_only():
    """Narrowing fixture scope must not have reopened a bare-name fallback."""
    from shared import ffmpeg_utils as trust

    source = ast.parse(Path(trust.__file__).read_text(encoding="utf-8"))
    pair = next(node for node in ast.walk(source)
                if isinstance(node, ast.FunctionDef) and node.name == "_executable_pair")
    called = {sub.func.attr for sub in ast.walk(pair)
              if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)}
    assert "pinned_pair" in called
    assert "which" not in called and "discover_pairs" not in called


# --- the pydub guard, proved behaviourally ---------------------------------- #

_SANDBOX_SEEN: dict = {}


def _pydub_now() -> dict:
    from pydub import AudioSegment
    from pydub import utils as pydub_utils

    return {name: getattr(AudioSegment, name, None)
            for name in ("converter", "ffmpeg", "ffprobe")} | {
        "prober": pydub_utils.get_prober_name()}


def test_a_sandbox_pair_is_authoritative_while_its_fixture_is_active(pinned_ffmpeg):
    """Ordered first on purpose: it pollutes, the next test proves the cleanup."""
    from shared import ffmpeg_utils as trust

    _SANDBOX_SEEN["dir"] = str(Path(pinned_ffmpeg))
    trust.configure_pydub()
    assert Path(trust.ffmpeg_cmd()).parent == Path(pinned_ffmpeg)
    assert all(_SANDBOX_SEEN["dir"] in str(v) for v in _pydub_now().values())


def test_no_authority_still_points_into_the_torn_down_sandbox():
    """The whole defect, in one assertion, for both authorities at once."""
    from shared import ffmpeg_utils as trust

    sandbox = _SANDBOX_SEEN.get("dir")
    assert sandbox, "the polluting test above must run first"

    resolved = trust.ffmpeg_path()
    assert resolved is None or sandbox not in resolved, (
        f"ffmpeg_utils still resolves the torn-down sandbox: {resolved}")

    stale = {k: v for k, v in _pydub_now().items() if v and sandbox in str(v)}
    assert stale == {}, f"pydub still points into the torn-down sandbox: {stale}"


def test_the_pydub_guard_restores_absence_as_well_as_values(tmp_path):
    """Driving the guard directly, so it cannot pass by luck of ordering.

    ``AudioSegment.ffprobe`` does not exist until ``configure_pydub()`` creates
    it, so a guard that only reassigns attributes would leave it behind. Absence
    has to round-trip as its own answer — the same rule the production-state
    fingerprint above follows.
    """
    from pydub import AudioSegment

    guard = conftest._restore_pydub_configuration.__wrapped__
    had_ffprobe = hasattr(AudioSegment, "ffprobe")
    if had_ffprobe:
        del AudioSegment.ffprobe
    before = AudioSegment.converter
    try:
        generator = guard()
        next(generator)
        AudioSegment.converter = str(tmp_path / "bin" / "ffmpeg.exe")
        AudioSegment.ffprobe = str(tmp_path / "bin" / "ffprobe.exe")
        with pytest.raises(StopIteration):
            next(generator)
        assert AudioSegment.converter == before
        assert not hasattr(AudioSegment, "ffprobe"), (
            "the guard reassigns but never removes, so an attribute a test "
            "invented survives it")
    finally:
        AudioSegment.converter = before
        if had_ffprobe:
            AudioSegment.ffprobe = before


def test_the_pydub_guard_is_autouse_so_no_test_has_to_remember_it():
    """A guard every test must opt into is a guard someone will forget."""
    fixture = conftest._restore_pydub_configuration
    # pytest 8 exposes the marker on a FixtureFunctionDefinition; older releases
    # attached it to the function itself. Ask for both rather than pin a version.
    marker = getattr(fixture, "_fixture_function_marker",
                     getattr(fixture, "_pytestfixturefunction", None))
    assert marker is not None, "the pydub guard is no longer a pytest fixture"
    assert marker.autouse is True
    assert marker.scope == "function"


def test_a_stand_in_pydub_is_left_alone():
    """Some fixtures inject a fake pydub; the guard must no-op for those."""
    sentinel = object()
    saved = sys.modules.get("pydub.utils")
    sys.modules["pydub.utils"] = sentinel  # type: ignore[assignment]
    try:
        assert conftest._pydub_modules() is None
        assert conftest._pydub_snapshot() is None
    finally:
        if saved is None:
            del sys.modules["pydub.utils"]
        else:
            sys.modules["pydub.utils"] = saved


# --------------------------------------------------------------------------- #
# G. v0.7.0 P04C (F3) -- the real canonical Qwen3 engine, guarded without walking it around every test
#
# Every engine here is a small synthetic one in tmp_path, fingerprinted through the guard's own functions with the paths
# ``conftest._canonical_engine_guard`` derives for that root. The real engine is never scanned or changed by a test.
# --------------------------------------------------------------------------- #
ENGINE_PER_TEST = ("the real nested Qwen3 engines folder", "the real canonical Qwen3 engine layout",
                   "the real canonical Qwen3 engine marker", "the real canonical Qwen3 engine launchers",
                   "the real canonical Qwen3 engine packages")
ENGINE_SESSION = ("the real canonical Qwen3 engine tree",)


def make_installed_engine(root: Path) -> Path:
    """A miniature of an installed canonical engine: identity file, launchers, packages several folders deep."""
    engine = root / ".venv" / "engines" / "qwen3"
    (engine / "Scripts").mkdir(parents=True)
    for name in ("python.exe", "pythonw.exe", "pip.exe", "activate.bat"):
        (engine / "Scripts" / name).write_bytes(b"launcher " + name.encode())
    (engine / "pyvenv.cfg").write_text("home = C:/base\ninclude-system-site-packages = false\nversion = 3.12.10\n",
                                       encoding="utf-8")
    (engine / "Include").mkdir()
    packages = engine / "Lib" / "site-packages"
    for package in ("torch", "transformers"):
        (packages / f"{package}-1.0.dist-info").mkdir(parents=True)
        (packages / f"{package}-1.0.dist-info" / "RECORD").write_text(f"{package}/__init__.py,,\n", encoding="utf-8")
        deep = packages / package / "nn" / "modules" / "__pycache__"
        deep.mkdir(parents=True)
        (packages / package / "__init__.py").write_text("import os\n", encoding="utf-8")
        (packages / package / "nn" / "modules" / "linear.py").write_text("WEIGHT = 1\n", encoding="utf-8")
        (deep / "linear.cpython-312.pyc").write_bytes(b"compiled")
    return engine


def engine_snapshots(root: Path):
    paths = conftest._canonical_engine_guard(root)
    return paths, conftest._snapshot(paths, ENGINE_PER_TEST), conftest._snapshot(paths, ENGINE_SESSION)


def changed(root: Path, per_test: dict, session: dict) -> tuple[set, set]:
    """The names of the engine entries that changed since the snapshots: (per-test ones, session ones)."""
    paths = conftest._canonical_engine_guard(root)

    def names(rows):
        return {row.split(" (")[0] for row in rows}

    return names(conftest._violations(per_test, paths)), names(conftest._violations(session, paths))


def test_the_real_engine_paths_are_the_ones_the_guard_watches_and_split_by_cost():
    expected = conftest._canonical_engine_guard(REPO_ROOT)
    assert expected["the real canonical Qwen3 engine layout"] == REPO_ROOT / ".venv" / "engines" / "qwen3"
    for name, path in expected.items():
        assert conftest._GUARDED_PATHS[name] == path
    assert set(ENGINE_PER_TEST) <= set(conftest._PER_TEST_GUARDED)
    assert not set(ENGINE_SESSION) & set(conftest._PER_TEST_GUARDED)  # the whole tree only at the session boundary
    assert set(ENGINE_PER_TEST) | set(ENGINE_SESSION) == set(expected)


def test_an_unchanged_installed_engine_raises_no_alarm_and_lock_files_beside_it_are_not_engine_files(tmp_path):
    make_installed_engine(tmp_path)
    _, per_test, session = engine_snapshots(tmp_path)
    assert all(value is not None for value in (*per_test.values(), *session.values()))
    # what a real lock acquisition leaves: the three empty lock files in the runtime folder, outside the engine
    locks = tmp_path / "files" / "runtime-data" / "qwen3"
    locks.mkdir(parents=True)
    for name in ("setup.lock", "inference.lock", "engine.lock"):
        (locks / name).write_bytes(b"")
    assert changed(tmp_path, per_test, session) == (set(), set())
    # ...while a lock file keeps its own (file) guard, which does see one appear
    assert conftest._fingerprint(locks / "engine.lock") != conftest._fingerprint(locks / "never-made.lock")


def test_an_engine_appearing_or_disappearing_is_attributed_to_the_test(tmp_path):
    _, per_test, session = engine_snapshots(tmp_path)  # nothing installed: every entry is "absent"
    assert set(per_test.values()) == {None}
    engine = make_installed_engine(tmp_path)
    per, whole = changed(tmp_path, per_test, session)
    assert per == set(ENGINE_PER_TEST) and whole == set(ENGINE_SESSION)

    _, per_test, session = engine_snapshots(tmp_path)
    shutil.rmtree(engine)
    per, whole = changed(tmp_path, per_test, session)
    assert per == set(ENGINE_PER_TEST) and whole == set(ENGINE_SESSION)


def test_a_package_installed_or_removed_is_attributed_to_the_test(tmp_path):
    engine = make_installed_engine(tmp_path)
    packages = engine / "Lib" / "site-packages"
    _, per_test, session = engine_snapshots(tmp_path)
    (packages / "numpy-2.5.4.dist-info").mkdir()
    assert "the real canonical Qwen3 engine packages" in changed(tmp_path, per_test, session)[0]

    _, per_test, session = engine_snapshots(tmp_path)
    shutil.rmtree(packages / "transformers-1.0.dist-info")
    assert "the real canonical Qwen3 engine packages" in changed(tmp_path, per_test, session)[0]

    _, per_test, session = engine_snapshots(tmp_path)
    (packages / "torch" / "extra.py").write_text("x\n", encoding="utf-8")  # a file added inside a package folder
    assert changed(tmp_path, per_test, session)[1] == set(ENGINE_SESSION)  # below the top level: the session walk


def test_two_snapshots_of_an_untouched_engine_are_equal_however_far_apart(tmp_path):
    """No false alarm from directory-listing timestamps: NTFS lets a listing's copy of a child folder's mtime lag."""
    engine = make_installed_engine(tmp_path)
    (engine / "Lib" / "site-packages" / "torch" / "late.py").write_text("x\n", encoding="utf-8")
    _, per_test, session = engine_snapshots(tmp_path)
    for _ in range(3):
        assert changed(tmp_path, per_test, session) == (set(), set())


def test_an_edit_deep_inside_a_package_is_caught_at_the_session_boundary(tmp_path):
    """The documented trade-off: a deep in-place edit changes no listing a test pays for; the session walk sees it."""
    engine = make_installed_engine(tmp_path)
    _, per_test, session = engine_snapshots(tmp_path)
    (engine / "Lib" / "site-packages" / "torch" / "nn" / "modules" / "linear.py").write_text("WEIGHT = 222\n",
                                                                                           encoding="utf-8")
    per, whole = changed(tmp_path, per_test, session)
    assert whole == set(ENGINE_SESSION)
    assert per == set(), "a per-test entry that walks the packages would be the multi-GB cost this split avoids"


def test_a_changed_identity_or_launcher_is_attributed_to_the_test(tmp_path):
    engine = make_installed_engine(tmp_path)
    cfg = engine / "pyvenv.cfg"
    _, per_test, session = engine_snapshots(tmp_path)
    stat = cfg.stat()
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("false", "FALSE"), encoding="utf-8")  # same size
    os.utime(cfg, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # and the timestamp put back
    assert "the real canonical Qwen3 engine marker" in changed(tmp_path, per_test, session)[0]

    _, per_test, session = engine_snapshots(tmp_path)
    (engine / "Scripts" / "python.exe").write_bytes(b"a different interpreter")
    assert "the real canonical Qwen3 engine launchers" in changed(tmp_path, per_test, session)[0]

    _, per_test, session = engine_snapshots(tmp_path)
    (engine / "share").mkdir()  # a new top-level folder in the engine
    assert "the real canonical Qwen3 engine layout" in changed(tmp_path, per_test, session)[0]


def test_an_engine_folder_replaced_by_a_file_is_detected(tmp_path):
    engines = tmp_path / ".venv" / "engines"
    engines.mkdir(parents=True)
    _, per_test, session = engine_snapshots(tmp_path)
    (engines / "qwen3").write_bytes(b"not an environment")
    per, _ = changed(tmp_path, per_test, session)
    assert {"the real nested Qwen3 engines folder", "the real canonical Qwen3 engine layout"} <= per


def test_the_per_test_check_never_walks_the_packages(tmp_path, monkeypatch):
    engine = make_installed_engine(tmp_path)
    packages = engine / "Lib" / "site-packages"
    paths = conftest._canonical_engine_guard(tmp_path)
    scanned = []
    real = conftest._REAL_SCANDIR

    def counting(path):
        scanned.append(Path(path))
        return real(path)

    monkeypatch.setattr(conftest, "_REAL_SCANDIR", counting)
    conftest._snapshot(paths, ENGINE_PER_TEST)
    folders = {p for p in scanned if p.is_dir()}  # (pyvenv.cfg is offered to scandir once, refused as a file, hashed)
    assert folders == {engine.parent, engine, engine / "Scripts", packages}  # one level each; Scripts is flat
    assert not any(p.is_relative_to(packages) and p != packages for p in scanned)

    scanned.clear()
    conftest._snapshot(paths, ENGINE_SESSION)  # the session walk, by contrast, goes all the way down
    assert packages / "torch" / "nn" / "modules" / "__pycache__" in set(scanned)


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows construct")
def test_the_engine_walks_do_not_follow_a_junction_out_of_the_engine(tmp_path):
    engine = make_installed_engine(tmp_path)
    outside = tmp_path / "outside"
    (outside / "deep").mkdir(parents=True)
    (outside / "deep" / "big.bin").write_bytes(b"x")
    link = engine / "Lib" / "site-packages" / "escape"
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True).returncode == 0
    if not made:
        pytest.skip("this account may not create a junction")
    _, per_test, session = engine_snapshots(tmp_path)
    tree = session["the real canonical Qwen3 engine tree"]
    assert ("qwen3/Lib/site-packages/escape@", -2, -2) in tree
    assert not any("big.bin" in row[0] for row in tree)
    _, rows = per_test["the real canonical Qwen3 engine packages"]
    kinds = dict(rows)
    assert kinds["escape"] == "link"
    (outside / "deep" / "big.bin").write_bytes(b"changed outside the engine")
    assert changed(tmp_path, per_test, session) == (set(), set())


def test_every_previously_guarded_path_is_still_guarded_with_the_same_attribution():
    per_test = set(conftest._PER_TEST_GUARDED)
    for name in ("the real requirements stamp", "the real import proof", "the real Kokoro proof",
                 "the real FFmpeg pin", "the real installed FFmpeg build", "the real FFmpeg staging tree",
                 "the real Qwen3 environment marker", "the real Qwen3 environment launchers",
                 "the real nested Qwen3 engines folder", "the real Qwen3 install record", "the real Qwen3 engine lock",
                 "the real Qwen3 local transcripts", "the real Qwen3 transcript selection",
                 "the real Qwen3 model folder", "the real Qwen3 job folder", "the real Qwen3 failure record"):
        assert name in per_test and name in conftest._GUARDED_PATHS
    assert "the real setup log directory" not in per_test
    assert conftest._GUARDED_PATHS["the real Qwen3 environment marker"] == REPO_ROOT / ".venv-qwen3" / "pyvenv.cfg"
    assert conftest._GUARDED_PATHS["the real Qwen3 engine lock"] == \
        REPO_ROOT / "files" / "runtime-data" / "qwen3" / "engine.lock"
    # every entry outside the engine keeps the full, link-following fingerprint it always had (v0.8.2 Phase 5A: the
    # independent engine environments folder is an engine path too, listed one level deep like the nested one)
    for name in conftest._GUARDED_PATHS:
        if name not in set(ENGINE_PER_TEST) | set(ENGINE_SESSION) | {"the real independent engine environments"}:
            assert name not in conftest._SHALLOW_GUARDED and name not in conftest._LINK_SAFE_TREES
