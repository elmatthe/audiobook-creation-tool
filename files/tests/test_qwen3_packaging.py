"""v0.6.7 CP6 — what the release archives carry of the Qwen3 voices, and what they must never carry.

The application code, the pinned model manifest and the pinned requirements ship (they are tracked under ``scripts/``).
The isolated environment, the models, the install record, per-run job folders and any local transcript do not: they are
created on the user's machine, only when the user asks. The one exception is the curated, owner-approved clone transcript
bundle (owner ruling Q8, v0.7.0 P03C). The release build itself is not changed beyond naming the environment folder in its
exclusion set.
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
    "scripts/tts/qwen3_runtime.py",
    "scripts/tts/qwen3_synth.py",
    "scripts/tts/qwen3_worker.py",
    "scripts/tts/qwen3_process.py",
    "scripts/tts/qwen3_setup.py",
    "scripts/tts/qwen3_install_ui.py",
    "scripts/tts/qwen3_models.json",
    "scripts/qwen3-requirements.txt",
)

_NEVER = re.compile(r"(\.venv-qwen3|runtime-data|qwen3-tts[/\\]|\.safetensors|transcript|last-failure|ACT-VERIFIED"
                    r"|install\.lock|/cache/)", re.IGNORECASE)
#: The one transcript file that ships (owner ruling Q8, v0.7.0 P03C): the curated, owner-approved bundle. This narrow
#: exception replaces the v0.6.7 blanket ban on any member naming a transcript; every other one is still refused.
BUNDLE = "scripts/tts/data/bundled_clone_transcripts.json"


class _Never:
    @staticmethod
    def search(member: str):
        return None if member == BUNDLE else _NEVER.search(member)


NEVER = _Never()


def test_the_bundle_exception_is_exactly_one_path():
    assert NEVER.search(BUNDLE) is None
    for near_miss in ("scripts/tts/data/bundled_clone_transcripts.json.bak", "scripts/tts/bundled_clone_transcripts.json",
                      "scripts/tts/data/transcripts.json", "Scripts/tts/data/bundled_clone_transcripts.json",
                      "scripts/tts/data/bundled_clone_transcripts.JSON", "files/runtime-data/qwen3/transcripts.json"):
        assert NEVER.search(near_miss), near_miss


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_the_shipped_bundle_is_in_both_archives_once_with_its_committed_bytes(archives, os_name):
    import zipfile

    with zipfile.ZipFile(archives[os_name]) as zf:
        members = zf.namelist()
        assert members.count(BUNDLE) == 1
        assert zf.read(BUNDLE) == (REPO_ROOT / BUNDLE).read_bytes()
    assert [m for m in members if "transcript" in m.lower()] == [BUNDLE]


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
        for path in ("scripts/qwen3-requirements.txt", "scripts/tts/qwen3_models.json"):
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


# --------------------------------------------------------------------------- #
# v0.7.0 P04C Stage 3 — the canonical engine inside .venv, its set-aside and preserved copies never ship
# --------------------------------------------------------------------------- #
PRESERVED_TAG = "20261021-184021-592ae0be"
#: Environments and private state at the repository root, as a real checkout can hold them.
ROOT_PLANTS = (
    ".venv/pyvenv.cfg",
    ".venv/engines/qwen3/pyvenv.cfg",
    ".venv/engines/qwen3/Scripts/python.exe",
    ".venv/engines/qwen3/Lib/site-packages/qwen_tts/__init__.py",
    ".venv.replaced/engines/qwen3/pyvenv.cfg",
    ".venv.replaced-1729800000/engines/qwen3/Lib/site-packages/torch/__init__.py",
    ".venv.discarded/engines/qwen3/Scripts/python.exe",
    ".venv-qwen3/Lib/site-packages/torch/__init__.py",
    f".venv.act67-preserved-{PRESERVED_TAG}/Lib/site-packages/app.py",
    f".venv-qwen3.act67-preserved-{PRESERVED_TAG}/pyvenv.cfg",
    f"files/runtime-data.act67-preserved-{PRESERVED_TAG}/qwen3/transcripts.json",
    "files/runtime-data/models/qwen3-tts/CustomVoice-0c0e3051/model.safetensors",
    "files/runtime-data/models/kokoro/hub/model.bin",
    "files/runtime-data/qwen3/state.json",
    "files/runtime-data/qwen3/transcript-selection.json",
    "files/runtime-data/qwen3/setup.lock",
    "files/runtime-data/qwen3/engine.lock",
)
#: The same kinds of folder force-committed INSIDE ``scripts/`` -- the one tree the packager walks -- where only the
#: name rules can stop them.
SCRIPTS_PLANTS = (
    "scripts/.venv/engines/qwen3/Lib/site-packages/qwen_tts/__init__.py",
    "scripts/tts/.venv/engines/qwen3/pyvenv.cfg",
    "scripts/.venv.replaced/engines/qwen3/Lib/site-packages/torch/__init__.py",
    "scripts/.venv.replaced-1729800000/engines/qwen3/pyvenv.cfg",
    "scripts/.venv.discarded/engines/qwen3/Scripts/python.exe",
    "scripts/.venv-qwen3/Lib/site-packages/torch/__init__.py",
    f"scripts/.venv.act67-preserved-{PRESERVED_TAG}/Lib/app.py",
    f"scripts/.venv-qwen3.act67-preserved-{PRESERVED_TAG}/pyvenv.cfg",
)
_ENVIRONMENT_MEMBER = re.compile(r"(^|/)\.venv([.-][^/]*)?/|engines/qwen3|pyvenv\.cfg|act67-preserved|runtime-data",
                                 re.IGNORECASE)


def _force_committed(root, paths):
    for rel in paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"planted")
    git(root, "add", "-A", "-f")
    git(root, "commit", "-q", "-m", "force-commit environments and private state")
    tracked = set(git(root, "ls-files").splitlines())
    assert set(paths) <= tracked, set(paths) - tracked  # really tracked: only the packager's own rules can stop them


@pytest.mark.parametrize("os_name", OS_NAMES)
def test_a_force_committed_nested_engine_its_set_aside_and_preserved_copies_never_become_members(tmp_path, os_name):
    from test_release_packaging import REFERENCE_MEMBERS

    root = fake_repo(tmp_path / "repo")
    _force_committed(root, ROOT_PLANTS + SCRIPTS_PLANTS)
    members = names(build(root, tmp_path / "dist", os_name))

    assert [m for m in members if _ENVIRONMENT_MEMBER.search(m)] == []
    assert not set(members) & set(ROOT_PLANTS + SCRIPTS_PLANTS)
    assert sorted(m for m in members if m.startswith("files/")) == sorted(REFERENCE_MEMBERS)
    assert "scripts/launcher.py" in members  # and the application itself still ships


@pytest.mark.parametrize("rel", ROOT_PLANTS[:10] + SCRIPTS_PLANTS)
def test_every_environment_folder_name_is_excluded_wherever_it_appears(rel):
    assert release._is_excluded(release.Path(rel)), rel


@pytest.mark.parametrize("rel", ["scripts/shared/venv_layout.py", "scripts/tts/engines.py", "scripts/engines/qwen3.py",
                                 "scripts/tts/qwen3_runtime.py", "scripts/qwen3-requirements.txt",
                                 "scripts/shared/.venv-notes.txt"])
def test_the_environment_rules_do_not_drop_application_files(rel):
    assert not release._is_excluded(release.Path(rel)), rel


def test_the_repair_s_set_aside_environments_are_gitignored_like_the_rest():
    import subprocess

    for path in (".venv/engines/qwen3/Scripts/python.exe", ".venv.replaced/engines/qwen3/pyvenv.cfg",
                 ".venv.replaced-1729800000/engines/qwen3/pyvenv.cfg", ".venv.discarded/engines/qwen3/x.py",
                 ".venv.discarded-2/x.py", ".venv-qwen3/pyvenv.cfg",
                 f".venv.act67-preserved-{PRESERVED_TAG}/pyvenv.cfg"):
        result = subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=REPO_ROOT)
        assert result.returncode == 0, path
    for path in ("scripts/shared/venv_layout.py", "scripts/.venv.replaced.py"):
        result = subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=REPO_ROOT)
        assert result.returncode == 1, path
