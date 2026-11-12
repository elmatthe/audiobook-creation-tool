"""A message that tells the person to press a button names one they can see -- v0.7.2 Phase 5, ACT72-045.

The TTS panel's run button is labelled Start. Five messages -- the declined or failed Install & Continue, a source
changed during an install, the declined or failed sentence-data download, and the Edge engine's own "sentence data
missing" error -- told the person to "Press Create again", a button that does not exist (reproduced at ``fa9d3c3``).

The behaviour tests that open those paths assert the shown text (``test_qwen3_gui.py``, ``test_sentence_data.py``);
this one reads every string the application can show, so a new message cannot name a button nobody can find.
"""

from __future__ import annotations

import ast
import re

from source_probe import application_python_files, module

PRESS = re.compile(r"\b[Pp]ress (\w+) again\b")


def _strings(tree: ast.AST) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            found.append("".join(part.value for part in node.values
                                 if isinstance(part, ast.Constant) and isinstance(part.value, str)))
    return found


def _run_button_label() -> str:
    """The text of the button whose command is ``self.run_job``, read from the panel's source."""
    for node in ast.walk(module("tts/epub2tts_gui.py")):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "Button"):
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        command = keywords.get("command")
        if (isinstance(command, ast.Attribute) and command.attr == "run_job"
                and isinstance(keywords.get("text"), ast.Constant)):
            return keywords["text"].value
    raise AssertionError("the TTS panel has no button bound to run_job")


def test_every_press_again_message_names_the_run_button():
    label = _run_button_label()
    named: dict[str, set[str]] = {}
    for path in application_python_files():  # the one definition of the shipped source
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for text in _strings(tree):
            for match in PRESS.finditer(text):
                named.setdefault(match.group(1), set()).add(path.name)
            # The sentence-data message splits "Press" and the button name across two literals.
            if text.startswith("Create again") or "Press Create" in text:
                named.setdefault("Create", set()).add(path.name)
    assert named, "no message names a button to press again: this guard has lost its subject"
    assert set(named) == {label}, f"messages name a button other than {label!r}: {named}"
