"""v0.6.5 Phase 6 — the structural-colon normalization candidate, integrated.

Phase 5 iteration 5 found that the pinned ``chatterbox-tts==0.1.7`` wheel's own
``chatterbox.tts_turbo.punc_norm()`` performs a blanket, context-blind
``text.replace(":", ",")`` before tokenization, corrupting every structured
colon this project's text ever contains ("6:45" -> "6,45", "3:1" -> "3,1",
"https://..." -> "https,//..."). A structural, non-word-specific candidate —
a colon becomes a comma only when it is a prose colon (followed by whitespace
or end-of-string); a structural colon is left untouched — was evaluated
across 3 matched seeds and **preferred by the maintainer on every seed**
(iteration 5 verdict, ``md-instructions/Decisions.md``, 2026-09-21). This
integrates that candidate as ``chatterbox_synth._structural_colon_punc_norm``,
applied by monkeypatching the pinned wheel's own module-level ``punc_norm`` at
model-load time — the installed wheel is never edited on disk, and there is
no supported extension point that would let production configure this any
other way.

These tests exercise only the pure text function and the patch-application
helper against a fake module — no model weights, no reference recording, no
network — so they belong in the ordinary fast tracked suite.
``test_chatterbox_punc_norm_evidence.py`` (unmodified by this file) continues
to document the raw, unpatched pinned wheel's own defect directly; this file
documents the production fix built on top of it.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from chatterbox.tts_turbo import punc_norm as real_punc_norm

from tts import chatterbox_synth as cbx


@pytest.fixture(autouse=True)
def _reset_colon_patch_flag(monkeypatch):
    """Every test starts as if the patch had never been applied in this
    process, so tests are order-independent regardless of what ran before."""
    monkeypatch.setattr(cbx, "_colon_patch_applied", False, raising=False)


STRUCTURAL_COLON_CASES = [
    pytest.param("It was 6:45 when the ferry departed.", "6:45", id="time-1"),
    pytest.param("The ferry would not arrive before 7:15.", "7:15", id="time-2"),
    pytest.param("The ratio felt close to 3:1.", "3:1", id="ratio"),
    pytest.param(
        "She had read the report at https://example.com/lighthouse-log before setting it aside.",
        "https://", id="url-scheme",
    ),
]


@pytest.mark.parametrize("source_text,structured_form", STRUCTURAL_COLON_CASES)
def test_the_candidate_preserves_every_structural_colon(source_text, structured_form):
    out = cbx._structural_colon_punc_norm(source_text)
    assert structured_form in out, (
        f"{structured_form!r} was corrupted by the structural-colon candidate: {out!r}")


def test_the_candidate_still_converts_an_ordinary_prose_colon_to_a_comma():
    """The one colon behavior that must NOT change — production's own
    COLON_PAUSE_MS/split_at_prose_colon already compensate for the pause lost
    at this exact comma, at the assembly level, unrelated to this patch."""
    out = cbx._structural_colon_punc_norm(
        "The pattern held: two full turns at the ordinary pace.")
    assert ":" not in out
    assert "held, two" in out


NON_COLON_PARITY_CASES = [
    pytest.param("hello there, no ending punctuation", id="lowercase-start-no-terminator"),
    pytest.param("An ellipsis trails off...", id="ellipsis"),
    pytest.param("An em—dash and an en–dash.", id="dashes"),
    pytest.param("Curly “quotes” and a ‘single’ pair.", id="curly-quotes"),
    pytest.param("Multiple   spaces   collapse.", id="whitespace-collapse"),
    pytest.param("", id="empty-string"),
]


@pytest.mark.parametrize("text", NON_COLON_PARITY_CASES)
def test_the_candidate_matches_the_real_wheel_when_there_is_no_colon(text):
    """Parity/drift guard: everything the candidate does OTHER than colon
    handling must stay byte-identical to the pinned wheel's own punc_norm. If
    a future chatterbox-tts pin changes this non-colon behavior, this test
    catches the drift rather than the candidate silently diverging further."""
    assert cbx._structural_colon_punc_norm(text) == real_punc_norm(text)


def test_the_patch_helper_replaces_punc_norm_on_the_given_module():
    fake_module = SimpleNamespace(punc_norm=lambda text: "UNPATCHED")
    cbx._ensure_structural_colon_patch(fake_module)
    assert fake_module.punc_norm is cbx._structural_colon_punc_norm


def test_the_patch_helper_is_idempotent():
    fake_module = SimpleNamespace(punc_norm=lambda text: "UNPATCHED")
    cbx._ensure_structural_colon_patch(fake_module)
    cbx._ensure_structural_colon_patch(fake_module)
    assert fake_module.punc_norm is cbx._structural_colon_punc_norm


def test_the_patch_helper_does_not_touch_a_second_unrelated_module():
    """Only the module object it is handed is mutated -- confirms this is a
    narrow, targeted seam, not a global search-and-replace."""
    fake_module = SimpleNamespace(punc_norm=lambda text: "UNPATCHED")
    other_module = SimpleNamespace(punc_norm=lambda text: "UNRELATED")
    cbx._ensure_structural_colon_patch(fake_module)
    assert other_module.punc_norm(None) == "UNRELATED"


def test_instantiate_model_applies_the_colon_patch_before_loading():
    """A static guard: the patch call sits inside _instantiate_model, so a
    future refactor cannot silently drop the wiring without this test
    failing (loading the real model is too heavy for the fast suite)."""
    src = Path(cbx.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    body = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "_instantiate_model")
    segment = ast.get_source_segment(src, body)
    assert "_ensure_structural_colon_patch" in segment
