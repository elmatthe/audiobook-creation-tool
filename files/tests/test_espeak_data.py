"""v0.6.1 Plan 4 Phase 13A.2 — the eSpeak data-path seam.

Kokoro's English G2P dies on this Mac before any Python handler can run: eSpeak NG
copies the data path it is given into a fixed 160-byte buffer as
``"<path>/espeak-ng-data"``, and the project's own install path is longer than
that. The truncated path does not exist, so the library falls back to the path
compiled into the wheel on its *build machine*, fails to open ``phontab`` and
calls ``exit()``. Measured: the bundled directory is 162 characters here, and the
boundary is exactly where the arithmetic says — a 144-character root works, 145
does not.

Everything below is deterministic. No model is downloaded, no network is used,
no native library is initialised, and the fixtures are ordinary temporary
directories: the seam is a path calculation plus one link, and that is what is
proved.
"""

from __future__ import annotations

import ast
import inspect
import os
import sys
from pathlib import Path

import pytest

from shared import espeak_data


@pytest.fixture(autouse=True)
def _forget_process_answer():
    espeak_data.reset_cache()
    yield
    espeak_data.reset_cache()


class FakeLoader:
    """Stands in for ``espeakng_loader`` — the seam must ask, never assume."""

    def __init__(self, data_path, *, raises: bool = False):
        self._data_path = str(data_path)
        self._raises = raises

    def get_data_path(self):
        if self._raises:
            raise RuntimeError("data path not exists")
        return self._data_path


def make_data_dir(root: Path) -> Path:
    """A directory shaped like the wheel's: named espeak-ng-data, holding phontab."""
    data = root / espeak_data.DATA_DIR_NAME
    data.mkdir(parents=True, exist_ok=True)
    (data / "phontab").write_bytes(b"\x00")
    return data


def deep_dir(tmp_path: Path, length: int) -> Path:
    """A real directory whose absolute path is at least *length* characters."""
    current = tmp_path
    while len(str(current)) < length:
        current = current / ("d" * 24)
    current.mkdir(parents=True, exist_ok=True)
    return current


# --------------------------------------------------------------------------- #
# The measured rule: eSpeak NG's fixed path_home buffer
# --------------------------------------------------------------------------- #


def test_the_limit_is_the_libraries_own_buffer_size():
    assert espeak_data.PATH_HOME_LIMIT == 160
    assert espeak_data.DATA_DIR_NAME == "espeak-ng-data"


def test_the_boundary_sits_where_the_arithmetic_says(tmp_path):
    """144 characters of root fit; 145 do not. Measured against the real library."""
    budget = espeak_data.PATH_HOME_LIMIT - len(os.sep) - len(espeak_data.DATA_DIR_NAME)
    fitting = "r" * (budget - 1)
    assert espeak_data.root_fits(fitting)
    assert not espeak_data.root_fits("r" * budget)


# --------------------------------------------------------------------------- #
# Discovery — dynamic, and truthful when the capability is genuinely absent
# --------------------------------------------------------------------------- #


def test_the_bundled_directory_is_discovered_from_the_installed_package(tmp_path):
    data = make_data_dir(tmp_path / "pkg")
    assert espeak_data.bundled_data_dir(FakeLoader(data)) == data


def test_a_loader_without_usable_data_answers_none(tmp_path):
    """No phontab means no capability — and the seam says so instead of guessing."""
    empty = tmp_path / "pkg" / espeak_data.DATA_DIR_NAME
    empty.mkdir(parents=True)
    assert espeak_data.bundled_data_dir(FakeLoader(empty)) is None
    assert espeak_data.bundled_data_dir(FakeLoader(empty, raises=True)) is None


def test_no_espeak_installed_changes_nothing_and_raises_nothing(monkeypatch):
    """A venv without the optional wheel behaves exactly as it does today."""
    monkeypatch.setattr(espeak_data, "bundled_data_dir", lambda *a, **k: None)
    environ: dict = {}
    assert espeak_data.configure(environ=environ) is None
    assert environ == {}


def test_no_user_or_machine_path_is_hardcoded():
    """Every path is computed; the only absolute paths in the file are prose."""
    source = Path(inspect.getfile(espeak_data)).read_text(encoding="utf-8")
    module = ast.parse(source)
    docstring_nodes = set()
    for node in ast.walk(module):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstring_nodes.add(id(first.value))
    for node in ast.walk(module):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstring_nodes:
                continue
            assert not node.value.startswith(("/Users", "/home", "/var", "C:\\")), node.value
            assert "espeakng-loader" not in node.value


# --------------------------------------------------------------------------- #
# The no-op case: an installation whose paths already fit
# --------------------------------------------------------------------------- #


def test_an_installation_that_already_fits_is_left_completely_alone(tmp_path):
    """This is every machine Kokoro works on today, Windows included.

    No link, no environment variable, no override of what misaki configured —
    the seam exists for the overflow case and must be invisible otherwise.
    """
    data = make_data_dir(tmp_path / "short")
    assert espeak_data.root_fits(data) and espeak_data.root_fits(data.parent)
    environ: dict = {}
    assert espeak_data.configure(data_dir=data, environ=environ) is None
    assert environ == {}
    assert not (tmp_path / "short" / "linked").exists()


# --------------------------------------------------------------------------- #
# The overflow case: a short root, linked, never copied
# --------------------------------------------------------------------------- #


def test_a_path_too_long_is_relinked_under_a_root_that_fits(tmp_path):
    data = make_data_dir(deep_dir(tmp_path / "deep", 150))
    assert not espeak_data.root_fits(data)
    short = tmp_path / "s"
    environ: dict = {}

    root = espeak_data.configure(data_dir=data, candidates=[short], environ=environ)

    assert root == str(short)
    assert espeak_data.root_fits(root)
    link = short / espeak_data.DATA_DIR_NAME
    assert (link / "phontab").exists(), "eSpeak must reach the real tables"
    assert environ["ESPEAK_DATA_PATH"] == str(short)


def test_the_bundled_data_is_linked_and_never_copied(tmp_path):
    """The wheel stays the one source of the data; the seam adds a pointer."""
    data = make_data_dir(deep_dir(tmp_path / "deep", 150))
    short = tmp_path / "s"
    espeak_data.configure(data_dir=data, candidates=[short], environ={})
    link = short / espeak_data.DATA_DIR_NAME
    if sys.platform == "win32":          # a junction reports as a directory
        assert (link / "phontab").exists()
    else:
        assert link.is_symlink()
        assert Path(os.readlink(link)) == data


def test_configuring_twice_is_idempotent(tmp_path):
    data = make_data_dir(deep_dir(tmp_path / "deep", 150))
    short = tmp_path / "s"
    environ: dict = {}
    first = espeak_data.configure(data_dir=data, candidates=[short], environ=environ)
    before = sorted(p.name for p in short.iterdir())
    second = espeak_data.configure(data_dir=data, candidates=[short], environ=environ)
    assert first == second
    assert sorted(p.name for p in short.iterdir()) == before == [espeak_data.DATA_DIR_NAME]


def test_a_candidate_that_is_itself_too_long_is_skipped_for_one_that_fits(tmp_path):
    data = make_data_dir(deep_dir(tmp_path / "deep", 150))
    too_long = deep_dir(tmp_path / "also-deep", 150)
    short = tmp_path / "s"
    root = espeak_data.configure(data_dir=data, candidates=[too_long, short],
                                 environ={})
    assert root == str(short)
    assert not (too_long / espeak_data.DATA_DIR_NAME).exists()


def test_when_no_candidate_can_be_used_the_failure_stays_truthful(tmp_path):
    """No silent success, no exception: the caller is told nothing was done."""
    data = make_data_dir(deep_dir(tmp_path / "deep", 150))
    only = deep_dir(tmp_path / "still-deep", 150)
    environ: dict = {}
    assert espeak_data.configure(data_dir=data, candidates=[only],
                                 environ=environ) is None
    assert environ == {}


def test_the_link_step_is_explicit_about_the_platform(tmp_path, monkeypatch):
    """A symlink first; the Windows junction fallback is a named branch, not luck."""
    data = make_data_dir(tmp_path / "pkg")

    def refuse(*_args, **_kwargs):
        raise OSError("symlinks are not permitted here")

    monkeypatch.setattr(os, "symlink", refuse)
    monkeypatch.setattr(sys, "platform", "linux")
    assert espeak_data._link_to(data, tmp_path / "s" / espeak_data.DATA_DIR_NAME) is False

    source = inspect.getsource(espeak_data._link_to)
    assert 'sys.platform == "win32"' in source
    assert "CreateJunction" in source


def test_the_default_candidates_live_in_ignored_runtime_data():
    from shared import paths

    first = espeak_data.candidate_roots()[0]
    assert first.parent == paths.RESOURCES_DIR, "project scratch, already git-ignored"
    assert len(espeak_data.candidate_roots()) > 1, "a fallback for a deep checkout"


# --------------------------------------------------------------------------- #
# One contract, applied in the same place by runtime and by setup
# --------------------------------------------------------------------------- #


def test_the_runtime_configures_after_importing_kokoro_and_before_the_pipeline():
    """Ordering is the whole point: misaki sets the long path at import time, and
    building the pipeline is what first opens it in native code."""
    from tts import kokoro_synth

    events: list[str] = []

    class FakeKPipeline:
        def __init__(self, lang_code):
            events.append(f"pipeline:{lang_code}")

    fake_module = type(sys)("kokoro")
    fake_module.KPipeline = FakeKPipeline
    sys.modules["kokoro"] = fake_module
    original = espeak_data.configure
    try:
        espeak_data.configure = lambda *a, **k: events.append("configure")
        kokoro_synth._instantiate_pipeline("a")
    finally:
        espeak_data.configure = original
        sys.modules.pop("kokoro", None)

    assert events == ["configure", "pipeline:a"]


def test_setup_and_runtime_share_one_espeak_contract():
    """Not two hacks: the bootstrap subprocesses call the same function."""
    from shared import bootstrap

    preamble = bootstrap.KOKORO_SUBPROCESS_PREAMBLE
    assert "from shared import espeak_data" in preamble
    assert str(bootstrap.SCRIPTS_DIR) in preamble

    for function in (bootstrap.warmup_kokoro_pipeline, bootstrap.predownload_kokoro):
        source = inspect.getsource(function)
        assert "KOKORO_SUBPROCESS_PREAMBLE" in source, function.__name__
        assert "espeak_data.configure()" in source, function.__name__
        assert source.index("from kokoro import KPipeline") < source.index(
            "espeak_data.configure()"), f"{function.__name__} must configure after the import"
        assert source.index("espeak_data.configure()") < source.index(
            "KPipeline(lang_code="), f"{function.__name__} must configure before the pipeline"
