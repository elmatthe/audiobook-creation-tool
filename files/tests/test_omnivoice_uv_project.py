"""v0.8.2 Phase 5B -- the OmniVoice engine's uv project is an exact translation of the sets v0.8.1 pinned.

``scripts/tts/engines/omnivoice/pyproject.toml`` and its ``uv.lock`` are what the production installer now syncs into
``.venv-engines/omnivoice``. On each supported platform the lock must install exactly the artifacts
``scripts/tts/omnivoice_packages.json`` pinned at v0.8.1 -- 88 on Windows x64, 86 on an Apple Silicon Mac -- by name,
version, file and SHA-256: torch and torchaudio 2.8.0+cu128 only from the explicit CUDA 12.8 index on Windows, the plain
PyPI 2.8.0 on a Mac, nothing else from anywhere but PyPI, and nothing built from source. The model is not a package
(``omnivoice_manifest.json``). No dependency is upgraded here: a re-lock that moved anything fails these tests before
it could reach an installer.

"What the lock installs" is derived from the lock itself, the way an installer reads it: the dependency graph walked
from the project under the platform's markers, and for each package the most specific wheel by the standard tag order
(``packaging.tags``) of CPython 3.12 on ``win_amd64``, or on macOS 15 arm64 (where the Mac set was acquired; on an older
macOS uv may take another wheel of the same version, also hashed in the lock).
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from urllib.parse import unquote

import pytest
from packaging import tags
from packaging.markers import Marker
from packaging.utils import parse_wheel_filename

from shared import engine_env, uv_runner
from tts import omnivoice_runtime as ov
from tts.engines import registry

REPO = Path(__file__).resolve().parents[2]
PROJECT = REPO / "scripts" / "tts" / "engines" / "omnivoice"
CU128 = "https://download.pytorch.org/whl/cu128"
PYPI = "https://pypi.org/simple"
WINDOWS_X64 = "sys_platform == 'win32' and platform_machine == 'AMD64'"
MAC_ARM64 = "sys_platform == 'darwin' and platform_machine == 'arm64'"
PLATFORMS = {
    "windows": {"markers": {"sys_platform": "win32", "platform_machine": "AMD64", "platform_system": "Windows",
                            "os_name": "nt"},
                "tags": ["win_amd64"], "count": 88},
    "mac": {"markers": {"sys_platform": "darwin", "platform_machine": "arm64", "platform_system": "Darwin",
                        "os_name": "posix"},
            "tags": list(tags.mac_platforms(version=(15, 0), arch="arm64")), "count": 86},
}


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pyproject() -> dict:
    return tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))


def _lock() -> dict:
    return tomllib.loads((PROJECT / "uv.lock").read_text(encoding="utf-8"))


def _reference(platform: str) -> dict:
    """The v0.8.1 set of *platform*: ``{name: (version, filename, sha256, size)}``."""
    data = json.loads(ov.packages_path().read_text(encoding="utf-8"))
    wheels = data["wheels"] if platform == "windows" else data["darwin_arm64"]["wheels"]
    return {_norm(w["name"]): (w["version"], w["filename"], w["sha256"], w["size"]) for w in wheels}


def _environment(platform: str) -> dict:
    env = {"python_version": "3.12", "python_full_version": "3.12.15", "implementation_name": "cpython",
           "platform_python_implementation": "CPython", "platform_release": "", "platform_version": "",
           "extra": ""}
    return {**env, **PLATFORMS[platform]["markers"]}


def _installed(platform: str) -> dict:
    """What the lock installs on *platform*: ``{name: (version, filename, sha256, source, size)}``."""
    lock = _lock()
    by_key = {}
    for package in lock["package"]:
        by_key.setdefault(package["name"], []).append(package)
    env = _environment(platform)

    def resolve(dep: dict) -> dict:
        candidates = [p for p in by_key[dep["name"]]
                      if ("version" not in dep or p["version"] == dep["version"])
                      and ("source" not in dep or p["source"] == dep["source"])]
        assert len(candidates) == 1, dep
        return candidates[0]

    (root,) = [p for p in lock["package"] if p["source"] == {"virtual": "."}]
    seen: dict[str, dict] = {}
    pending = [root]
    while pending:
        package = pending.pop()
        for dep in package.get("dependencies", []):
            if "marker" in dep and not Marker(dep["marker"]).evaluate(env):
                continue
            target = resolve(dep)
            if target["name"] in seen:
                assert seen[target["name"]] is target, f"two versions of {target['name']} on {platform}"
                continue
            seen[target["name"]] = target
            pending.append(target)

    order = {tag: rank for rank, tag in enumerate(
        list(tags.cpython_tags(python_version=(3, 12), abis=["cp312"], platforms=PLATFORMS[platform]["tags"]))
        + list(tags.compatible_tags(python_version=(3, 12), interpreter="cp312",
                                    platforms=PLATFORMS[platform]["tags"])))}
    installed = {}
    for name, package in seen.items():
        best = None
        for wheel in package.get("wheels", []):
            filename = unquote(wheel["url"].rsplit("/", 1)[1])
            rank = min((order[t] for t in parse_wheel_filename(filename)[3] if t in order), default=None)
            if rank is not None and (best is None or rank < best[0]):
                best = (rank, filename, wheel["hash"].removeprefix("sha256:"), wheel.get("size"))
        assert best is not None, f"{name} has no wheel for {platform}: it would be built from source"
        installed[_norm(name)] = (package["version"], best[1], best[2], package["source"], best[3])
    return installed


def test_the_project_is_the_registry_s_and_installs_nothing_of_its_own():
    assert registry.definition("omnivoice").project == "scripts/tts/engines/omnivoice"
    assert engine_env.project_dir(REPO, "omnivoice") == PROJECT == ov.project_dir()
    data = _pyproject()
    assert data["project"]["name"] == "act-omnivoice-engine" and data["project"]["requires-python"] == "==3.12.*"
    uv = data["tool"]["uv"]
    assert uv["package"] is False and uv["no-build"] is True  # a virtual project; no source build, ever
    assert uv["environments"] == [WINDOWS_X64, MAC_ARM64]  # no Windows CPU-only build, no Intel Mac
    lock = _lock()
    assert lock["requires-python"] == "==3.12.*"
    assert lock["supported-markers"] == ["platform_machine == 'AMD64' and sys_platform == 'win32'",
                                         "platform_machine == 'arm64' and sys_platform == 'darwin'"]
    virtual = [(p["name"], p["version"]) for p in lock["package"] if p["source"] == {"virtual": "."}]
    assert virtual == [("act-omnivoice-engine", "0.0.0")]


@pytest.mark.parametrize("platform", sorted(PLATFORMS))
def test_on_each_platform_the_lock_installs_exactly_the_v0_8_1_set(platform):
    """Same names, versions, files and SHA-256 -- 88 on Windows, 86 on a Mac -- and not one package more or less."""
    installed, reference = _installed(platform), _reference(platform)
    assert len(installed) == len(reference) == PLATFORMS[platform]["count"]
    assert {n: i[:3] for n, i in installed.items()} == {n: r[:3] for n, r in reference.items()}
    for name, (*_, size) in installed.items():  # where the lock records a size, it is the reference's
        assert size is None or size == reference[name][3], name


@pytest.mark.parametrize("platform", sorted(PLATFORMS))
def test_torch_and_torchaudio_come_only_from_the_platform_s_index_and_nothing_else_leaves_pypi(platform):
    installed = _installed(platform)
    expected = ("2.8.0+cu128", CU128) if platform == "windows" else ("2.8.0", PYPI)
    for name in ("torch", "torchaudio"):
        version, filename, _sha, source, _size = installed[name]
        assert (version, source) == (expected[0], {"registry": expected[1]}), name
        tag = "win_amd64" if platform == "windows" else "macosx_11_0_arm64"
        assert filename.endswith(f"-{tag}.whl") and filename.startswith(f"{name}-{expected[0]}-cp312-"), filename
    others = {n: i[3] for n, i in installed.items() if n not in ("torch", "torchaudio")}
    assert set(map(str, others.values())) == {str({"registry": PYPI})}  # no other index, no URL, no path, no fallback


def test_the_cuda_index_is_explicit_and_only_windows_torch_uses_it():
    data = _pyproject()
    assert data["tool"]["uv"]["index"] == [{"name": "pytorch-cu128", "url": CU128, "explicit": True}]
    for name in ("torch", "torchaudio"):
        assert data["tool"]["uv"]["sources"][name] == [{"index": "pytorch-cu128", "marker": "sys_platform == 'win32'"}]
    assert set(data["tool"]["uv"]["sources"]) == {"torch", "torchaudio"}
    assert {p["source"]["registry"] for p in _lock()["package"] if "registry" in p["source"]} == {PYPI, CU128}


def test_every_package_is_pinned_by_a_constraint_to_the_version_v0_8_1_reviewed():
    """Re-locking can never drift: every package of either set is constrained to its exact version."""
    constraints = {}
    for line in _pyproject()["tool"]["uv"]["constraint-dependencies"]:
        requirement, _, marker = line.partition(";")
        name, version = requirement.strip().split("==")
        constraints.setdefault(_norm(name), set()).add((version, marker.strip()))
    for platform in PLATFORMS:
        env = _environment(platform)
        for name, (version, *_rest) in _reference(platform).items():
            pinned = {v for v, marker in constraints[name] if not marker or Marker(marker).evaluate(env)}
            assert pinned == {version}, (platform, name, pinned)


def test_the_download_shown_before_an_install_is_every_pinned_wheel_of_this_platform():
    """``uv.lock`` records no size for the PyTorch index's wheels, so the reference keeps every file's size."""
    cu128_sizes = [w.get("size") for p in _lock()["package"] if p["source"] == {"registry": CU128}
                   for w in p["wheels"]]
    assert cu128_sizes == [None, None]
    reference = _reference("windows" if ov._system() != "darwin" else "mac")
    assert ov.wheels_total_bytes() == sum(size for *_, size in reference.values())
    assert 3_400_000_000 < sum(size for *_, size in _reference("windows").values()) < 4_000_000_000
    assert 200_000_000 < sum(size for *_, size in _reference("mac").values()) < 300_000_000


def test_the_model_manifest_holds_only_the_model_and_the_package_reference_only_packages():
    model = json.loads(ov.manifest_path().read_text(encoding="utf-8"))
    assert ov.manifest_problems(model) == [] and model["version"] == 2
    assert not {"packages", "wheels", "installed_bytes", "darwin_arm64"} & set(model)
    assert model["engine"]["omnivoice"] == "0.2.1" and model["model"]["revision"]
    packages = json.loads(ov.packages_path().read_text(encoding="utf-8"))
    assert ov.packages_problems(packages) == [] and "model" not in packages and "licenses" not in packages


def test_the_lock_identity_a_receipt_binds_to_ignores_line_endings(tmp_path):
    for name in ("pyproject.toml", "uv.lock"):
        data = (PROJECT / name).read_bytes().replace(b"\r\n", b"\n")
        (tmp_path / name).write_bytes(data.replace(b"\n", b"\r\n"))
    assert uv_runner.lock_identity(REPO, project=tmp_path) == engine_env.lock_identity(REPO, "omnivoice")
    assert engine_env.lock_identity(REPO, "omnivoice")["uv"] == uv_runner.UV_VERSION


@pytest.mark.parametrize("platform, link", [("win32", "copy"), ("darwin", "clone")])
def test_the_production_sync_is_locked_cacheless_compiled_and_never_hardlinks(platform, link):
    command = engine_env.sync_command(REPO, "omnivoice", platform=platform)
    for word in ("--no-dev", "--locked", "--no-cache", "--compile-bytecode"):
        assert word in command
    assert command[command.index("--link-mode") + 1] == link
    assert "--offline" not in command and "--upgrade" not in command and "hardlink" not in command
