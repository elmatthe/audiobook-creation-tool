"""PRE-PLAN-6 Phase 4 — nothing runs FFmpeg that was not proved to run.

**What was wrong (H3 and M2).** ``ffmpeg_utils`` resolved the pinned pair when
there was one and otherwise fell back to the first *discovered* coherent pair,
handing it to callers as an executable answer with ``verified=False`` attached —
which nobody checked. And when nothing resolved at all, ``ffmpeg_cmd()`` and
``ffprobe_cmd()`` returned the bare names ``"ffmpeg"`` and ``"ffprobe"``, each
resolved independently through PATH at exec time, so a run could execute two
halves of two different installations.

Both are the Phase 15 defect wearing a different hat. That machine had a
perfectly coherent, perfectly resolvable pair that Windows refused to execute,
and the first thing that ever ran ffprobe was a real conversion in front of the
user. **A path is not a proof. A PATH entry is not a proof. A command name is
not a proof.**

**The contract now.** Discovery is observational — it answers "does something
appear to be here?" for a status line and nothing else, and it executes nothing.
Execution comes only from ``ffmpeg_health.pinned_pair()``: coherent, both halves
actually executed, durably recorded, and still identity-matching at lookup.

The old 2026-08-28 ADR deliberately permitted the weaker behaviour. It is left
intact; the additive superseding entry is owed at Phase 10.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from shared import ffmpeg_health, ffmpeg_utils

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UNIVERSAL = REPO_ROOT / "scripts" / "Universal"
EXE = ffmpeg_health.EXE


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """No test here may read or write the machine's real health state."""
    resources = tmp_path / "runtime-data"
    resources.mkdir()
    monkeypatch.setattr(ffmpeg_health, "RESOURCES_DIR", resources)
    monkeypatch.setattr(ffmpeg_health, "BIN_DIR", tmp_path / "bin")
    monkeypatch.setattr(ffmpeg_health, "_winget_package_dirs", lambda: [])
    monkeypatch.setattr(ffmpeg_health, "_brew_dirs", lambda: [])
    monkeypatch.setenv("PATH", "")
    ffmpeg_utils.refresh()
    yield
    ffmpeg_utils.refresh()


def install(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"ffmpeg{EXE}").write_text("binary", encoding="utf-8")
    (directory / f"ffprobe{EXE}").write_text("binary", encoding="utf-8")
    return directory


def pin(monkeypatch, directory: Path):
    monkeypatch.setenv("PATH", str(directory))
    proven = ffmpeg_health.establish(runner=lambda exe: (True, "ffmpeg version 9.0.1"))
    assert proven is not None
    ffmpeg_utils.refresh()
    return proven


# --------------------------------------------------------------------------- #
# A. Observation and execution are different questions
# --------------------------------------------------------------------------- #
def test_an_unproved_pair_is_observable_but_not_executable(monkeypatch, tmp_path):
    directory = install(tmp_path / "found")
    monkeypatch.setenv("PATH", str(directory))
    ffmpeg_utils.refresh()

    assert ffmpeg_utils.discovered_ffmpeg() is True
    assert ffmpeg_utils.verified_ffmpeg() is False
    assert ffmpeg_utils.have_ffmpeg() is False
    assert ffmpeg_utils.ffmpeg_path() is None
    assert ffmpeg_utils.ffprobe_path() is None
    with pytest.raises(ffmpeg_utils.FFmpegUnavailable):
        ffmpeg_utils.ffmpeg_cmd()


def test_a_pinned_pair_is_both_observable_and_executable(monkeypatch, tmp_path):
    directory = install(tmp_path / "good")
    pin(monkeypatch, directory)

    assert ffmpeg_utils.verified_ffmpeg() is True
    assert ffmpeg_utils.have_ffmpeg() is True
    assert Path(ffmpeg_utils.ffmpeg_cmd()).parent == directory
    assert Path(ffmpeg_utils.ffprobe_cmd()).parent == directory


def test_nothing_at_all_is_neither(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    ffmpeg_utils.refresh()

    assert ffmpeg_utils.discovered_ffmpeg() is False
    assert ffmpeg_utils.have_ffmpeg() is False
    with pytest.raises(ffmpeg_utils.FFmpegUnavailable):
        ffmpeg_utils.ffprobe_cmd()


def test_observation_never_executes_anything(monkeypatch, tmp_path):
    """A blocked binary raises a Windows prompt when *run*. Status must not."""
    directory = install(tmp_path / "found")
    monkeypatch.setenv("PATH", str(directory))
    ffmpeg_utils.refresh()
    monkeypatch.setattr(ffmpeg_health, "_run_version",
                        lambda exe: pytest.fail("observation executed a binary"))

    ffmpeg_utils.discovered_ffmpeg()
    ffmpeg_utils.status_line()
    ffmpeg_utils.have_ffmpeg()
    ffmpeg_utils.verified_ffmpeg()


def test_there_is_only_one_discovery_implementation():
    """ffmpeg_utils must not grow a second scanner of its own."""
    text = Path(ffmpeg_utils.__file__).read_text(encoding="utf-8")
    for forbidden in ("shutil.which", "os.environ[\"PATH\"]", "glob("):
        assert forbidden not in text, forbidden
    assert "ffmpeg_health.discover_pairs()" in text
    assert "ffmpeg_health.pinned_pair()" in text


# --------------------------------------------------------------------------- #
# B. The command API is fail-closed and coherent
# --------------------------------------------------------------------------- #
def test_the_two_commands_always_come_from_one_installation(monkeypatch, tmp_path):
    other = install(tmp_path / "other")
    good = install(tmp_path / "good")
    pin(monkeypatch, good)
    monkeypatch.setenv("PATH", os.pathsep.join([str(other), str(good)]))
    ffmpeg_utils.refresh()

    assert Path(ffmpeg_utils.ffmpeg_cmd()).parent == \
        Path(ffmpeg_utils.ffprobe_cmd()).parent


def test_the_refusal_is_an_exception_not_a_none_or_a_name(monkeypatch, tmp_path):
    """A command list whose first element is None fails obscurely, later."""
    monkeypatch.setenv("PATH", "")
    ffmpeg_utils.refresh()

    with pytest.raises(ffmpeg_utils.FFmpegUnavailable) as raised:
        ffmpeg_utils.ffmpeg_cmd()
    assert "verified" in str(raised.value).lower()


def test_the_decoder_probe_tolerates_the_refusal(monkeypatch, tmp_path):
    """It asks ffmpeg what it supports; with no ffmpeg the answer is nothing."""
    monkeypatch.setenv("PATH", "")
    ffmpeg_utils.refresh()

    assert ffmpeg_utils._decoder_available("aac_at") is False


# --------------------------------------------------------------------------- #
# C. pydub cannot escape to a bare PATH ffmpeg
# --------------------------------------------------------------------------- #
def _pydub():
    return pytest.importorskip("pydub")


def test_pydub_is_pointed_at_the_pinned_pair(monkeypatch, tmp_path):
    pydub = _pydub()
    directory = install(tmp_path / "good")
    pin(monkeypatch, directory)
    monkeypatch.setattr(ffmpeg_utils, "_pydub_configured", False)

    ffmpeg_utils.configure_pydub()

    assert Path(pydub.AudioSegment.converter).parent == directory
    assert Path(pydub.AudioSegment.ffprobe).parent == directory


def test_pydub_is_not_left_on_its_bare_name_defaults(monkeypatch, tmp_path):
    """The one audio route no consumer gate sits in front of.

    pydub shells out to whatever ``ffmpeg`` PATH resolves when it is not
    configured, so leaving it alone when nothing is pinned was a way for audio
    work to escape the trust model entirely.
    """
    pydub = _pydub()
    monkeypatch.setenv("PATH", "")
    ffmpeg_utils.refresh()
    monkeypatch.setattr(ffmpeg_utils, "_pydub_configured", False)

    ffmpeg_utils.configure_pydub()

    assert pydub.AudioSegment.converter == ffmpeg_utils.UNVERIFIED_PYDUB_SENTINEL
    assert pydub.AudioSegment.ffprobe == ffmpeg_utils.UNVERIFIED_PYDUB_SENTINEL
    assert pydub.AudioSegment.converter not in ("ffmpeg", "avconv")


def test_pydub_is_never_pointed_at_an_unproved_discovered_pair(monkeypatch, tmp_path):
    pydub = _pydub()
    directory = install(tmp_path / "found")
    monkeypatch.setenv("PATH", str(directory))
    ffmpeg_utils.refresh()
    monkeypatch.setattr(ffmpeg_utils, "_pydub_configured", False)

    ffmpeg_utils.configure_pydub()

    assert pydub.AudioSegment.converter == ffmpeg_utils.UNVERIFIED_PYDUB_SENTINEL


def test_pinning_a_pair_later_replaces_the_sentinel(monkeypatch, tmp_path):
    """refresh() has to un-stick pydub, or the process keeps the old answer."""
    pydub = _pydub()
    monkeypatch.setenv("PATH", "")
    ffmpeg_utils.refresh()
    monkeypatch.setattr(ffmpeg_utils, "_pydub_configured", False)
    ffmpeg_utils.configure_pydub()
    assert pydub.AudioSegment.converter == ffmpeg_utils.UNVERIFIED_PYDUB_SENTINEL

    directory = install(tmp_path / "good")
    pin(monkeypatch, directory)          # pin() calls refresh()
    ffmpeg_utils.configure_pydub()

    assert Path(pydub.AudioSegment.converter).parent == directory


def test_the_unverified_sentinel_cannot_be_looked_up_on_path():
    """The sentinel must be an absolute path, not a command name.

    This is the cross-platform half of the pydub closure, and it is a property
    of *process creation*, not of pydub. ``subprocess`` — and the CreateProcess
    / ``execvp`` calls under it — treat an argv[0] containing no path separator
    as a **command name** and search PATH for it. Anything with a separator is
    a filesystem object and is opened directly.

    So a decorative token like ``"<no-verified-ffmpeg>"`` does not close the
    escape it was written to close. It is safe on Windows only by accident:
    ``<`` and ``>`` are illegal in NTFS filenames, so the lookup cannot match
    anything. On macOS and Linux they are ordinary filename characters, a PATH
    directory may legally hold an executable named exactly that, and pydub
    would run it — unverified PATH execution, which is precisely what this
    phase says is impossible.

    Asserted as the platform-independent property rather than by creating such
    a file, because the Windows development machine cannot represent the POSIX
    case and faking the filesystem would prove nothing about it.
    """
    sentinel = ffmpeg_utils.UNVERIFIED_PYDUB_SENTINEL

    assert os.path.isabs(sentinel), (
        f"{sentinel!r} is not absolute, so process creation would resolve it "
        "as a command name through PATH")
    assert os.path.dirname(sentinel), "no path component: still a bare token"
    assert sentinel not in ("ffmpeg", "ffprobe", "avconv", "avprobe")
    # The specific historical value, named so this cannot silently regress to it.
    assert sentinel != "<no-verified-ffmpeg>"


def test_the_unverified_sentinel_is_structurally_not_an_executable():
    """A directory, not a nonexistent file — the stronger of the two options.

    "Nothing will execute a directory" is a property of the operating system.
    "This file does not exist" is a property of the filesystem at one moment,
    which anyone can change by creating the file. The sentinel is this
    package's own directory: it necessarily exists, because the module under
    test was imported from it, and it necessarily is not an ffmpeg binary.
    """
    sentinel = Path(ffmpeg_utils.UNVERIFIED_PYDUB_SENTINEL)

    assert sentinel.is_dir(), "the fail-closed target must be a real directory"
    assert not sentinel.is_file()
    assert sentinel == Path(ffmpeg_utils.__file__).resolve().parent


def test_an_unverified_pydub_run_fails_without_searching_path(monkeypatch,
                                                              tmp_path):
    """End to end: what pydub is handed cannot become a PATH lookup.

    A real ffmpeg is planted on PATH so that a bare-name argv[0] *would*
    resolve to it. The assertion is that the value pydub receives is not a
    bare name at all, so the lookup never happens — and that actually trying to
    run it fails locally, at the fixed target, rather than executing anything.
    """
    pydub = _pydub()
    decoy = install(tmp_path / "decoy-on-path")
    monkeypatch.setenv("PATH", str(decoy))
    ffmpeg_utils.refresh()
    monkeypatch.setattr(ffmpeg_utils, "_pydub_configured", False)

    ffmpeg_utils.configure_pydub()

    converter = pydub.AudioSegment.converter
    assert os.path.isabs(converter)
    assert Path(converter).parent != decoy, "pydub picked up the PATH decoy"

    import subprocess
    with pytest.raises(OSError):
        subprocess.run([converter, "-version"], capture_output=True)


def test_the_prober_name_is_the_same_fail_closed_target(monkeypatch):
    """pydub probes through ``get_prober_name``; it must not be exempt."""
    pydub = _pydub()
    from pydub import utils as pydub_utils

    monkeypatch.setenv("PATH", "")
    ffmpeg_utils.refresh()
    monkeypatch.setattr(ffmpeg_utils, "_pydub_configured", False)

    ffmpeg_utils.configure_pydub()

    prober = pydub_utils.get_prober_name()
    assert prober == ffmpeg_utils.UNVERIFIED_PYDUB_SENTINEL
    assert os.path.isabs(prober)
    assert pydub.AudioSegment.ffprobe == prober


def test_pinning_replaces_the_fail_closed_target_everywhere(monkeypatch,
                                                            tmp_path):
    """The approved refresh behaviour, re-asserted across all four settings."""
    pydub = _pydub()
    from pydub import utils as pydub_utils

    monkeypatch.setenv("PATH", "")
    ffmpeg_utils.refresh()
    monkeypatch.setattr(ffmpeg_utils, "_pydub_configured", False)
    ffmpeg_utils.configure_pydub()
    assert pydub_utils.get_prober_name() == ffmpeg_utils.UNVERIFIED_PYDUB_SENTINEL

    directory = install(tmp_path / "good")
    pin(monkeypatch, directory)          # pin() calls refresh()
    ffmpeg_utils.configure_pydub()

    assert Path(pydub.AudioSegment.converter).parent == directory
    assert Path(pydub.AudioSegment.ffmpeg).parent == directory
    assert Path(pydub.AudioSegment.ffprobe).parent == directory
    assert Path(pydub_utils.get_prober_name()).parent == directory


# --------------------------------------------------------------------------- #
# D. Consumer gates
# --------------------------------------------------------------------------- #
def test_the_mp3_tool_gate_requires_a_proved_pair(monkeypatch, tmp_path):
    from mp3_tools import mp3_tool

    directory = install(tmp_path / "found")
    monkeypatch.setenv("PATH", str(directory))
    ffmpeg_utils.refresh()
    assert mp3_tool.ensure_ffmpeg_available() is False, \
        "a merely discovered pair authorised every FFmpeg-backed operation"

    pin(monkeypatch, directory)
    assert mp3_tool.ensure_ffmpeg_available() is True


def test_the_converter_gates_ask_for_verification():
    """Both gates, on the parsed tree rather than on source text."""
    source = (UNIVERSAL / "mp3_tools" / "m4b_converter.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    asked = {n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("have_ffmpeg", "verified_ffmpeg")}
    assert asked == {"verified_ffmpeg"}, asked


def test_the_mp3_tool_gate_asks_for_verification():
    source = (UNIVERSAL / "mp3_tools" / "mp3_tool.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    asked = {n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("have_ffmpeg", "verified_ffmpeg")}
    assert asked == {"verified_ffmpeg"}, asked


def test_no_production_consumer_still_gates_on_have_ffmpeg():
    """``have`` and ``verified`` now mean the same thing, but say what you mean."""
    offenders = []
    for path in UNIVERSAL.rglob("*.py"):
        if path.name in ("ffmpeg_utils.py", "ffmpeg_health.py"):
            continue
        if "have_ffmpeg(" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(UNIVERSAL))
    assert offenders == []


# --------------------------------------------------------------------------- #
# E. Nothing bypasses the shared authority
# --------------------------------------------------------------------------- #
def test_no_production_module_spawns_a_bare_ffmpeg_name():
    """The structural inventory: a future direct spawn cannot slip past.

    Every FFmpeg execution in the application goes through ``ffmpeg_cmd()`` or
    ``ffprobe_cmd()``, which resolve only the pinned pair. A literal ``"ffmpeg"``
    or ``"ffprobe"`` as the head of a command list would be a second, untrusted
    route, so it is refused here rather than discovered later.
    """
    offenders: list[str] = []
    for path in UNIVERSAL.rglob("*.py"):
        if path.name in ("ffmpeg_utils.py", "ffmpeg_health.py",
                         "ffmpeg_portable.py"):
            continue      # the authority itself, and the acquirer it feeds
        if path.name == "epub2tts_edge.py":
            # Vendored upstream code that writes bare-name command lists and
            # then routes every one of them through ``_run_ffmpeg``, which
            # rewrites argv[0] via the shared authority. Allowlisted here and
            # held in place by the companion test below -- being on this list is
            # not permission to spawn a bare name.
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.List) or not node.elts:
                continue
            head = node.elts[0]
            if isinstance(head, ast.Constant) and head.value in ("ffmpeg", "ffprobe"):
                offenders.append(f"{path.relative_to(UNIVERSAL)}:{head.lineno}")
    assert offenders == [], offenders


def test_every_ffmpeg_execution_resolves_through_the_shared_helpers():
    """Positive half: the consumers that do run FFmpeg ask the authority."""
    expected = {
        "mp3_tools/m4b_maker.py", "mp3_tools/m4b_probe.py",
        "mp3_tools/mp3_tool.py", "mp3_tools/m4b_converter.py",
        "shared/metadata.py", "tts/chatterbox_synth.py",
        "tts/epub2tts_edge/epub2tts_edge.py",
    }
    found = set()
    for path in UNIVERSAL.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "ffmpeg_cmd()" in text or "ffprobe_cmd()" in text:
            found.add(path.relative_to(UNIVERSAL).as_posix())
    assert expected <= found, expected - found


def test_the_command_helpers_are_the_only_path_resolution():
    """No consumer resolves a binary for itself."""
    offenders = []
    for path in UNIVERSAL.rglob("*.py"):
        # The setup layer legitimately *looks* for FFmpeg on PATH to decide
        # whether to install one. What it must never do is hand that answer to
        # a runtime execution, and it does not: it feeds ffmpeg_health.
        if path.name in ("ffmpeg_health.py", "ffmpeg_portable.py", "bootstrap.py"):
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ('shutil.which("ffmpeg")', 'shutil.which("ffprobe")'):
            if needle in text:
                offenders.append(f"{path.relative_to(UNIVERSAL)}: {needle}")
    assert offenders == []


# --------------------------------------------------------------------------- #
# F. Cache and refresh
# --------------------------------------------------------------------------- #
def test_a_newly_pinned_pair_becomes_available_after_refresh(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "")
    ffmpeg_utils.refresh()
    assert ffmpeg_utils.verified_ffmpeg() is False

    directory = install(tmp_path / "good")
    pin(monkeypatch, directory)

    assert Path(ffmpeg_utils.ffmpeg_path()).parent == directory


def test_an_invalidated_pin_does_not_fall_back_to_a_discovered_pair(
        monkeypatch, tmp_path):
    """The pinned binary changes; a PATH pair is still not an answer."""
    directory = install(tmp_path / "good")
    pin(monkeypatch, directory)
    assert ffmpeg_utils.verified_ffmpeg() is True

    # The pinned ffmpeg is replaced by something else entirely.
    (directory / f"ffmpeg{EXE}").write_text("a different binary", encoding="utf-8")
    os.utime(directory / f"ffmpeg{EXE}", ns=(0, 1))
    elsewhere = install(tmp_path / "elsewhere")
    monkeypatch.setenv("PATH", str(elsewhere))
    ffmpeg_utils.refresh()

    assert ffmpeg_utils.verified_ffmpeg() is False
    assert ffmpeg_utils.ffmpeg_path() is None
    assert ffmpeg_utils.discovered_ffmpeg() is True      # still observable
    with pytest.raises(ffmpeg_utils.FFmpegUnavailable):
        ffmpeg_utils.ffmpeg_cmd()


def test_refresh_clears_every_cached_answer(monkeypatch, tmp_path):
    directory = install(tmp_path / "good")
    pin(monkeypatch, directory)
    first = ffmpeg_utils.ffmpeg_path()

    replacement = install(tmp_path / "replacement")
    pin(monkeypatch, replacement)

    assert ffmpeg_utils.ffmpeg_path() != first
    assert Path(ffmpeg_utils.ffmpeg_path()).parent == replacement


# --------------------------------------------------------------------------- #
# G. No provisioning became reachable
# --------------------------------------------------------------------------- #
def test_no_consumer_can_provision_ffmpeg():
    """Phase 4 refuses; Phase 5 is what makes repair automatic."""
    offenders = []
    for path in UNIVERSAL.rglob("*.py"):
        if path.name in ("bootstrap.py", "ffmpeg_portable.py"):
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ("ffmpeg_portable.acquire", "ensure_ffmpeg(", "_install_ffmpeg("):
            if needle in text:
                offenders.append(f"{path.relative_to(UNIVERSAL)}: {needle}")
    assert offenders == []


def test_ffmpeg_utils_never_proves_or_pins_anything():
    """Consuming the pin is not the same job as establishing it."""
    text = Path(ffmpeg_utils.__file__).read_text(encoding="utf-8")
    for forbidden in ("establish(", "adopt_pair(", "prove_pair(", "ensure_ready("):
        assert forbidden not in text, forbidden


def test_the_vendored_edge_runner_rewrites_through_the_authority():
    """The allowlist above is only safe while this rewrite exists.

    ``epub2tts_edge`` is vendored upstream code that builds ``["ffmpeg", ...]``
    lists. Every one goes through ``_run_ffmpeg``, which replaces argv[0] with
    ``ffmpeg_cmd()`` -- so it inherits the fail-closed contract rather than
    escaping it. If that rewrite is ever removed, this fires.
    """
    path = UNIVERSAL / "tts" / "epub2tts_edge" / "epub2tts_edge.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    runner = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_run_ffmpeg")
    called = {n.func.attr for n in ast.walk(runner)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "ffmpeg_cmd" in called

    # And every spawn in the module goes through that runner, not subprocess.
    text = path.read_text(encoding="utf-8")
    body = text[text.index("DEFAULT_SPEAKER"):]
    assert "subprocess.run(" not in body
    assert "_run_ffmpeg(" in body


def test_the_edge_runner_refuses_when_nothing_is_pinned(monkeypatch, tmp_path):
    """Behavioural companion: the rewrite inherits the refusal."""
    monkeypatch.setenv("PATH", "")
    ffmpeg_utils.refresh()
    from tts.epub2tts_edge import epub2tts_edge

    with pytest.raises(ffmpeg_utils.FFmpegUnavailable):
        epub2tts_edge._run_ffmpeg(["ffmpeg", "-version"])
