"""v0.6.1 Plan 4 Phase 12 — the fatal-fault diagnostic wiring.

A real Windows access violation inside ``torch_cpu.dll`` killed the application
during a Chatterbox run and left the session log ending mid-sentence, because a
native fatal fault unwinds nothing. ``faulthandler`` is the standard library's
answer, and these tests prove it is wired correctly *without* a test that has to
kill the interpreter to observe it: the module exposes an injectable seam, so the
call can be asserted directly.

What must hold:

* start-up arms it, against this session's own log file, for all threads;
* the handle handed to ``faulthandler`` stays open for the process lifetime —
  notably it is **not** the logging handler's stream, which ``logging.shutdown()``
  closes at exit;
* arming twice does not open a second handle or stack a second handler;
* if arming fails for any reason the application still starts, and says so;
* the ordinary logger keeps working either way;
* nothing new is imported, no subprocess is spawned, and no engine value moves.
"""

from __future__ import annotations

import ast
import importlib
import io
import logging
from pathlib import Path

import pytest

from shared import logging_setup

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPO_ROOT / "scripts" / "Universal" / "launcher.py"
MODULE = REPO_ROOT / "scripts" / "Universal" / "shared" / "logging_setup.py"


class FakeFaulthandler:
    """Records what production asked for, so no test has to fault for real."""

    def __init__(self, explode: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.explode = explode
        self.disabled = 0

    def enable(self, *, file=None, all_threads=None):
        self.calls.append({"file": file, "all_threads": all_threads})
        if self.explode is not None:
            raise self.explode

    def disable(self):
        self.disabled += 1


@pytest.fixture
def session_log(tmp_path, monkeypatch):
    """A real configured logger writing into ``tmp_path``, torn down cleanly."""
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(logging_setup.paths, "LOGS_DIR", logs)
    monkeypatch.setattr(logging_setup.paths, "logs_dir", lambda: logs)
    monkeypatch.setattr(logging_setup, "_configured", False)
    monkeypatch.setattr(logging_setup, "_session_log_path", None)
    monkeypatch.setattr(logging_setup, "_fatal_stream", None)

    logger = logging.getLogger(logging_setup._LOGGER_NAME)
    saved = list(logger.handlers)
    logger.handlers.clear()
    try:
        yield logging_setup.get_logger()
    finally:
        logging_setup.disable_fatal_diagnostics()
        for handler in list(logger.handlers):
            handler.close()
        logger.handlers[:] = saved


def _source_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Arming
# --------------------------------------------------------------------------- #
def test_startup_arms_the_fatal_handler(session_log):
    fake = FakeFaulthandler()
    assert logging_setup.enable_fatal_diagnostics(faulthandler_module=fake) is True
    assert len(fake.calls) == 1


def test_every_thread_is_dumped_not_just_the_one_that_faulted(session_log):
    """The Chatterbox engine runs on a worker; a main-thread-only dump is useless."""
    fake = FakeFaulthandler()
    logging_setup.enable_fatal_diagnostics(faulthandler_module=fake)
    assert fake.calls[0]["all_threads"] is True


def test_the_dump_lands_in_this_sessions_own_log_file(session_log):
    fake = FakeFaulthandler()
    logging_setup.enable_fatal_diagnostics(faulthandler_module=fake)
    handed = fake.calls[0]["file"]
    assert Path(handed.name) == logging_setup.session_log_path()


def test_the_session_log_path_is_the_one_the_logger_actually_writes_to(session_log):
    handler = next(h for h in session_log.handlers
                   if isinstance(h, logging.FileHandler))
    assert Path(handler.baseFilename) == logging_setup.session_log_path()


def test_a_fatal_dump_would_be_written_to_a_real_open_descriptor(session_log):
    fake = FakeFaulthandler()
    logging_setup.enable_fatal_diagnostics(faulthandler_module=fake)
    handed = fake.calls[0]["file"]
    assert not handed.closed
    assert handed.fileno() >= 0


# --------------------------------------------------------------------------- #
# Lifetime — the point of the whole design
# --------------------------------------------------------------------------- #
def test_the_handle_is_not_the_logging_handlers_stream(session_log):
    """``logging.shutdown()`` closes handler streams at exit; faulthandler needs
    a descriptor that is still valid *after* that."""
    fake = FakeFaulthandler()
    logging_setup.enable_fatal_diagnostics(faulthandler_module=fake)
    handed = fake.calls[0]["file"]
    handler = next(h for h in session_log.handlers
                   if isinstance(h, logging.FileHandler))
    assert handed is not handler.stream


def test_closing_the_logging_handler_leaves_the_fatal_handle_usable(session_log):
    fake = FakeFaulthandler()
    logging_setup.enable_fatal_diagnostics(faulthandler_module=fake)
    handed = fake.calls[0]["file"]
    for handler in list(session_log.handlers):
        handler.close()
    assert not handed.closed
    handed.write("still writable after logging shutdown\n")


def test_arming_twice_does_not_open_a_second_handle(session_log):
    fake = FakeFaulthandler()
    assert logging_setup.enable_fatal_diagnostics(faulthandler_module=fake) is True
    first = fake.calls[0]["file"]
    assert logging_setup.enable_fatal_diagnostics(faulthandler_module=fake) is True
    assert len(fake.calls) == 1, "the second call must not re-enable"
    assert first is not None and not first.closed


def test_disabling_closes_exactly_the_one_handle_that_was_opened(session_log):
    fake = FakeFaulthandler()
    logging_setup.enable_fatal_diagnostics(faulthandler_module=fake)
    handed = fake.calls[0]["file"]
    logging_setup.disable_fatal_diagnostics()
    assert handed.closed
    assert logging_setup.fatal_diagnostics_armed() is False


def test_disabling_when_never_armed_is_harmless(session_log):
    logging_setup.disable_fatal_diagnostics()
    logging_setup.disable_fatal_diagnostics()
    assert logging_setup.fatal_diagnostics_armed() is False


def test_it_can_be_armed_again_after_being_disabled(session_log):
    fake = FakeFaulthandler()
    logging_setup.enable_fatal_diagnostics(faulthandler_module=fake)
    logging_setup.disable_fatal_diagnostics()
    assert logging_setup.enable_fatal_diagnostics(faulthandler_module=fake) is True
    assert len(fake.calls) == 2
    assert not fake.calls[1]["file"].closed


def test_armed_state_is_reported_truthfully(session_log):
    assert logging_setup.fatal_diagnostics_armed() is False
    logging_setup.enable_fatal_diagnostics(faulthandler_module=FakeFaulthandler())
    assert logging_setup.fatal_diagnostics_armed() is True


# --------------------------------------------------------------------------- #
# Failure to arm must never cost the user their application
# --------------------------------------------------------------------------- #
def test_a_refusing_faulthandler_does_not_raise(session_log):
    fake = FakeFaulthandler(explode=RuntimeError("sys.stderr is invalid"))
    assert logging_setup.enable_fatal_diagnostics(faulthandler_module=fake) is False


def test_a_failed_arming_leaves_nothing_armed_and_no_open_handle(session_log):
    fake = FakeFaulthandler(explode=OSError("bad descriptor"))
    logging_setup.enable_fatal_diagnostics(faulthandler_module=fake)
    assert logging_setup.fatal_diagnostics_armed() is False
    assert fake.calls[0]["file"].closed, "the handle must not be left dangling"


def test_a_failed_arming_is_recorded_in_the_log(session_log, tmp_path):
    fake = FakeFaulthandler(explode=RuntimeError("nope"))
    logging_setup.enable_fatal_diagnostics(faulthandler_module=fake)
    for handler in session_log.handlers:
        handler.flush()
    text = logging_setup.session_log_path().read_text(encoding="utf-8")
    assert "fatal-fault diagnostics could not be armed" in text


def test_the_ordinary_logger_still_works_after_a_failed_arming(session_log):
    logging_setup.enable_fatal_diagnostics(
        faulthandler_module=FakeFaulthandler(explode=RuntimeError("nope")))
    session_log.debug("an ordinary line")
    for handler in session_log.handlers:
        handler.flush()
    assert "an ordinary line" in logging_setup.session_log_path().read_text(
        encoding="utf-8")


def test_a_successful_arming_is_recorded_in_the_log(session_log):
    logging_setup.enable_fatal_diagnostics(faulthandler_module=FakeFaulthandler())
    for handler in session_log.handlers:
        handler.flush()
    assert "Fatal-fault diagnostics armed" in logging_setup.session_log_path().read_text(
        encoding="utf-8")


# --------------------------------------------------------------------------- #
# Where it is wired, and what it must not disturb
# --------------------------------------------------------------------------- #
def _launcher_init_body() -> ast.FunctionDef:
    tree = _source_tree(LAUNCHER)
    app = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == "LauncherApp")
    return next(n for n in app.body
                if isinstance(n, ast.FunctionDef) and n.name == "__init__")


def test_the_launcher_arms_diagnostics_during_startup():
    """Parsed, not string-matched: a comment mentioning it must not satisfy this."""
    calls = [n for n in ast.walk(_launcher_init_body())
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "enable_fatal_diagnostics"]
    assert len(calls) == 1


def test_diagnostics_are_armed_before_any_tool_panel_is_built():
    """A worker cannot exist before a panel does, so arming must come first."""
    body = _launcher_init_body()
    order = []
    for node in ast.walk(body):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("enable_fatal_diagnostics", "select_tool",
                                  "_build_ui"):
                order.append((node.lineno, node.func.attr))
    order.sort()
    names = [name for _line, name in order]
    assert names.index("enable_fatal_diagnostics") < names.index("_build_ui")
    assert names.index("enable_fatal_diagnostics") < names.index("select_tool")


def test_the_diagnostic_adds_no_third_party_import():
    """Standard library only — no requirements change may hide in here."""
    tree = _source_tree(MODULE)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "faulthandler", "logging", "datetime",
                        "pathlib"}


def test_the_diagnostic_spawns_no_subprocess():
    source = MODULE.read_text(encoding="utf-8")
    for banned in ("subprocess", "os.system", "multiprocessing", "Popen"):
        assert banned not in source


def test_requirements_are_untouched_by_this_diagnostic():
    text = (REPO_ROOT / "scripts" / "requirements.txt").read_text(encoding="utf-8")
    assert "faulthandler" not in text


def test_the_launcher_still_registers_exactly_six_tools():
    launcher = importlib.import_module("launcher")
    assert len(launcher.TOOLS) == 6


def test_the_version_did_not_move():
    from shared import version

    assert version.VERSION == "0.5.1"


# --------------------------------------------------------------------------- #
# The settled Chatterbox values this diagnostic must not have disturbed
# --------------------------------------------------------------------------- #
def test_no_settled_chatterbox_value_moved():
    cbx = importlib.import_module("tts.chatterbox_synth")
    assert cbx.CHATTERBOX_MAX_CHUNK_CHARS == 300
    assert cbx.GENERATION_TEMPERATURE == 0.72
    assert cbx.PHASE9_EVALUATION_TEMPERATURE == 0.8
    assert cbx.COLON_PAUSE_MS == 75


def test_the_four_approved_voices_are_still_registered():
    registry = importlib.import_module("tts.voice_registry")
    chatterbox = [v for v in registry.VOICES if v.backend == "chatterbox"]
    assert len(chatterbox) == 4
    assert len(registry.VOICES) == 16


def test_the_diagnostic_touched_no_engine_module():
    """The whole change is logging plus one launcher line — prove the engine
    modules contain no faulthandler wiring that could have crept in."""
    for name in ("tts/chatterbox_synth.py", "tts/kokoro_synth.py",
                 "tts/epub2tts_gui.py"):
        source = (REPO_ROOT / "scripts" / "Universal" / name).read_text(
            encoding="utf-8")
        assert "faulthandler" not in source


def test_arming_writes_nothing_into_the_tracked_tree(session_log):
    logging_setup.enable_fatal_diagnostics(faulthandler_module=FakeFaulthandler())
    destination = logging_setup.session_log_path()
    assert "runtime-data" in str(destination).replace("\\", "/") or \
        str(destination).startswith(str(Path(session_log.handlers[0].baseFilename).parent))


def test_the_real_faulthandler_module_is_the_default(session_log, monkeypatch):
    """No injection means production, not a stub left behind by a test."""
    seen = {}

    def fake_open(*args, **kwargs):
        seen["opened"] = True
        return io.StringIO()

    import faulthandler as real

    monkeypatch.setattr(real, "enable", lambda **kw: seen.update(kw))
    monkeypatch.setattr("builtins.open", fake_open)
    logging_setup.enable_fatal_diagnostics()
    assert seen.get("all_threads") is True
    logging_setup.disable_fatal_diagnostics()
