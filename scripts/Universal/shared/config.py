"""Typed, immutable effective configuration for the Audiobook Creation Tool.

Precedence, highest last:

1. immutable code defaults (:data:`DEFAULTS`);
2. individually valid values from the committed root ``config.toml``;
3. valid values for the explicitly allowlisted mutable settings stored in
   ``files/runtime-data/settings.json`` (see :data:`SETTINGS_OVERLAY`).

Every key is validated on its own, so one bad value never discards an unrelated
good one, and a missing or malformed ``config.toml`` can never stop the
application from starting. Anything that falls back records a
:class:`Diagnostic` naming the source, the key and the fallback, so a caller can
log the technical detail and present a single aggregated, human-readable summary
(``warning_summary``) with no raw traceback in it.

Two structural rules this module must keep:

- **Tk-free and platform-neutral.** Parsing, validation and precedence take
  paths and data as inputs; presenting the result is somebody else's job.
- **It never imports ``logging_setup``.** Log retention reads *this* module, so
  the dependency runs one way only and cannot recurse.

Loading configuration never creates a directory — resolving the output base
computes a path and nothing more.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from . import paths, settings as app_settings
from .version import VERSION

# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #

SOURCE_DEFAULT = "default"
SOURCE_TOML = "config.toml"
SOURCE_SETTINGS = "settings.json"

CONFIG_FILENAME = "config.toml"

#: The folder created under the user's Downloads directory when no base is set.
OUTPUT_BASE_FOLDER_NAME = "Audiobook-Creation-Tool-Outputs"

#: Platform identifiers this project recognises. The values on the right are the
#: normalised spellings used everywhere else in the tree (``scripts/Windows``,
#: ``scripts/MacOS``, ``release.ENTRY_FILES``); the keys make the match
#: case-insensitive so ``macOS`` in a hand-edited file still validates.
KNOWN_PLATFORMS: dict[str, str] = {
    "windows": "Windows",
    "macos": "MacOS",
}

#: settings.json key -> dotted configuration key it may override. This is the
#: WHOLE mutable overlay: a settings key that is not listed here can never reach
#: the effective configuration, however it is spelled.
SETTINGS_OVERLAY: dict[str, str] = {
    "output_base_directory": "output.base_directory",
}

#: Settings keys that are legitimate user state but deliberately have no
#: configuration counterpart. They are skipped silently instead of being
#: reported as unrecognised. Do not invent TOML keys for these.
USER_STATE_SETTINGS: frozenset[str] = frozenset(
    {
        "last_tool",
        "input_dir",
        "output_dir",
        "cover_dir",
        "m4b_input_dir",
        "m4b_output_dir",
        "m4b_cover_dir",
        "mp3_input_dir",
        "mp3_output_dir",
        "tts_input_dir",
        "tts_output_dir",
        "metadata_input_dir",
        "metadata_output_dir",
        "metadata_cover_dir",
        "cover_input_dir",
        "voice",
        "bitrate",
    }
)

#: Every key this project understands, per section. Anything else in the TOML is
#: ignored and reported once so a typo cannot look supported.
_SCHEMA: dict[str, frozenset[str]] = {
    "project": frozenset({"name", "version", "python_min", "entry_point", "platforms"}),
    "output": frozenset({"base_directory"}),
    "logging": frozenset({"max_sessions"}),
    "importing": frozenset({"large_result_warning_threshold"}),
}

# --------------------------------------------------------------------------- #
# Immutable code defaults — the floor nothing can remove
# --------------------------------------------------------------------------- #

DEFAULT_PROJECT_NAME = "Audiobook Creation Tool"
DEFAULT_PYTHON_MIN = "3.11"
DEFAULT_ENTRY_POINT = "scripts/Universal/launcher.py"
DEFAULT_PLATFORMS: tuple[str, ...] = ("Windows", "MacOS")
DEFAULT_MAX_SESSIONS = 30
DEFAULT_LARGE_RESULT_WARNING_THRESHOLD = 1000

MAX_SESSIONS_RANGE = (1, 1000)
LARGE_RESULT_THRESHOLD_RANGE = (1, 1_000_000)

_PYTHON_MIN_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

DEFAULTS: Mapping[str, Any] = MappingProxyType(
    {
        "project.name": DEFAULT_PROJECT_NAME,
        "project.version": VERSION,
        "project.python_min": DEFAULT_PYTHON_MIN,
        "project.entry_point": DEFAULT_ENTRY_POINT,
        "project.platforms": DEFAULT_PLATFORMS,
        "output.base_directory": "",
        "logging.max_sessions": DEFAULT_MAX_SESSIONS,
        "importing.large_result_warning_threshold": DEFAULT_LARGE_RESULT_WARNING_THRESHOLD,
    }
)


# --------------------------------------------------------------------------- #
# Diagnostics
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Diagnostic:
    """One thing that did not load as written, and what happened instead.

    ``message`` is written for a person and is safe to show in a summary.
    ``detail`` carries the technical remainder (an exception's text, the raw
    value) and belongs in the log, never in a dialog.
    """

    source: str
    key: str
    message: str
    detail: str = ""
    severity: str = "warning"

    def summary_line(self) -> str:
        where = self.key or "(file)"
        return f"{self.source} — {where}: {self.message}"


def warning_summary(diagnostics) -> str:
    """One human-readable block for every diagnostic, deduplicated and ordered.

    Identical lines collapse to one, so a repeated fallback cannot spam the
    user. Returns an empty string when there is nothing to say.
    """
    seen: list[str] = []
    for diag in diagnostics:
        line = diag.summary_line()
        if line not in seen:
            seen.append(line)
    return "\n".join(f"• {line}" for line in seen)


def technical_details(diagnostics) -> list[str]:
    """The loggable form: one line per diagnostic including its ``detail``."""
    out: list[str] = []
    for diag in diagnostics:
        line = f"[{diag.severity}] {diag.source} {diag.key or '(file)'}: {diag.message}"
        if diag.detail:
            line += f" | {diag.detail}"
        if line not in out:
            out.append(line)
    return out


# --------------------------------------------------------------------------- #
# The immutable snapshot
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    version: str
    python_min: str
    entry_point: str
    platforms: tuple[str, ...]


@dataclass(frozen=True)
class OutputConfig:
    #: Always absolute. Computed, never created.
    base_directory: Path
    #: True when no valid override was supplied and the Downloads default applies.
    is_default: bool


@dataclass(frozen=True)
class LoggingConfig:
    max_sessions: int


@dataclass(frozen=True)
class ImportingConfig:
    #: Validated here; Plan 3 owns the behaviour that consumes it.
    large_result_warning_threshold: int


@dataclass(frozen=True)
class EffectiveConfig:
    """A frozen snapshot. Capture one at run start and it cannot shift underneath."""

    project: ProjectConfig
    output: OutputConfig
    logging: LoggingConfig
    importing: ImportingConfig
    #: dotted key -> which layer supplied the effective value.
    sources: Mapping[str, str]
    diagnostics: tuple[Diagnostic, ...]

    @property
    def has_warnings(self) -> bool:
        return bool(self.diagnostics)

    def source_of(self, dotted_key: str) -> str:
        return self.sources.get(dotted_key, SOURCE_DEFAULT)

    def warning_summary(self) -> str:
        return warning_summary(self.diagnostics)

    def technical_details(self) -> list[str]:
        return technical_details(self.diagnostics)


# --------------------------------------------------------------------------- #
# Path helpers
# --------------------------------------------------------------------------- #


def _downloads_dir(home: Path | None) -> Path:
    if home is None:
        return paths.downloads_dir()
    candidate = home / "Downloads"
    return candidate if candidate.exists() else home


def default_output_base(home: Path | None = None) -> Path:
    """``<Downloads>/Audiobook-Creation-Tool-Outputs`` — computed, not created."""
    return _downloads_dir(home) / OUTPUT_BASE_FOLDER_NAME


def _resolve_output_base(raw: str, home: Path | None) -> tuple[Path | None, str]:
    """Validate a configured output base.

    Returns ``(path, "")`` on success or ``(None, reason)`` on rejection.
    ``~`` is expanded because it is a portable, machine-agnostic way to name a
    home-relative location. Environment variables are deliberately **not**
    expanded, so ``%USERPROFILE%\\x`` or ``$HOME/x`` stays a literal relative
    name and is rejected below rather than silently resolving.
    """
    text = raw.strip()
    if not text:
        return None, "empty"

    candidate = Path(text)
    if text.startswith("~"):
        expanded = Path(text).expanduser()
        if str(expanded).startswith("~"):
            return None, "'~' could not be expanded to a home directory"
        candidate = expanded

    if not candidate.is_absolute():
        return None, "a relative path is not accepted (give an absolute path or a '~' path)"

    return candidate, ""


# --------------------------------------------------------------------------- #
# Per-key validation
# --------------------------------------------------------------------------- #


class _Builder:
    """Accumulates validated values, their source, and any diagnostics."""

    def __init__(self, repo_root: Path, home: Path | None):
        self.repo_root = repo_root
        self.home = home
        self.values: dict[str, Any] = dict(DEFAULTS)
        self.sources: dict[str, str] = {key: SOURCE_DEFAULT for key in DEFAULTS}
        self.diagnostics: list[Diagnostic] = []

    def note(self, source: str, key: str, message: str, detail: str = "") -> None:
        self.diagnostics.append(Diagnostic(source, key, message, detail))

    def accept(self, source: str, key: str, value: Any) -> None:
        self.values[key] = value
        self.sources[key] = source

    # -- individual keys ---------------------------------------------------- #

    def project_name(self, source: str, raw: Any) -> None:
        key = "project.name"
        if not isinstance(raw, str) or not raw.strip():
            self.note(source, key, f"must be a non-blank string; using {DEFAULT_PROJECT_NAME!r}",
                      f"got {raw!r}")
            return
        self.accept(source, key, raw.strip())

    def project_version(self, source: str, raw: Any) -> None:
        key = "project.version"
        if not isinstance(raw, str) or not _VERSION_RE.match(raw.strip()):
            self.note(source, key, f"must look like 'X.Y.Z'; using the code version {VERSION}",
                      f"got {raw!r}")
            return
        text = raw.strip()
        if text != VERSION:
            # The code is always the source of truth at runtime. Repository
            # verification treats the same drift as a hard failure.
            self.note(source, key,
                      f"says {text} but the application is {VERSION}; using {VERSION}",
                      f"config.toml={text!r} version.py={VERSION!r}")
            return
        self.accept(source, key, text)

    def project_python_min(self, source: str, raw: Any) -> None:
        key = "project.python_min"
        if not isinstance(raw, str) or not _PYTHON_MIN_RE.match(raw.strip()):
            self.note(source, key,
                      f"must look like 'X.Y' or 'X.Y.Z'; using {DEFAULT_PYTHON_MIN}",
                      f"got {raw!r}")
            return
        self.accept(source, key, raw.strip())

    def project_entry_point(self, source: str, raw: Any) -> None:
        key = "project.entry_point"
        fallback = f"using {DEFAULT_ENTRY_POINT}"
        if not isinstance(raw, str) or not raw.strip():
            self.note(source, key, f"must be a non-blank relative path; {fallback}", f"got {raw!r}")
            return
        text = raw.strip().replace("\\", "/")
        candidate = Path(text)
        if candidate.is_absolute() or ".." in candidate.parts:
            self.note(source, key,
                      f"must be a relative in-repository path without '..'; {fallback}",
                      f"got {raw!r}")
            return
        if not (self.repo_root / candidate).is_file():
            self.note(source, key, f"does not point at a file in this repository; {fallback}",
                      f"resolved to {self.repo_root / candidate}")
            return
        self.accept(source, key, text)

    def project_platforms(self, source: str, raw: Any) -> None:
        key = "project.platforms"
        fallback = f"using {list(DEFAULT_PLATFORMS)}"
        if not isinstance(raw, list) or not raw:
            self.note(source, key, f"must be a non-empty array of platform names; {fallback}",
                      f"got {raw!r}")
            return
        kept: list[str] = []
        rejected: list[str] = []
        for item in raw:
            normalised = KNOWN_PLATFORMS.get(item.strip().lower()) if isinstance(item, str) else None
            if normalised is None:
                rejected.append(repr(item))
            elif normalised not in kept:
                kept.append(normalised)
        if rejected:
            known = ", ".join(sorted(set(KNOWN_PLATFORMS.values())))
            self.note(source, key, f"ignoring unknown platform(s); known values are {known}",
                      f"rejected {', '.join(rejected)}")
        if not kept:
            self.note(source, key, f"no known platform remained; {fallback}", "")
            return
        self.accept(source, key, tuple(kept))

    def output_base(self, source: str, raw: Any) -> None:
        key = "output.base_directory"
        fallback = "using the default Downloads location"
        if not isinstance(raw, str):
            self.note(source, key, f"must be a string; {fallback}", f"got {raw!r}")
            return
        if not raw.strip():
            # An explicit empty value is the documented way to say "default".
            self.accept(source, key, "")
            return
        resolved, reason = _resolve_output_base(raw, self.home)
        if resolved is None:
            self.note(source, key, f"{reason}; {fallback}", f"got {raw!r}")
            return
        self.accept(source, key, str(resolved))

    def _bounded_int(self, source: str, key: str, raw: Any, bounds: tuple[int, int]) -> None:
        low, high = bounds
        default = DEFAULTS[key]
        # bool is an int subclass; `logging.max_sessions = true` is a mistake.
        if not isinstance(raw, int) or isinstance(raw, bool):
            self.note(source, key, f"must be a whole number; using {default}", f"got {raw!r}")
            return
        if not (low <= raw <= high):
            self.note(source, key, f"must be between {low} and {high}; using {default}",
                      f"got {raw!r}")
            return
        self.accept(source, key, raw)

    def logging_max_sessions(self, source: str, raw: Any) -> None:
        self._bounded_int(source, "logging.max_sessions", raw, MAX_SESSIONS_RANGE)

    def importing_threshold(self, source: str, raw: Any) -> None:
        self._bounded_int(source, "importing.large_result_warning_threshold", raw,
                          LARGE_RESULT_THRESHOLD_RANGE)


_TOML_VALIDATORS = {
    "project.name": _Builder.project_name,
    "project.version": _Builder.project_version,
    "project.python_min": _Builder.project_python_min,
    "project.entry_point": _Builder.project_entry_point,
    "project.platforms": _Builder.project_platforms,
    "output.base_directory": _Builder.output_base,
    "logging.max_sessions": _Builder.logging_max_sessions,
    "importing.large_result_warning_threshold": _Builder.importing_threshold,
}


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def read_toml(path: Path) -> tuple[dict[str, Any], Diagnostic | None]:
    """Parse *path*. Returns ``({}, diagnostic)`` rather than raising, ever."""
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return {}, Diagnostic(
            SOURCE_TOML, "",
            "not found; every value falls back to the built-in defaults",
            f"expected at {path}",
        )
    except tomllib.TOMLDecodeError as exc:
        return {}, Diagnostic(
            SOURCE_TOML, "",
            "could not be read as TOML; every value falls back to the built-in defaults",
            f"{type(exc).__name__}: {exc}",
        )
    except OSError as exc:
        return {}, Diagnostic(
            SOURCE_TOML, "",
            "could not be opened; every value falls back to the built-in defaults",
            f"{type(exc).__name__}: {exc}",
        )
    if not isinstance(data, dict):
        return {}, Diagnostic(
            SOURCE_TOML, "",
            "is not a table of sections; every value falls back to the built-in defaults",
            f"parsed a {type(data).__name__}",
        )
    return data, None


def _apply_toml(builder: _Builder, data: Mapping[str, Any]) -> None:
    unknown: list[str] = []
    for section, contents in data.items():
        known_keys = _SCHEMA.get(section)
        if known_keys is None:
            unknown.append(section)
            continue
        if not isinstance(contents, dict):
            builder.note(SOURCE_TOML, section,
                         "must be a section (a [table]); ignoring it",
                         f"got a {type(contents).__name__}")
            continue
        for name, value in contents.items():
            dotted = f"{section}.{name}"
            if name not in known_keys:
                unknown.append(dotted)
                continue
            _TOML_VALIDATORS[dotted](builder, SOURCE_TOML, value)
    if unknown:
        builder.note(
            SOURCE_TOML, "",
            "contains entries this version does not use; they were ignored",
            "unrecognised: " + ", ".join(sorted(set(unknown))),
        )


def _apply_settings(builder: _Builder, data: Mapping[str, Any]) -> None:
    unrecognised: list[str] = []
    for key, value in data.items():
        dotted = SETTINGS_OVERLAY.get(key)
        if dotted is not None:
            _TOML_VALIDATORS[dotted](builder, SOURCE_SETTINGS, value)
            continue
        if key in USER_STATE_SETTINGS:
            continue  # legitimate user state with no configuration counterpart
        unrecognised.append(key)
    if unrecognised:
        allowed = ", ".join(sorted(SETTINGS_OVERLAY)) or "(none)"
        builder.note(
            SOURCE_SETTINGS, "",
            "holds keys that are not allowlisted configuration overrides; they were ignored",
            f"ignored: {', '.join(sorted(unrecognised))}; allowlisted: {allowed}",
        )


def load(
    *,
    config_path: Path | None = None,
    settings_data: Mapping[str, Any] | None = None,
    settings_error: str | None = None,
    repo_root: Path | None = None,
    home: Path | None = None,
) -> EffectiveConfig:
    """Build one immutable snapshot. Never raises, never writes, never mkdirs.

    Every argument exists so a test can inject a temporary tree instead of
    touching the maintainer's real repository, settings or home directory.
    """
    root = Path(repo_root) if repo_root is not None else paths.REPO_ROOT
    path = Path(config_path) if config_path is not None else root / CONFIG_FILENAME

    builder = _Builder(root, home)

    data, file_diag = read_toml(path)
    if file_diag is not None:
        builder.diagnostics.append(file_diag)
    else:
        _apply_toml(builder, data)

    if settings_data is None:
        settings_data = app_settings.all_settings()
        if settings_error is None:
            settings_error = app_settings.last_load_error()
    if settings_error:
        builder.note(
            SOURCE_SETTINGS, "",
            "could not be read; your saved preferences are ignored until it is replaced",
            settings_error,
        )
    _apply_settings(builder, settings_data or {})

    raw_base = builder.values["output.base_directory"]
    if raw_base:
        base_dir, is_default = Path(raw_base), False
    else:
        base_dir, is_default = default_output_base(home), True

    return EffectiveConfig(
        project=ProjectConfig(
            name=builder.values["project.name"],
            version=builder.values["project.version"],
            python_min=builder.values["project.python_min"],
            entry_point=builder.values["project.entry_point"],
            platforms=tuple(builder.values["project.platforms"]),
        ),
        output=OutputConfig(base_directory=base_dir, is_default=is_default),
        logging=LoggingConfig(max_sessions=builder.values["logging.max_sessions"]),
        importing=ImportingConfig(
            large_result_warning_threshold=builder.values[
                "importing.large_result_warning_threshold"
            ],
        ),
        sources=MappingProxyType(dict(builder.sources)),
        diagnostics=tuple(builder.diagnostics),
    )


# --------------------------------------------------------------------------- #
# Process-wide cache
# --------------------------------------------------------------------------- #

_cache: EffectiveConfig | None = None


def get_effective() -> EffectiveConfig:
    """The cached snapshot for this process, loaded on first use."""
    global _cache
    if _cache is None:
        _cache = load()
    return _cache


def invalidate() -> None:
    """Drop the cached snapshot so the next read rebuilds it."""
    global _cache
    _cache = None


def reload() -> EffectiveConfig:
    """Rebuild and return the snapshot. Used by tests and by Preferences."""
    invalidate()
    return get_effective()


# --------------------------------------------------------------------------- #
# The only sanctioned writer of a configuration override
# --------------------------------------------------------------------------- #


def is_allowlisted_setting(key: str) -> bool:
    """True if *key* may override a configuration value from ``settings.json``."""
    return key in SETTINGS_OVERLAY


def validate_output_base(raw: str) -> tuple[Path | None, str]:
    """Public form of the output-base rule, for a UI that must explain itself.

    Returns ``(resolved_path, "")`` when *raw* is acceptable, or
    ``(None, reason)`` where *reason* is written for a person. Nothing is
    created, written or persisted — this only answers the question.
    """
    return _resolve_output_base(raw, None)


def set_output_base(value: str | Path | None) -> bool:
    """Persist the user's output-base choice and refresh the snapshot.

    ``None`` (or an empty string) clears the override and restores the default
    Downloads location. Returns whether the settings write succeeded. The
    committed ``config.toml`` is never touched — the GUI writes settings only.
    """
    text = "" if value is None else str(value).strip()
    if text:
        resolved, reason = _resolve_output_base(text, None)
        if resolved is None:
            raise ValueError(f"output base rejected: {reason}")
        text = str(resolved)
    ok = app_settings.set("output_base_directory", text)
    invalidate()
    return ok


def reset_preferences() -> bool:
    """Clear every mutable preference and refresh the snapshot.

    Touches ``settings.json`` only: no configuration file, model, binary, log,
    virtual environment, output or source file is read or removed here.
    """
    ok = app_settings.reset()
    invalidate()
    return ok


# --------------------------------------------------------------------------- #
# The once-per-launch warning guard
# --------------------------------------------------------------------------- #
#
# Diagnostics are produced on every load, but a user must be told about them
# once per application launch — not once per reload, and never once per bad key.
# The guard lives here rather than in the UI so it is platform-neutral, so a
# headless test can assert it, and so a reload storm cannot turn into a dialog
# storm. The UI asks; this module decides whether there is anything left to say.

_launch_warning_consumed = False


def take_launch_warning() -> str | None:
    """The aggregated summary the first time it is asked for, then ``None``.

    Consumes the guard on the first call whether or not there was anything to
    report, so a later reload — or reopening Preferences — cannot resurrect the
    launch warning.
    """
    global _launch_warning_consumed
    if _launch_warning_consumed:
        return None
    _launch_warning_consumed = True
    return get_effective().warning_summary() or None


def launch_warning_pending() -> bool:
    """Whether the guard is still unconsumed. For tests and diagnostics."""
    return not _launch_warning_consumed


def reset_launch_warning_guard() -> None:
    """Re-arm the guard. Tests use this; the application never needs to."""
    global _launch_warning_consumed
    _launch_warning_consumed = False
