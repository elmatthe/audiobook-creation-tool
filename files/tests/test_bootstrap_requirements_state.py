"""v0.6.1 Plan 4 Phase 12 remediation — the requirements-drift upgrade path.

**The defect this file pins down.** ``Setup_and_Run-audiobook-creation-tool.bat``
treats the mere existence of ``.venv\\Scripts\\pythonw.exe`` as proof that setup is
current, and hands off to ``bootstrap.py --launch-only``. That path health-checked
**Kokoro only**. So an environment built before a dependency was pinned stayed
"valid" forever: the Phase 12 manual matrix found a perfectly working ``.venv``
that silently had no ``chatterbox-tts`` and no ``pillow-heif``, leaving the local
voices and HEIC support unavailable with nothing anywhere saying why. Only
deleting the whole environment by hand fixed it.

**The contract.** An environment is bound to the exact ``scripts/requirements.txt``
it was last successfully reconciled against, by content hash. Launch compares the
two:

* stamp matches  -> fast path, no pip, no cost;
* stamp missing  -> an older environment, reconcile **once**;
* stamp differs  -> pins changed, reconcile;
* reconcile fails -> no stamp is written, the truth is reported, and the app still
  opens so Edge TTS keeps working.

The stamp lives **inside the venv**, which is deliberate: it is disposable local
state, it is never tracked, and it travels with the environment when a directory is
renamed — so swapping an old venv back in is correctly detected as stale.

Nothing here installs anything, downloads weights or touches a real environment.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared import bootstrap  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def fake_env(monkeypatch, tmp_path):
    """A disposable venv + requirements file, fully detached from the real ones."""
    venv = tmp_path / ".venv"
    (venv / "Scripts").mkdir(parents=True)
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("pillow==12.2.0\nedge-tts==7.2.8\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "VENV_DIR", venv)
    monkeypatch.setattr(bootstrap, "REQUIREMENTS_FILE", reqs)
    return SimpleNamespace(venv=venv, reqs=reqs, tmp=tmp_path)


class _Log:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def line(self, text: str) -> None:
        self.lines.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


# --------------------------------------------------------------------------- #
# A. The fingerprint itself
# --------------------------------------------------------------------------- #
def test_the_fingerprint_is_deterministic(fake_env):
    assert bootstrap.requirements_fingerprint() == bootstrap.requirements_fingerprint()


def test_the_fingerprint_changes_when_a_pin_changes(fake_env):
    before = bootstrap.requirements_fingerprint()
    fake_env.reqs.write_text("pillow==12.2.0\nedge-tts==7.2.9\n", encoding="utf-8")
    assert bootstrap.requirements_fingerprint() != before


def test_the_fingerprint_changes_when_a_package_is_added(fake_env):
    before = bootstrap.requirements_fingerprint()
    fake_env.reqs.write_text(
        "pillow==12.2.0\nedge-tts==7.2.8\npillow-heif==1.5.0\n", encoding="utf-8")
    assert bootstrap.requirements_fingerprint() != before


def test_a_missing_requirements_file_does_not_raise(fake_env):
    fake_env.reqs.unlink()
    assert bootstrap.requirements_fingerprint() == ""


# --------------------------------------------------------------------------- #
# B. Where the stamp lives
# --------------------------------------------------------------------------- #
def test_the_stamp_lives_inside_the_disposable_environment(fake_env):
    assert bootstrap.requirements_state_path().is_relative_to(fake_env.venv)


def test_the_stamp_is_not_a_tracked_repository_file():
    """The real path must sit under the gitignored .venv, never in the tree."""
    assert bootstrap.requirements_state_path().is_relative_to(bootstrap.VENV_DIR)
    tracked = REPO_ROOT / ".gitignore"
    assert ".venv/" in tracked.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# C. Deciding whether to reconcile
# --------------------------------------------------------------------------- #
def test_an_environment_with_no_stamp_needs_reconciling(fake_env):
    """C. First launch after an older version — reconcile once, not forever."""
    assert bootstrap.requirements_are_current() is False


def test_a_matching_stamp_is_current(fake_env):
    bootstrap.record_requirements_state()
    assert bootstrap.requirements_are_current() is True


def test_a_stamp_from_different_requirements_is_stale(fake_env):
    bootstrap.record_requirements_state()
    fake_env.reqs.write_text(
        "pillow==12.2.0\nedge-tts==7.2.8\nchatterbox-tts==0.1.7\n", encoding="utf-8")
    assert bootstrap.requirements_are_current() is False


def test_a_corrupt_stamp_is_treated_as_stale_rather_than_crashing(fake_env):
    bootstrap.requirements_state_path().write_text("not json{", encoding="utf-8")
    assert bootstrap.requirements_are_current() is False


def test_a_stamp_without_the_expected_key_is_treated_as_stale(fake_env):
    bootstrap.requirements_state_path().write_text(
        json.dumps({"something_else": 1}), encoding="utf-8")
    assert bootstrap.requirements_are_current() is False


def test_the_stamp_records_the_fingerprint_it_was_written_for(fake_env):
    bootstrap.record_requirements_state()
    payload = json.loads(bootstrap.requirements_state_path().read_text(encoding="utf-8"))
    assert payload["requirements_sha256"] == bootstrap.requirements_fingerprint()


# --------------------------------------------------------------------------- #
# D. Reconciliation behaviour
# --------------------------------------------------------------------------- #
@pytest.fixture
def install_spy(monkeypatch):
    calls = {"pip": 0, "validate": 0, "pip_ok": True, "validate_ok": True}

    def fake_pip(log):
        calls["pip"] += 1
        return calls["pip_ok"]

    def fake_validate(log):
        calls["validate"] += 1
        return calls["validate_ok"]

    monkeypatch.setattr(bootstrap, "pip_install_requirements", fake_pip)
    monkeypatch.setattr(bootstrap, "validate_installed_packages", fake_validate)
    return calls


def test_a_current_environment_runs_no_pip_at_all(fake_env, install_spy):
    """A. Current environment — fast launch stays fast."""
    bootstrap.record_requirements_state()
    ok, _msg = bootstrap.ensure_requirements_current(_Log())
    assert ok is True
    assert install_spy["pip"] == 0


def test_a_stale_environment_reconciles_exactly_once(fake_env, install_spy):
    """B. Requirements changed — one truthful reconciliation."""
    ok, _msg = bootstrap.ensure_requirements_current(_Log())
    assert ok is True
    assert install_spy["pip"] == 1
    assert install_spy["validate"] == 1


def test_reconciliation_installs_from_the_requirements_file(fake_env, monkeypatch):
    seen: list[Path] = []

    def fake_pip(log):
        seen.append(bootstrap.REQUIREMENTS_FILE)
        return True

    monkeypatch.setattr(bootstrap, "pip_install_requirements", fake_pip)
    monkeypatch.setattr(bootstrap, "validate_installed_packages", lambda log: True)
    bootstrap.ensure_requirements_current(_Log())
    assert seen == [fake_env.reqs]


def test_after_a_successful_repair_the_next_launch_is_fast(fake_env, install_spy):
    """D. Successful repair -> future launches return to the fast path."""
    bootstrap.ensure_requirements_current(_Log())
    assert install_spy["pip"] == 1
    bootstrap.ensure_requirements_current(_Log())
    assert install_spy["pip"] == 1, "a reconciled environment must not reinstall"


def test_a_failed_pip_writes_no_stamp_and_reports_truthfully(fake_env, install_spy):
    """E. Failed repair — never claim the environment is current."""
    install_spy["pip_ok"] = False
    ok, msg = bootstrap.ensure_requirements_current(_Log())
    assert ok is False
    assert not bootstrap.requirements_state_path().exists()
    assert msg


def test_a_failed_validation_writes_no_stamp(fake_env, install_spy):
    install_spy["validate_ok"] = False
    ok, _msg = bootstrap.ensure_requirements_current(_Log())
    assert ok is False
    assert not bootstrap.requirements_state_path().exists()


def test_a_failed_repair_is_retried_on_the_next_launch(fake_env, install_spy):
    install_spy["pip_ok"] = False
    bootstrap.ensure_requirements_current(_Log())
    bootstrap.ensure_requirements_current(_Log())
    assert install_spy["pip"] == 2, "a failure must not be remembered as success"


def test_reconciliation_never_downloads_the_chatterbox_model(fake_env, monkeypatch):
    """F. Package repair and the ~3.9 GiB model download stay separate."""
    downloads: list[str] = []
    monkeypatch.setattr(bootstrap, "predownload_chatterbox",
                        lambda log: downloads.append("chatterbox"))
    monkeypatch.setattr(bootstrap, "predownload_kokoro",
                        lambda log: downloads.append("kokoro"))
    monkeypatch.setattr(bootstrap, "pip_install_requirements", lambda log: True)
    monkeypatch.setattr(bootstrap, "validate_installed_packages", lambda log: True)
    bootstrap.ensure_requirements_current(_Log())
    assert downloads == []


def test_reconciliation_never_deletes_or_recreates_the_environment(
        fake_env, install_spy):
    """A changed pin must never cost the user their whole environment."""
    marker = fake_env.venv / "Scripts" / "sentinel.txt"
    marker.write_text("keep me", encoding="utf-8")
    bootstrap.ensure_requirements_current(_Log())
    assert marker.read_text(encoding="utf-8") == "keep me"


def test_a_missing_requirements_file_is_not_treated_as_drift(fake_env, install_spy):
    """No requirements file means nothing to reconcile — never loop on pip."""
    fake_env.reqs.unlink()
    ok, _msg = bootstrap.ensure_requirements_current(_Log())
    assert ok is True
    assert install_spy["pip"] == 0


# --------------------------------------------------------------------------- #
# E. Wiring — the launch path actually consults it
# --------------------------------------------------------------------------- #
def test_the_launch_path_reconciles_requirements_before_launching():
    import ast

    src = Path(bootstrap.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "_launch_with_kokoro_healthcheck")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "ensure_requirements_current" in called
    assert "launch_gui" in called


def test_setup_records_the_stamp_only_after_packages_validate():
    import ast

    src = Path(bootstrap.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "run_setup")
    body = ast.get_source_segment(src, fn)
    assert "record_requirements_state()" in body
    assert body.index("validate_installed_packages") < body.index(
        "record_requirements_state()")


def test_kokoro_self_heal_is_still_wired_into_launch():
    """G. Existing Kokoro behaviour remains intact."""
    import ast

    src = Path(bootstrap.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "_launch_with_kokoro_healthcheck")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "kokoro_is_healthy" in called
    assert "ensure_kokoro_installed" in str(ast.dump(fn))


def test_the_batch_launcher_does_not_hard_code_a_requirements_hash():
    """Dependency truth stays in requirements.txt/bootstrap, not the .bat."""
    bat = (REPO_ROOT / "Setup_and_Run-audiobook-creation-tool.bat").read_text(
        encoding="utf-8", errors="replace")
    assert "sha256" not in bat.lower()
    assert "requirements" not in bat.lower() or "pip" not in bat.lower()


# --------------------------------------------------------------------------- #
# F. The concrete Phase 12 scenario
# --------------------------------------------------------------------------- #
def test_a_pre_pillow_heif_environment_is_detected_as_stale(fake_env, install_spy):
    """H. The exact upgrade the maintainer hit: a new pin appears."""
    bootstrap.record_requirements_state()
    assert bootstrap.requirements_are_current() is True
    fake_env.reqs.write_text(
        "pillow==12.2.0\nedge-tts==7.2.8\npillow-heif==1.5.0\n"
        "chatterbox-tts==0.1.7\n", encoding="utf-8")
    assert bootstrap.requirements_are_current() is False
    ok, _msg = bootstrap.ensure_requirements_current(_Log())
    assert ok is True and install_spy["pip"] == 1
    assert bootstrap.requirements_are_current() is True
