"""v0.8.2 Phase 5A — the Qwen3 engine's uv project is an exact translation of the pins v0.8.1 reviewed.

``scripts/tts/engines/qwen3/pyproject.toml`` and its ``uv.lock`` are what the production installer now syncs. They must
install exactly the 89 artifacts ``scripts/qwen3-requirements.txt`` pins and ``scripts/qwen3-artifacts.json`` reviewed
(same names, versions and wheel hashes; torch/torchaudio 2.10.0+cu128 only from the explicit CUDA 12.8 index; sox as
ACT's own commit-pinned derivative wheel; Windows x64 only; nothing built from source). No dependency is upgraded here:
a re-lock that moved anything fails these tests before it could reach an installer.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from urllib.parse import unquote

import pytest

from shared import engine_env, uv_runner
from tts import qwen3_package_manifest as qm
from tts import qwen3_wheels
from tts.engines import registry

REPO = Path(__file__).resolve().parents[2]
PROJECT = REPO / "scripts" / "tts" / "engines" / "qwen3"
CU128 = "https://download.pytorch.org/whl/cu128"
PYPI = "https://pypi.org/simple"
WINDOWS_X64 = "sys_platform == 'win32' and platform_machine == 'AMD64'"
_PIN = re.compile(r"^([A-Za-z0-9_.-]+)==(\S+) --hash=sha256:([0-9a-f]{64})$")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pyproject() -> dict:
    return tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))


def _lock() -> dict:
    return tomllib.loads((PROJECT / "uv.lock").read_text(encoding="utf-8"))


def _locked() -> dict:
    """The locked packages by normalised name, without the project itself."""
    return {_norm(p["name"]): p for p in _lock()["package"] if p["source"] != {"virtual": "."}}


def _requirements() -> dict:
    pins = {}
    for line in (REPO / "scripts" / "qwen3-requirements.txt").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            match = _PIN.match(line.strip())
            assert match, line
            pins[_norm(match[1])] = (match[2], match[3])
    return pins


def _wheel(entry: dict) -> tuple[str, str]:
    return unquote(entry["url"].rsplit("/", 1)[1]), entry["hash"].removeprefix("sha256:")


def test_the_project_is_the_registry_s_and_installs_nothing_of_its_own():
    assert registry.definition("qwen3").project == "scripts/tts/engines/qwen3"
    assert engine_env.project_dir(REPO, "qwen3") == PROJECT
    data = _pyproject()
    assert data["project"]["name"] == "act-qwen3-engine" and data["project"]["requires-python"] == "==3.12.*"
    uv = data["tool"]["uv"]
    assert uv["package"] is False and uv["no-build"] is True  # a virtual project; no source build, ever
    assert uv["environments"] == [WINDOWS_X64]
    lock = _lock()
    assert lock["requires-python"] == "==3.12.*"  # uv writes the same marker in its own canonical order
    assert lock["supported-markers"] == ["platform_machine == 'AMD64' and sys_platform == 'win32'"]
    virtual = [(p["name"], p["version"]) for p in lock["package"] if p["source"] == {"virtual": "."}]
    assert virtual == [("act-qwen3-engine", "0.0.0")]


def test_every_locked_version_is_exactly_the_reviewed_requirements_pin():
    pins, locked = _requirements(), _locked()
    assert len(pins) == len(locked) == 89
    assert {name: entry["version"] for name, entry in locked.items()} == {name: v for name, (v, _) in pins.items()}
    assert {c["name"]: c.get("specifier") for c in _lock()["manifest"]["constraints"] if "url" not in c} == {
        name: f"=={version}" for name, (version, _) in pins.items() if name != "sox"}


def test_every_reviewed_wheel_is_in_the_lock_by_its_exact_file_and_hash():
    manifest = qwen3_wheels.reviewed()
    locked = _locked()
    assert len(manifest.wheels) == 89
    for artifact in manifest.wheels:
        entry = locked[_norm(artifact.name)]
        assert entry["version"] == artifact.version, artifact.name
        assert (artifact.filename, artifact.sha256) in {_wheel(w) for w in entry["wheels"]}, artifact.name


def test_every_requirements_hash_is_the_installed_wheel_except_sox_s_source_archive():
    """The requirements file pins wheels by hash; for sox it pins the upstream source archive, from which ACT built
    the derivative wheel the lock (and the reviewed manifest) install. Nothing else is installed from a source."""
    manifest = {(_norm(a.name)): a for a in qwen3_wheels.reviewed().wheels}
    for name, (_, sha) in _requirements().items():
        if name == "sox":
            assert sha == qm.SOX_SOURCE_SHA256 != qwen3_wheels.reviewed().sox_wheel.sha256
            continue
        assert manifest[name].sha256 == sha, name


def test_torch_and_torchaudio_come_only_from_the_explicit_cuda_12_8_index():
    data = _pyproject()
    indexes = data["tool"]["uv"]["index"]
    assert indexes == [{"name": "pytorch-cu128", "url": CU128, "explicit": True}]
    assert data["tool"]["uv"]["sources"]["torch"] == {"index": "pytorch-cu128"}
    assert data["tool"]["uv"]["sources"]["torchaudio"] == {"index": "pytorch-cu128"}
    locked = _locked()
    for name in ("torch", "torchaudio"):
        assert locked[name]["version"] == "2.10.0+cu128" and locked[name]["source"] == {"registry": CU128}
        assert [_wheel(w)[0] for w in locked[name]["wheels"]] == [f"{name}-2.10.0+cu128-cp312-cp312-win_amd64.whl"]
    others = {n: e["source"] for n, e in locked.items() if n not in ("torch", "torchaudio", "sox")}
    assert set(map(str, others.values())) == {str({"registry": PYPI})}  # no other index, no fallback


def test_sox_is_act_s_commit_pinned_derivative_wheel():
    manifest = qwen3_wheels.reviewed()
    published = qm.published_sox_source(manifest)
    sox = _locked()["sox"]
    assert sox["source"] == {"url": published["url"]} and sox["version"] == "1.5.0"
    assert [_wheel(w) for w in sox["wheels"]] == [(manifest.sox_wheel.filename, manifest.sox_wheel.sha256)]
    assert manifest.sox_distribution.url == published["url"]
    assert manifest.sox_distribution.sha256 == manifest.sox_wheel.sha256
    assert "sdist" not in sox
    assert re.search(r"/[0-9a-f]{40}/", published["url"]), published["url"]  # one commit, never a branch
    assert _pyproject()["tool"]["uv"]["sources"]["sox"] == {"url": published["url"]}


def test_the_download_size_shown_before_an_install_is_every_reviewed_wheel():
    assert qwen3_wheels.total_bytes() == sum(a.size for a in qwen3_wheels.reviewed().wheels)
    assert 2_500_000_000 < qwen3_wheels.total_bytes() < 3_500_000_000


def test_the_lock_identity_a_receipt_binds_to_ignores_line_endings(tmp_path):
    for name in ("pyproject.toml", "uv.lock"):
        data = (PROJECT / name).read_bytes().replace(b"\r\n", b"\n")
        (tmp_path / name).write_bytes(data.replace(b"\n", b"\r\n"))
    assert uv_runner.lock_identity(REPO, project=tmp_path) == engine_env.lock_identity(REPO, "qwen3")
    assert engine_env.lock_identity(REPO, "qwen3")["uv"] == uv_runner.UV_VERSION


@pytest.mark.parametrize("profile_word", ["--no-dev", "--locked", "--no-cache", "--compile-bytecode"])
def test_the_production_sync_is_locked_cacheless_and_compiled(profile_word):
    command = engine_env.sync_command(REPO, "qwen3")
    assert profile_word in command
    assert "--link-mode" in command and command[command.index("--link-mode") + 1] == "copy"  # never a hardlink
    assert "--offline" not in command and "--upgrade" not in command and "--refresh" not in command
