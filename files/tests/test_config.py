"""The configuration core: parsing, per-key validation, precedence, diagnostics.

Every test drives ``shared.config.load()`` with injected paths, so nothing here
reads or writes the maintainer's real ``config.toml``, ``settings.json``,
Downloads folder, logs, outputs, virtual environment or model cache. The one
test that touches the committed file only reads it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from shared import config, logging_setup
from shared.version import VERSION

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def write_config(directory: Path, body: str) -> Path:
    path = directory / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def fake_repo(tmp_path: Path) -> Path:
    """A minimal repository root containing only the real entry-point file."""
    root = tmp_path / "repo"
    entry = root / "scripts" / "Universal" / "launcher.py"
    entry.parent.mkdir(parents=True)
    entry.write_text("# stand-in for the launcher\n", encoding="utf-8")
    return root


VALID_BODY = """
[project]
name = "Audiobook Creation Tool"
version = "{version}"
python_min = "3.11"
entry_point = "scripts/Universal/launcher.py"
platforms = ["Windows", "MacOS"]

[output]
base_directory = ""

[logging]
max_sessions = 30

[importing]
large_result_warning_threshold = 1000
"""


def load_body(tmp_path: Path, body: str, **kwargs):
    root = fake_repo(tmp_path)
    path = write_config(root, body)
    kwargs.setdefault("settings_data", {})
    kwargs.setdefault("home", tmp_path / "home")
    return config.load(config_path=path, repo_root=root, **kwargs)


def keys_with_diagnostics(effective) -> set[str]:
    return {d.key for d in effective.diagnostics}


# --------------------------------------------------------------------------- #
# The committed file
# --------------------------------------------------------------------------- #


def test_the_committed_root_config_is_valid_with_no_diagnostics():
    effective = config.load(
        config_path=REPO_ROOT / "config.toml",
        settings_data={},
        repo_root=REPO_ROOT,
    )
    assert effective.diagnostics == ()
    assert effective.project.name == "Audiobook Creation Tool"
    assert effective.project.version == VERSION
    assert effective.project.python_min == "3.11"
    assert effective.project.entry_point == "scripts/Universal/launcher.py"
    assert effective.project.platforms == ("Windows", "MacOS")
    assert effective.logging.max_sessions == 30
    assert effective.importing.large_result_warning_threshold == 1000
    assert effective.output.is_default is True


def test_the_committed_config_keeps_its_explanatory_comments():
    text = (REPO_ROOT / "config.toml").read_text(encoding="utf-8")
    assert text.count("#") > 20, "the committed file must stay documented for hand-editing"
    for key in ("base_directory", "max_sessions", "large_result_warning_threshold"):
        assert key in text


def test_the_committed_config_is_machine_agnostic():
    """No absolute path, drive letter or user name may be committed."""
    text = (REPO_ROOT / "config.toml").read_text(encoding="utf-8")
    values = [
        line.split("=", 1)[1].strip()
        for line in text.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    ]
    for value in values:
        assert "C:\\" not in value and "C:/" not in value
        assert "/Users/" not in value and "\\Users\\" not in value


# --------------------------------------------------------------------------- #
# File-level fallback
# --------------------------------------------------------------------------- #


def test_a_missing_config_falls_back_to_every_default_and_says_so(tmp_path):
    root = fake_repo(tmp_path)
    effective = config.load(
        config_path=root / "config.toml",
        settings_data={},
        repo_root=root,
        home=tmp_path / "home",
    )
    assert effective.project.name == config.DEFAULT_PROJECT_NAME
    assert effective.logging.max_sessions == config.DEFAULT_MAX_SESSIONS
    assert len(effective.diagnostics) == 1
    assert "not found" in effective.diagnostics[0].message
    assert effective.source_of("logging.max_sessions") == config.SOURCE_DEFAULT


def test_malformed_toml_falls_back_without_raising(tmp_path):
    effective = load_body(tmp_path, "[project\nname = broken")
    assert effective.project.name == config.DEFAULT_PROJECT_NAME
    assert effective.logging.max_sessions == config.DEFAULT_MAX_SESSIONS
    assert any("TOML" in d.message for d in effective.diagnostics)


def test_a_malformed_config_never_exposes_a_traceback_in_the_summary(tmp_path):
    effective = load_body(tmp_path, "[project\nname = broken")
    summary = effective.warning_summary()
    assert "Traceback" not in summary
    assert "TOMLDecodeError" not in summary
    # ...but the technical detail is kept for the log.
    assert any("TOMLDecodeError" in line for line in effective.technical_details())


def test_a_section_that_is_not_a_table_is_reported_not_crashed(tmp_path):
    effective = load_body(tmp_path, 'project = "not a table"\n')
    assert effective.project.name == config.DEFAULT_PROJECT_NAME
    assert "project" in keys_with_diagnostics(effective)


# --------------------------------------------------------------------------- #
# Per-key validation and partial fallback
# --------------------------------------------------------------------------- #


def test_one_bad_key_never_discards_its_valid_neighbours(tmp_path):
    body = VALID_BODY.format(version=VERSION).replace(
        "max_sessions = 30", "max_sessions = 99999"
    )
    effective = load_body(tmp_path, body)
    assert effective.logging.max_sessions == config.DEFAULT_MAX_SESSIONS
    assert keys_with_diagnostics(effective) == {"logging.max_sessions"}
    # Everything else still came from the file.
    assert effective.source_of("project.name") == config.SOURCE_TOML
    assert effective.source_of("importing.large_result_warning_threshold") == config.SOURCE_TOML
    assert effective.importing.large_result_warning_threshold == 1000


def test_a_blank_project_name_falls_back(tmp_path):
    body = VALID_BODY.format(version=VERSION).replace('name = "Audiobook Creation Tool"',
                                                      'name = "   "')
    effective = load_body(tmp_path, body)
    assert effective.project.name == config.DEFAULT_PROJECT_NAME
    assert "project.name" in keys_with_diagnostics(effective)


def test_project_version_drift_uses_the_code_version_and_warns(tmp_path):
    body = VALID_BODY.format(version="9.9.9")
    effective = load_body(tmp_path, body)
    assert effective.project.version == VERSION
    assert "project.version" in keys_with_diagnostics(effective)
    assert "9.9.9" in effective.warning_summary()


@pytest.mark.parametrize("bad", ['"3"', '"three.eleven"', '"3.11.2.1"', "3.11", "true"])
def test_an_invalid_python_min_falls_back(tmp_path, bad):
    body = VALID_BODY.format(version=VERSION).replace('python_min = "3.11"',
                                                      f"python_min = {bad}")
    effective = load_body(tmp_path, body)
    assert effective.project.python_min == config.DEFAULT_PYTHON_MIN
    assert "project.python_min" in keys_with_diagnostics(effective)


@pytest.mark.parametrize(
    "bad",
    [
        '"scripts/Universal/does_not_exist.py"',   # not a file
        '"../outside/launcher.py"',                # escapes the repository
        '"/etc/passwd"',                           # absolute
        '""',                                      # blank
        "42",                                      # wrong type
    ],
)
def test_an_invalid_entry_point_falls_back(tmp_path, bad):
    body = VALID_BODY.format(version=VERSION).replace(
        'entry_point = "scripts/Universal/launcher.py"', f"entry_point = {bad}"
    )
    effective = load_body(tmp_path, body)
    assert effective.project.entry_point == config.DEFAULT_ENTRY_POINT
    assert "project.entry_point" in keys_with_diagnostics(effective)


def test_a_valid_entry_point_must_resolve_inside_the_given_repository(tmp_path):
    effective = load_body(tmp_path, VALID_BODY.format(version=VERSION))
    assert effective.source_of("project.entry_point") == config.SOURCE_TOML
    assert "project.entry_point" not in keys_with_diagnostics(effective)


def test_unknown_platform_values_are_dropped_and_known_ones_kept(tmp_path):
    body = VALID_BODY.format(version=VERSION).replace(
        'platforms = ["Windows", "MacOS"]', 'platforms = ["Windows", "Amiga"]'
    )
    effective = load_body(tmp_path, body)
    assert effective.project.platforms == ("Windows",)
    assert "project.platforms" in keys_with_diagnostics(effective)


def test_platform_names_are_matched_case_insensitively_then_normalised(tmp_path):
    body = VALID_BODY.format(version=VERSION).replace(
        'platforms = ["Windows", "MacOS"]', 'platforms = ["windows", "macOS"]'
    )
    effective = load_body(tmp_path, body)
    assert effective.project.platforms == ("Windows", "MacOS")
    assert effective.diagnostics == ()


def test_platforms_falling_to_nothing_known_uses_the_default(tmp_path):
    body = VALID_BODY.format(version=VERSION).replace(
        'platforms = ["Windows", "MacOS"]', 'platforms = ["Amiga"]'
    )
    effective = load_body(tmp_path, body)
    assert effective.project.platforms == config.DEFAULT_PLATFORMS


@pytest.mark.parametrize("bad", ['"30"', "30.5", "true", "0", "1001", "-5"])
def test_an_invalid_max_sessions_falls_back_to_thirty(tmp_path, bad):
    body = VALID_BODY.format(version=VERSION).replace("max_sessions = 30",
                                                      f"max_sessions = {bad}")
    effective = load_body(tmp_path, body)
    assert effective.logging.max_sessions == 30
    assert "logging.max_sessions" in keys_with_diagnostics(effective)


@pytest.mark.parametrize("good", ["1", "1000", "250"])
def test_max_sessions_accepts_its_documented_range(tmp_path, good):
    body = VALID_BODY.format(version=VERSION).replace("max_sessions = 30",
                                                      f"max_sessions = {good}")
    effective = load_body(tmp_path, body)
    assert effective.logging.max_sessions == int(good)
    assert effective.diagnostics == ()


def test_the_large_result_threshold_is_validated_now(tmp_path):
    body = VALID_BODY.format(version=VERSION).replace(
        "large_result_warning_threshold = 1000", "large_result_warning_threshold = 0"
    )
    effective = load_body(tmp_path, body)
    assert effective.importing.large_result_warning_threshold == 1000
    assert "importing.large_result_warning_threshold" in keys_with_diagnostics(effective)


def test_the_large_result_threshold_is_only_validated_not_consumed():
    """Plan 3 owns the behaviour. Phase 1 must not have implemented scanning."""
    text = (REPO_ROOT / "scripts" / "Universal" / "shared" / "config.py").read_text(
        encoding="utf-8"
    )
    for plan3_word in ("def scan", "rglob", "Cancel Import", "recursive_scan"):
        assert plan3_word not in text


# --------------------------------------------------------------------------- #
# Unknown keys and sections
# --------------------------------------------------------------------------- #


def test_unknown_sections_and_keys_are_ignored_and_reported_once(tmp_path):
    body = VALID_BODY.format(version=VERSION).replace(
        "max_sessions = 30", "max_sessions = 30\nmax_sesions = 12"
    ) + """
[telemetry]
enabled = true
"""
    effective = load_body(tmp_path, body)
    assert effective.logging.max_sessions == 30
    file_level = [d for d in effective.diagnostics if d.key == ""]
    assert len(file_level) == 1, "unknown entries must aggregate into ONE diagnostic"
    assert "telemetry" in file_level[0].detail
    assert "logging.max_sesions" in file_level[0].detail


def test_an_unknown_key_does_not_invalidate_the_known_ones(tmp_path):
    body = VALID_BODY.format(version=VERSION).replace(
        "[output]", "[output]\nbase_dir = \"typo\""
    )
    effective = load_body(tmp_path, body)
    assert effective.output.is_default is True
    assert effective.project.name == "Audiobook Creation Tool"


# --------------------------------------------------------------------------- #
# Output base
# --------------------------------------------------------------------------- #


def test_an_empty_output_base_means_the_downloads_default(tmp_path):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    effective = load_body(tmp_path, VALID_BODY.format(version=VERSION), home=home)
    assert effective.output.is_default is True
    assert effective.output.base_directory == (
        home / "Downloads" / config.OUTPUT_BASE_FOLDER_NAME
    )


def test_the_default_output_base_is_computed_never_created(tmp_path):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    effective = load_body(tmp_path, VALID_BODY.format(version=VERSION), home=home)
    assert not effective.output.base_directory.exists()


def test_an_absolute_output_base_is_accepted(tmp_path):
    custom = tmp_path / "elsewhere" / "Outputs"
    body = VALID_BODY.format(version=VERSION).replace(
        'base_directory = ""', f'base_directory = "{custom.as_posix()}"'
    )
    effective = load_body(tmp_path, body)
    assert effective.output.is_default is False
    assert effective.output.base_directory == custom
    assert effective.diagnostics == ()


def test_a_tilde_output_base_is_expanded(tmp_path):
    body = VALID_BODY.format(version=VERSION).replace(
        'base_directory = ""', 'base_directory = "~/Media/Audiobooks"'
    )
    effective = load_body(tmp_path, body)
    assert effective.output.is_default is False
    assert not str(effective.output.base_directory).startswith("~")
    assert effective.output.base_directory.is_absolute()
    assert effective.output.base_directory.parts[-2:] == ("Media", "Audiobooks")


@pytest.mark.parametrize("relative", ["Outputs", "./Outputs", "some/nested/dir"])
def test_a_relative_output_base_is_rejected_not_resolved_against_the_cwd(tmp_path, relative):
    body = VALID_BODY.format(version=VERSION).replace(
        'base_directory = ""', f'base_directory = "{relative}"'
    )
    effective = load_body(tmp_path, body)
    assert effective.output.is_default is True
    assert "output.base_directory" in keys_with_diagnostics(effective)
    assert "relative" in effective.warning_summary()


@pytest.mark.parametrize("raw", ["%USERPROFILE%/Outputs", "$HOME/Outputs", "${HOME}/Outputs"])
def test_environment_variables_are_never_expanded_in_an_output_base(tmp_path, raw):
    body = VALID_BODY.format(version=VERSION).replace(
        'base_directory = ""', f'base_directory = "{raw}"'
    )
    effective = load_body(tmp_path, body)
    # They stay literal, are therefore relative, and are therefore rejected.
    assert effective.output.is_default is True
    assert "output.base_directory" in keys_with_diagnostics(effective)


def test_a_non_string_output_base_falls_back(tmp_path):
    body = VALID_BODY.format(version=VERSION).replace('base_directory = ""',
                                                      "base_directory = 7")
    effective = load_body(tmp_path, body)
    assert effective.output.is_default is True
    assert "output.base_directory" in keys_with_diagnostics(effective)


# --------------------------------------------------------------------------- #
# Precedence and the mutable overlay
# --------------------------------------------------------------------------- #


def test_the_allowlisted_setting_overrides_the_toml_value(tmp_path):
    from_toml = tmp_path / "from-toml"
    from_settings = tmp_path / "from-settings"
    body = VALID_BODY.format(version=VERSION).replace(
        'base_directory = ""', f'base_directory = "{from_toml.as_posix()}"'
    )
    effective = load_body(
        tmp_path, body, settings_data={"output_base_directory": str(from_settings)}
    )
    assert effective.output.base_directory == from_settings
    assert effective.source_of("output.base_directory") == config.SOURCE_SETTINGS


def test_toml_overrides_the_code_default(tmp_path):
    body = VALID_BODY.format(version=VERSION).replace("max_sessions = 30",
                                                      "max_sessions = 7")
    effective = load_body(tmp_path, body)
    assert effective.logging.max_sessions == 7
    assert effective.source_of("logging.max_sessions") == config.SOURCE_TOML


def test_an_invalid_settings_override_falls_back_to_the_toml_value(tmp_path):
    from_toml = tmp_path / "from-toml"
    body = VALID_BODY.format(version=VERSION).replace(
        'base_directory = ""', f'base_directory = "{from_toml.as_posix()}"'
    )
    effective = load_body(tmp_path, body, settings_data={"output_base_directory": "relative"})
    assert effective.output.base_directory == from_toml
    assert any(d.source == config.SOURCE_SETTINGS for d in effective.diagnostics)


def test_the_overlay_allowlist_is_exactly_the_output_base():
    assert config.SETTINGS_OVERLAY == {"output_base_directory": "output.base_directory"}
    assert config.is_allowlisted_setting("output_base_directory")
    assert not config.is_allowlisted_setting("logging_max_sessions")
    assert not config.is_allowlisted_setting("last_tool")


def test_known_user_state_keys_are_carried_without_being_configuration(tmp_path):
    """Fixture corrected by the v0.6.1 Plan 4 Phase 12 remediation.

    The assertion is unchanged; only the sample key is. This used to pass
    ``"input_dir"``, which was in ``USER_STATE_SETTINGS`` but which **no writer in
    this repository has ever produced** — so the test proved the allowlist worked
    for a key that could not occur, while the real namespaced keys the panels do
    write (``cover_resizer.input_dir``) warned the user on every launch. The key
    below is taken from ``cover_resizer.KEY_INPUT_DIR``.
    """
    effective = load_body(
        tmp_path,
        VALID_BODY.format(version=VERSION),
        settings_data={"last_tool": "m4b_metadata",
                       "cover_resizer.input_dir": "D:/Books"},
    )
    assert effective.diagnostics == ()          # legitimate state, not a warning
    assert "last_tool" not in effective.sources  # ...and never a configuration key


def test_a_non_allowlisted_settings_key_is_ignored_with_one_diagnostic(tmp_path):
    effective = load_body(
        tmp_path,
        VALID_BODY.format(version=VERSION),
        settings_data={"logging.max_sessions": 3, "output.base_directory": "/tmp/x"},
    )
    assert effective.logging.max_sessions == 30
    assert effective.output.is_default is True
    settings_diags = [d for d in effective.diagnostics if d.source == config.SOURCE_SETTINGS]
    assert len(settings_diags) == 1
    assert "not allowlisted" in settings_diags[0].message


def test_an_unreadable_settings_file_is_reported_and_ignored(tmp_path):
    effective = load_body(
        tmp_path,
        VALID_BODY.format(version=VERSION),
        settings_data={},
        settings_error="JSONDecodeError: Expecting value: line 1 column 1",
    )
    assert any(d.source == config.SOURCE_SETTINGS for d in effective.diagnostics)
    assert "JSONDecodeError" not in effective.warning_summary()
    assert any("JSONDecodeError" in line for line in effective.technical_details())


# --------------------------------------------------------------------------- #
# Diagnostics presentation
# --------------------------------------------------------------------------- #


def test_the_warning_summary_is_deduplicated_and_bulleted():
    diags = [
        config.Diagnostic("config.toml", "logging.max_sessions", "out of range", "got 0"),
        config.Diagnostic("config.toml", "logging.max_sessions", "out of range", "got 0"),
        config.Diagnostic("settings.json", "", "ignored", "detail"),
    ]
    summary = config.warning_summary(diags)
    assert summary.count("out of range") == 1
    assert summary.count("•") == 2


def test_a_clean_load_produces_an_empty_summary(tmp_path):
    effective = load_body(tmp_path, VALID_BODY.format(version=VERSION))
    assert effective.warning_summary() == ""
    assert effective.technical_details() == []
    assert effective.has_warnings is False


def test_every_diagnostic_names_its_source_and_explains_the_fallback(tmp_path):
    body = VALID_BODY.format(version=VERSION).replace("max_sessions = 30",
                                                      "max_sessions = 0")
    effective = load_body(tmp_path, body)
    diag = effective.diagnostics[0]
    assert diag.source == config.SOURCE_TOML
    assert diag.key == "logging.max_sessions"
    assert "using 30" in diag.message


# --------------------------------------------------------------------------- #
# Immutability, caching and reload
# --------------------------------------------------------------------------- #


def test_the_snapshot_is_immutable(tmp_path):
    effective = load_body(tmp_path, VALID_BODY.format(version=VERSION))
    with pytest.raises(Exception):
        effective.project.name = "changed"          # frozen dataclass
    with pytest.raises(Exception):
        effective.sources["project.name"] = "x"     # mapping proxy
    assert isinstance(effective.project.platforms, tuple)
    assert isinstance(effective.diagnostics, tuple)


def test_get_effective_caches_and_reload_rebuilds(tmp_path):
    from shared import settings as app_settings

    app_settings.use_path(tmp_path / "settings.json")
    config.invalidate()
    try:
        first = config.get_effective()
        assert config.get_effective() is first, "the snapshot must be cached"
        second = config.reload()
        assert second is not first, "reload must rebuild"
        assert config.get_effective() is second
    finally:
        app_settings.use_path(None)
        config.invalidate()


def test_loading_configuration_never_imports_tkinter():
    """The configuration core stays platform-neutral and headless."""
    text = (REPO_ROOT / "scripts" / "Universal" / "shared" / "config.py").read_text(
        encoding="utf-8"
    )
    assert "tkinter" not in text
    assert "import tk" not in text


def test_the_config_module_never_imports_logging_setup():
    """Log retention reads config; config must not read logging, or they recurse.

    Parsed rather than grepped, so the module docstring may keep explaining the
    rule without tripping the test that enforces it.
    """
    import ast

    source = (REPO_ROOT / "scripts" / "Universal" / "shared" / "config.py").read_text(
        encoding="utf-8"
    )
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(alias.name for alias in node.names)
    assert "logging_setup" not in imported
    assert not any("tkinter" in name for name in imported)


# --------------------------------------------------------------------------- #
# Logging retention
# --------------------------------------------------------------------------- #


def _make_sessions(directory: Path, count: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (directory / f"session_2026-08-{i + 1:02d}_000000.log").write_text("x", encoding="utf-8")


def test_log_retention_uses_the_configured_value(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    _make_sessions(logs, 10)
    monkeypatch.setattr(logging_setup, "configured_max_sessions", lambda: 4)
    logging_setup._prune_old_logs(logs_dir=logs)
    assert len(list(logs.glob("session_*.log"))) == 4


def test_log_retention_keeps_the_newest_sessions(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    _make_sessions(logs, 5)
    monkeypatch.setattr(logging_setup, "configured_max_sessions", lambda: 2)
    logging_setup._prune_old_logs(logs_dir=logs)
    remaining = sorted(p.name for p in logs.glob("session_*.log"))
    assert remaining == [
        "session_2026-08-04_000000.log",
        "session_2026-08-05_000000.log",
    ]


def test_log_retention_reads_the_effective_configuration(tmp_path, monkeypatch):
    root = fake_repo(tmp_path)
    write_config(
        root,
        VALID_BODY.format(version=VERSION).replace("max_sessions = 30", "max_sessions = 5"),
    )
    snapshot = config.load(config_path=root / "config.toml", settings_data={}, repo_root=root)
    monkeypatch.setattr(config, "get_effective", lambda: snapshot)
    assert logging_setup.configured_max_sessions() == 5


def test_log_retention_falls_back_when_configuration_raises(monkeypatch):
    def boom():
        raise RuntimeError("configuration unavailable")

    monkeypatch.setattr(config, "get_effective", boom)
    assert logging_setup.configured_max_sessions() == logging_setup.DEFAULT_MAX_SESSIONS


def test_log_retention_falls_back_when_the_config_module_cannot_be_imported(monkeypatch):
    """Logging must start even if the configuration module cannot be imported."""
    import shared

    monkeypatch.delattr(shared, "config", raising=False)
    monkeypatch.setitem(sys.modules, "shared.config", None)
    assert logging_setup.configured_max_sessions() == logging_setup.DEFAULT_MAX_SESSIONS


def test_the_code_default_for_retention_is_unchanged():
    assert logging_setup.DEFAULT_MAX_SESSIONS == 30
    assert logging_setup.MAX_SESSIONS == 30
    assert config.DEFAULTS["logging.max_sessions"] == 30
