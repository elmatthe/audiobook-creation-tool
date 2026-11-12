"""What setup says about FFmpeg matches what setup does (v0.7.2 Phase 8, ACT72-040).

``repair_venv``'s docstring and the ``--repair-venv`` help said the launch path never installs FFmpeg. That was true
until PRE-PLAN-6 made every launch repair it, and the two sentences went on saying it. Nothing read them, so nothing
noticed.

Each statement is tied here to the code it describes, read from the parsed source, so the words and the behaviour have
to move together: change what a repair run does about FFmpeg and the structural half fails; change the words back and
the text half fails.
"""

from __future__ import annotations

import ast
import re

import pytest

from shared import bootstrap

import source_probe

BOOTSTRAP = "shared/bootstrap.py"
#: Every way the code can install or repair the audio tools.
PROVISIONING = ("repair_ffmpeg", "_install_ffmpeg", "_download_portable_ffmpeg_windows", "acquire")
#: The claim that was false: that a launch (or a repair run, which ends in one) never installs FFmpeg.
NEVER_INSTALLS = re.compile(r"never\s+install", re.IGNORECASE)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _help(capsys) -> dict[str, str]:
    """The real ``--help`` of the real parser, as argparse prints it, split by option."""
    with pytest.raises(SystemExit) as stopped:
        bootstrap.main(["--help"])
    assert stopped.value.code == 0
    printed = capsys.readouterr().out
    options: dict[str, str] = {}
    current = None
    for line in printed.splitlines():
        found = re.match(r"\s{2}(--[a-z-]+)\b(.*)", line)
        if found:
            current = found.group(1)
            options[current] = found.group(2)
        elif current is not None and line.startswith(" "):
            options[current] += " " + line
    return {name: _flat(text) for name, text in options.items()}


def test_the_rebuild_itself_never_touches_ffmpeg_and_the_launch_after_it_repairs_it():
    """The behaviour the words below describe, from the call graph."""
    for target in PROVISIONING + ("ensure_ffmpeg", "ensure_ffmpeg_ready_for_launch"):
        assert not source_probe.reaches(BOOTSTRAP, "repair_venv", target), f"repair_venv reaches {target}"
    assert source_probe.reaches(BOOTSTRAP, "_repair_and_launch", "repair_venv")
    assert source_probe.reaches(BOOTSTRAP, "_repair_and_launch", "ensure_ffmpeg_ready_for_launch")
    assert source_probe.reaches(BOOTSTRAP, "_repair_and_launch", "repair_ffmpeg"), \
        "a repair run no longer ends in a launch that repairs FFmpeg: the help and the docstring must be rewritten"
    assert source_probe.reaches(BOOTSTRAP, "_launch_with_kokoro_healthcheck", "repair_ffmpeg")
    main = source_probe.function(BOOTSTRAP, "main")
    routed = [node for node in ast.walk(main) if isinstance(node, ast.If)
              and isinstance(node.test, ast.Attribute) and node.test.attr == "repair_venv"]
    assert len(routed) == 1 and source_probe.calls(routed[0]) >= {"_repair_and_launch"}, \
        "--repair-venv is no longer what runs _repair_and_launch"


def test_the_repair_venv_help_says_the_launch_that_follows_repairs_ffmpeg(capsys):
    text = _help(capsys)["--repair-venv"]
    assert not NEVER_INSTALLS.search(text), text
    assert "FFmpeg" in text and "repairs it" in text, text
    assert "launch that follows" in text, text
    assert "touches only the Python environment" in text, "and it still says what the rebuild itself is limited to"
    assert "base interpreter" in text, text


def test_the_launch_only_help_still_names_ffmpeg_among_what_a_launch_repairs(capsys):
    text = _help(capsys)["--launch-only"]
    assert "FFmpeg" in text and "repair" in text, text


def test_no_setup_option_claims_that_ffmpeg_is_never_installed(capsys):
    """True of every option, so a new one cannot bring the sentence back."""
    for name, text in _help(capsys).items():
        if "ffmpeg" in text.lower():
            assert not NEVER_INSTALLS.search(text), (name, text)


def test_the_repair_venv_docstring_no_longer_says_a_launch_never_installs_ffmpeg():
    text = _flat(bootstrap.repair_venv.__doc__)
    assert "still never installs" not in text
    assert "never looks at FFmpeg" in text, "what this function itself does not do"
    assert "installs or repairs them" in text and "ensure_ffmpeg_ready_for_launch" in text, \
        "and what the launch after it does"


def test_the_launchers_describe_a_repair_as_environment_repair_then_launch():
    """The two launcher scripts say what a repair run is without saying anything about FFmpeg that could go stale."""
    for name in ("Setup_and_Run-audiobook-creation-tool.bat", "Setup_and_Run-audiobook-creation-tool.command"):
        text = (source_probe.REPO_ROOT / name).read_text(encoding="utf-8")
        assert "--repair-venv" in text, name
        for line in text.splitlines():
            if "ffmpeg" in line.lower():
                assert not NEVER_INSTALLS.search(line), (name, line)
