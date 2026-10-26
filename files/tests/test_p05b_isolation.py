"""Stage 4C controls: disposable failures must be visible at the write boundary."""

import importlib.util
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import conftest
import write_tripwire as tripwire
from tts import qwen3_runtime as rt


def test_a_numba_cache_disguised_as_python_bytecode_is_reported_and_refused(tmp_path):
    production = tmp_path / "production" / "librosa" / "__pycache__"
    production.mkdir(parents=True)
    for name in ("kernel.nbi", "kernel.nbc", "kernel.pyc", "new-directory"):
        start = len(tripwire.refusals)
        with tripwire.armed([production.parent]) as attempts, pytest.raises(PermissionError):
            if name == "new-directory":
                (production / name).mkdir(exist_ok=True)
            else:
                (production / name).write_bytes(b"native cache")
        assert len(attempts) == 1 and len(tripwire.refusals) == start + 1
        assert not tripwire.refusal_details[-1]["bytecode"]
        assert not (production / name).exists()


def test_existing_cache_directory_mkdir_refusal_cannot_be_swallowed_silently(tmp_path):
    with tripwire.armed([tmp_path]) as attempts:
        tmp_path.mkdir(exist_ok=True)  # pathlib swallows PermissionError when the directory exists
    assert attempts == [("os.mkdir", str(tmp_path))]


def test_removed_calm_redirect_is_refused_by_the_outer_guard(tmp_path):
    production, sandbox = tmp_path / "production", tmp_path / "sandbox"
    (production / "files").mkdir(parents=True)
    (sandbox / "files").mkdir(parents=True)
    with pytest.MonkeyPatch.context() as parent:
        parent.setattr(rt, "repo_root", lambda: production)
        with tripwire.armed([production]) as attempts:
            with pytest.MonkeyPatch.context() as redirect:
                redirect.setattr(rt, "repo_root", lambda: sandbox)
                assert Path(rt.worker_environment()["TEMP"]).is_relative_to(sandbox)
            with pytest.raises(PermissionError, match="write tripwire"):
                rt.worker_environment()
    assert attempts and not (production / "files/runtime-data").exists()


def test_calm_containment_survives_inner_undo_and_errors(tmp_path, monkeypatch):
    from test_qwen3_calm_harness import calm_runtime

    original = rt.repo_root
    original_temp = os.environ.get("TEMP")
    fixture = calm_runtime.__wrapped__(tmp_path)
    root = next(fixture)
    try:
        monkeypatch.setenv("ACT_SYNTHETIC_FAULT", "1")
        monkeypatch.undo()
        with pytest.raises(RuntimeError), pytest.MonkeyPatch.context() as inner:
            inner.setenv("ACT_SYNTHETIC_FAULT", "2")
            raise RuntimeError("fault in contained operation")
        assert rt.repo_root() == root
        assert Path(rt.worker_environment()["TEMP"]).is_relative_to(root)
        assert Path(os.environ["TEMP"]).is_relative_to(root)
    finally:
        fixture.close()
    assert rt.repo_root is original and os.environ.get("TEMP") == original_temp


def test_numba_compiles_and_writes_only_the_contained_cache(tmp_path):
    import numba

    assert not numba.config.DISABLE_JIT
    assert Path(numba.config.CACHE_DIR) == conftest.NUMBA_TEST_CACHE
    assert numba.config.CACHE_LOCATOR_CLASSES == "UserProvidedCacheLocator"
    source = tmp_path / "compiled_probe.py"
    source.write_text("from numba import njit\n@njit(cache=True)\ndef square(x):\n    return x * x\n")
    spec = importlib.util.spec_from_file_location("compiled_probe", source)
    module = importlib.util.module_from_spec(spec)
    # Keep a regular module identity so Numba's compiled-cache deserialization works too.
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        assert module.square(7) == 49 and module.square.signatures
        assert Path(module.square._cache._impl.locator.get_cache_path()).is_relative_to(conftest.NUMBA_TEST_CACHE)
        assert list(conftest.NUMBA_TEST_CACHE.rglob("compiled_probe.square*.nbc"))
        assert list(conftest.NUMBA_TEST_CACHE.rglob("compiled_probe.square*.nbi"))
    assert not (tmp_path / "__pycache__").exists()


def test_numba_cache_failure_cannot_fall_back_to_the_installed_library(tmp_path, monkeypatch):
    import numba

    source = tmp_path / "source.py"
    source.write_text("def kernel(x):\n    return x + 1\n")
    namespace = {}
    exec(compile(source.read_text(), str(source), "exec"), namespace)
    unavailable = tmp_path / "unavailable-cache"
    monkeypatch.setattr(numba.config, "CACHE_DIR", str(unavailable))
    with tripwire.armed([unavailable]) as attempts, pytest.raises(RuntimeError, match="no locator available"):
        numba.njit(cache=True)(namespace["kernel"])
    assert attempts and not unavailable.exists() and not (tmp_path / "__pycache__").exists()


def test_process_lifetime_guard_catches_collection_setup_body_teardown_import_and_atexit(tmp_path):
    """A fresh copied runner protects a synthetic production tree through shutdown."""
    app = tmp_path / "guard-app"
    tests = app / "files/tests"
    tests.mkdir(parents=True)
    for name in ("guarded_pytest.py", "write_tripwire.py"):
        shutil.copyfile(Path(__file__).with_name(name), tests / name)
    output = app / "files/dev-work/p05b-stage4c"
    output.mkdir(parents=True)
    protected = app / "files/runtime-data"
    protected.mkdir()
    helper = tests / "side_effect.py"
    helper.write_text("from pathlib import Path\n"
                      f"try: Path({str(protected / 'import')!r}).mkdir()\nexcept PermissionError: pass\n")
    probe = tests / "test_phases.py"
    probe.write_text("import atexit, sys\nfrom pathlib import Path\nimport pytest\n"
                     f"sys.path.insert(0, {str(tests)!r})\nimport side_effect\n"
                     f"ROOT = Path({str(protected)!r})\n"
                     "def write(phase):\n"
                     "    try: (ROOT / phase).mkdir()\n"
                     "    except PermissionError: pass\n"
                     "write('collection')\natexit.register(write, 'atexit')\n"
                     "@pytest.fixture\ndef phases():\n    write('setup')\n    yield\n    write('teardown')\n"
                     "def test_body(phases):\n    write('call')\n")
    config, report = output / "config.json", output / "audit.json"
    config.write_text(json.dumps({"version": 1, "process_sites": {}, "tools": {}}))
    result = subprocess.run([sys.executable, "-I", "-B", str(tests / "guarded_pytest.py"), str(config), str(report),
                             str(probe), "-q", "-p", "no:cacheprovider", f"--basetemp={output / 'tmp'}"],
                            capture_output=True, text=True, timeout=60)
    audit = json.loads(report.read_text())
    assert result.returncode == 1 and audit["pytest_exit"] == 0, result.stdout + result.stderr
    assert audit["counts"]["passed"] == 1 and audit["outer_exit"] == 1
    assert {Path(item["path"]).name for item in audit["raw_refusals"]} == \
        {"import", "collection", "setup", "call", "teardown", "atexit"}
    assert len(audit["unintended_production_refusals"]) == 6
    assert all(item["stack"] for item in audit["raw_refusals"])
    assert any(item["test"].endswith("(setup)") for item in audit["raw_refusals"])
    assert any(item["test"].endswith("(teardown)") for item in audit["raw_refusals"])
    assert list(protected.iterdir()) == []


def test_process_policy_requires_pinned_sources_and_contained_destinations(tmp_path):
    from guarded_pytest import ProcessPolicy, ROOT

    source = Path(__file__)
    rel = source.relative_to(ROOT).as_posix()
    entry = {"sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
             "functions": ["test_process_policy_requires_pinned_sources_and_contained_destinations"]}
    config = {"version": 1, "process_sites": {rel: entry}, "tools": {}}
    policy = ProcessPolicy(config, tmp_path)
    good = [sys.executable, "-c", f"open({str(tmp_path / 'allowed')!r}, 'w').close()"]
    assert policy.approve(good, None)
    bad = [sys.executable, "-c", f"open({str(ROOT / '.venv' / 'forbidden')!r}, 'w').close()"]
    with pytest.raises(PermissionError, match="unqualified child"):
        policy.audit("subprocess.Popen", (sys.executable, bad, None, {}))
    assert len(policy.refused) == 1
    entry["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="changed reviewed process source"):
        ProcessPolicy(config, tmp_path)


def test_process_policy_refuses_a_junction_crossing_its_disposable_boundary(tmp_path):
    from guarded_pytest import ProcessPolicy
    from test_optional_tts_setup import _junction

    sandbox, elsewhere = tmp_path / "sandbox", tmp_path / "elsewhere"
    sandbox.mkdir()
    elsewhere.mkdir()
    assert _junction(sandbox / "escape", elsewhere), "this qualification requires the existing junction capability"
    policy = ProcessPolicy({"version": 1, "process_sites": {}, "tools": {}}, sandbox)
    assert policy.disposable(sandbox / "safe")
    assert not policy.disposable(sandbox / "escape" / "native-output")


def test_packaging_git_permission_cannot_write_the_production_repo_or_redirected_gitdir(tmp_path):
    from guarded_pytest import ProcessPolicy, ROOT

    policy = ProcessPolicy({"version": 1, "process_sites": {}, "tools": {}}, tmp_path)
    options = ["-c", "user.name=packager-test", "-c", "user.email=packager-test@example.invalid",
               "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false"]
    assert policy.git_profile(["git", "-C", str(ROOT), "ls-files", "-z", "--", "scripts"], None)
    assert policy.git_profile(["git", "-C", str(ROOT), *options, "add", "-A", "-f"], None) is None
    assert policy.git_profile(["git", "-C", str(tmp_path), *options, "init", "-q"], None)
    assert policy.git_profile(["git", "-C", str(tmp_path), *options, "push"], None) is None
    (tmp_path / ".git").write_text("gitdir: outside-this-fixture\n")
    assert policy.git_profile(["git", "-C", str(tmp_path), *options, "add", "-A", "-f"], None) is None
