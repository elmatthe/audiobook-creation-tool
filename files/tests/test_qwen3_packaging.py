"""v0.6.7 CP6 — what the release archives carry of the Qwen3 voices, and what they must never carry.

The application code, the pinned model manifest and the pinned requirements ship (they are tracked under ``scripts/``).
The isolated environment, the models, the install record, per-run job folders and any transcript do not: they are
created on the user's machine, only when the user asks, and the transcripts are not cleared for public redistribution
(owner ruling Q5). The release build itself is not changed beyond naming the environment folder in its exclusion set.
"""

from __future__ import annotations

import re

import pytest

from shared import release

from test_release_packaging import (  # noqa: F401
    OS_NAMES,
    REPO_ROOT,
    archives,
    build,
    commit_everything,
    fake_repo,
    git,
    names,
)

SHIPPED = (
    "scripts/Universal/tts/qwen3_runtime.py",
    "scripts/Universal/tts/qwen3_synth.py",
    "scripts/Universal/tts/qwen3_worker.py",
    "scripts/Universal/tts/qwen3_process.py",
    "scripts/Universal/tts/qwen3_setup.py",
    "scripts/Universal/tts/qwen3_install_ui.py",
    "scripts/Universal/tts/qwen3_models.json",
    "scripts/qwen3-requirements.txt",
)

NEVER = re.compile(r"(\.venv-qwen3|runtime-data|qwen3-tts[/\\]|\.safetensors|transcript|last-failure|ACT-VERIFIED"
                   r"|install\.lock|/cache/)", re.IGNORECASE)


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_the_qwen3_code_manifest_and_pins_ship_in_both_archives(archives, os_name):
    tracked = set(git(REPO_ROOT, "ls-files", "--", "scripts").splitlines())
    members = set(names(archives[os_name]))
    for path in SHIPPED:
        assert path in tracked, f"{path} must be committed to ship"
        assert path in members, path


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_no_archive_member_is_a_qwen3_environment_model_record_or_transcript(archives, os_name):
    offenders = [m for m in names(archives[os_name]) if NEVER.search(m)]
    assert offenders == []


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_a_committed_qwen3_environment_models_and_transcripts_still_ship_nothing(tmp_path, os_name):
    """Even force-committed, nothing outside ``scripts/`` (bar the six references) can ride along."""
    root = fake_repo(tmp_path / "repo")
    planted = [
        ".venv-qwen3/Scripts/python.exe",
        ".venv-qwen3/pyvenv.cfg",
        "files/runtime-data/models/qwen3-tts/CustomVoice-0c0e3051/model.safetensors",
        "files/runtime-data/models/qwen3-tts/CustomVoice-0c0e3051/ACT-VERIFIED.json",
        "files/runtime-data/qwen3/state.json",
        "files/runtime-data/qwen3/transcripts.json",
        "files/runtime-data/qwen3/jobs/20261019-120000-1-abc/job.json",
        "files/runtime-data/qwen3/last-failure.txt",
        "files/runtime-data/qwen3/cache/pip/wheel.whl",
    ]
    for rel in planted:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"planted")
    git(root, "add", "-A", "-f")
    git(root, "commit", "-q", "-m", "plant the qwen3 artefacts")
    for os_name_ in (os_name,):
        members = names(build(root, tmp_path / "dist", os_name_))
        assert [m for m in members if NEVER.search(m)] == []


def test_the_packager_names_the_qwen3_environment_folder_among_its_exclusions():
    assert ".venv-qwen3" in release.EXCLUDED_DIR_NAMES and ".venv" in release.EXCLUDED_DIR_NAMES
    assert release._is_excluded(release.Path(".venv-qwen3/Scripts/python.exe"))
    assert release._is_excluded(release.Path("scripts/.venv-qwen3/pyvenv.cfg"))


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_the_shipped_requirements_and_manifest_are_the_committed_bytes(archives, os_name):
    import zipfile

    with zipfile.ZipFile(archives[os_name]) as zf:
        for path in ("scripts/qwen3-requirements.txt", "scripts/Universal/tts/qwen3_models.json"):
            assert zf.read(path) == (REPO_ROOT / path).read_bytes(), path


def test_the_environment_folder_is_gitignored_so_it_cannot_be_staged_by_accident():
    import subprocess

    for path in (".venv-qwen3/Scripts/python.exe", "files/runtime-data/models/qwen3-tts/x/model.safetensors",
                 "files/runtime-data/qwen3/transcripts.json"):
        result = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT)
        assert result.returncode == 0, path


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_the_voice_previews_never_ship_even_when_committed(archives, tmp_path, os_name):
    """Previews are repository documentation (owner ruling Q8): checked on the real archive and on a planted one."""
    def offenders(members):
        return [m for m in members if "voice-previews" in m or m.endswith("previews.json")]

    assert offenders(names(archives[os_name])) == []
    root = fake_repo(tmp_path / "repo")
    for rel in ("files/voice-previews/af_heart.wav", "files/voice-previews/previews.json",
                "files/voice-previews/README.md"):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"planted")
    git(root, "add", "-A", "-f")
    git(root, "commit", "-q", "-m", "plant the previews")
    assert offenders(names(build(root, tmp_path / "dist", os_name))) == []
