"""v0.6.1 Plan 4 Phase 12 manual-feedback pass — Chatterbox tuning is explicit.

After listening to the whole 6m54s post-fix chapter the maintainer approved it and
asked for two very small things: slightly less exaggeration, and steadier
pronunciation of unusual proper nouns (``Ascended`` came out "as-ken-did";
``Tamar`` alternated between "Tay-Mar" and "Ta-Mar" within one chapter).

Before this pass every call site was a bare ``model.generate(text)``, so the
effective parameters lived only in the wheel and could not be seen, compared or
adjusted from this repository. That also made an important question hard to
answer: *did the Phase 9 evaluation and the audiobook path use the same
settings?* They did — both called ``generate`` with no keywords — and these tests
keep it that way, because a future divergence would invalidate the listening
approval the registry rests on.

What Turbo actually honours, read off ``chatterbox/tts_turbo.py`` in the pinned
wheel rather than from documentation:

* ``generate()`` **ignores** ``exaggeration``, ``cfg_weight`` and ``min_p``,
  logging *"CFG, min_p and exaggeration are not supported by Turbo version and
  will be ignored"*. They are not tuning knobs and must not be presented as such.
* ``prepare_conditionals(exaggeration=…)`` → ``T3Cond.emotion_adv`` looks like the
  surviving expressiveness control, **and it is not**. ``tts_turbo.py`` sets
  ``hp.emotion_adv = False``, so the conditioning encoder discards it; measured
  under a fixed seed, 0.5 vs 0.35 gave byte-identical audio. This line originally
  claimed the opposite and was corrected once the measurement disproved it.
* ``temperature`` is therefore the **only** working lever, and the one the
  maintainer tuned to 0.72.

**No pronunciation dictionary.** Hard-coding "Ascended" or "Tamar" is explicitly
out of scope; those observations are evidence about sampling stability, not
permission to special-case one audiobook. A guard below enforces that.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from tts import chatterbox_synth as cbx  # noqa: E402

SRC = Path(cbx.__file__).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# A. The settings are centralized and explicit
# --------------------------------------------------------------------------- #
def test_generation_parameters_are_declared_in_one_place():
    params = cbx.generation_params()
    assert set(params) == {"temperature", "top_p", "top_k", "repetition_penalty"}


def test_no_call_site_generates_without_the_shared_parameters():
    """A bare ``generate(text)`` anywhere would silently bypass the tuning."""
    tree = ast.parse(SRC)
    bare: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", None) != "generate":
            continue
        has_kwargs = any(kw.arg is None or kw.arg in cbx.generation_params()
                         for kw in node.keywords)
        if not has_kwargs:
            bare.append(node.lineno)
    assert not bare, f"generate() called without generation_params() at lines {bare}"


def test_every_synthesis_path_reaches_the_one_setting_set():
    """No synthesis entry point may invent its own parameters.

    Updated by the Phase 12 tuning pass: ``chatterbox_file_to_mp3`` now renders a
    chunk through ``_synthesize_chunk`` (which owns the prose-colon pause), so the
    parameters are reached one level down. The contract is unchanged — every path
    still ends at ``generation_params`` — and the helper is included here so that
    delegation cannot become a way to bypass it.
    """
    tree = ast.parse(SRC)
    targets = {"synthesize_text_to_wav", "synthesize_text_to_mp3",
               "_synthesize_chunk"}
    seen: dict[str, bool] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in targets:
            seen[node.name] = "generation_params" in ast.get_source_segment(SRC, node)
    assert seen == {name: True for name in targets}, seen

    audiobook = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                     and n.name == "chatterbox_file_to_mp3")
    called = {n.func.id for n in ast.walk(audiobook)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_synthesize_chunk" in called


# --------------------------------------------------------------------------- #
# B. The centralization changed no behaviour
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["top_p", "top_k", "repetition_penalty"])
def test_every_untuned_value_still_equals_the_pinned_wheels_own_default(name):
    """Everything the maintainer did NOT choose must still be the wheel's value.

    ``temperature`` is deliberately excluded and asserted separately below: the
    maintainer selected 0.72 on 2026-08-16, so it is now the one intentional
    divergence. Keeping the other three pinned to the wheel means a future pin
    bump still fails loudly here.
    """
    pytest.importorskip("chatterbox")
    assert cbx.generation_params()[name] == cbx.generation_defaults()[name]


def test_temperature_is_the_one_deliberate_divergence_from_the_wheel():
    pytest.importorskip("chatterbox")
    assert cbx.generation_params()["temperature"] == 0.72
    assert cbx.generation_defaults()["temperature"] == 0.8


def test_the_reference_exaggeration_matches_the_wheels_own_default():
    pytest.importorskip("chatterbox")
    from chatterbox.tts_turbo import ChatterboxTurboTTS

    default = inspect.signature(
        ChatterboxTurboTTS.prepare_conditionals).parameters["exaggeration"].default
    assert cbx.REFERENCE_EXAGGERATION == default


# --------------------------------------------------------------------------- #
# C. Parameters Turbo ignores are not offered as knobs
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("ignored", ["exaggeration", "cfg_weight", "min_p"])
def test_turbo_ignored_parameters_are_not_passed_to_generate(ignored):
    assert ignored not in cbx.generation_params()


def test_exaggeration_is_recorded_as_inert_on_turbo():
    """Corrected mid-pass, because the first assumption here was wrong.

    It is natural to assume the expressiveness control simply moved from
    ``generate()`` to ``prepare_conditionals(exaggeration=…)``. It did not:
    ``tts_turbo.py`` sets ``hp.emotion_adv = False``, so the conditioning encoder
    drops the value. Measured under a fixed seed, 0.5 vs 0.35 produced
    byte-identical audio. The engine must say so, or the next person will offer
    the maintainer a placebo knob.
    """
    block = SRC[SRC.index("# Generation tuning"):SRC.index("def generation_params")]
    assert "emotion_adv = False" in block
    assert "byte-identical" in block


def test_turbo_really_disables_emotion_adv_in_the_pinned_wheel():
    """Pins the upstream fact the comment above depends on."""
    pytest.importorskip("chatterbox")
    import chatterbox.tts_turbo as turbo

    src = Path(turbo.__file__).read_text(encoding="utf-8")
    assert "hp.emotion_adv = False" in src


def test_temperature_is_documented_as_the_only_working_lever():
    block = SRC[SRC.index("# Generation tuning"):SRC.index("GENERATION_TOP_P")]
    assert "only" in block.lower() and "temperature" in block.lower()


def test_a_future_exaggeration_change_is_flagged_against_the_cache_digest():
    """Guards the trap: the digest does not include exaggeration yet.

    A cached conditional built at the old value would be reused and the change
    would appear to do nothing. The note must stay next to the constant.
    """
    doc_block = SRC[SRC.index("GENERATION_REPETITION_PENALTY ="):
                    SRC.index("REFERENCE_EXAGGERATION =")]
    assert "identity_digest" in doc_block


# --------------------------------------------------------------------------- #
# D. No pronunciation dictionary — explicitly out of scope
# --------------------------------------------------------------------------- #
def test_no_hardcoded_pronunciation_substitutions_exist():
    """Strengthened: judge executable code, not the prose explaining the finding.

    The engine legitimately documents *why* the maintainer's ``Ascended``
    observation drove the temperature choice. What must never exist is a word rule
    in the running code, so the AST is checked with docstrings and comments gone.
    """
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and ast.get_docstring(node):
            node.body = node.body[1:]
    code = ast.unparse(tree).lower()
    for token in ("ascended", "tamar", "pronunciation_map", "pronunciations",
                  "phoneme_overrides", "lexicon"):
        assert token not in code, (
            f"{token!r} appears in executable engine code — this pass forbids "
            f"special-casing one audiobook's words")


def test_the_engine_does_not_rewrite_source_words_before_synthesis():
    """Only whitespace/structure handling is allowed between text and generate()."""
    tree = ast.parse(SRC)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "chatterbox_file_to_mp3")
    body = ast.get_source_segment(SRC, fn)
    assert ".replace(" not in body or "Title:" in body


# --------------------------------------------------------------------------- #
# E. The approved long-form fix is untouched by this pass
# --------------------------------------------------------------------------- #
def test_the_approved_chunk_ceiling_is_unchanged():
    assert cbx.CHATTERBOX_MAX_CHUNK_CHARS == 300


def test_the_chatterbox_splitter_is_still_the_one_in_use():
    tree = ast.parse(SRC)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "chatterbox_file_to_mp3")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "split_for_chatterbox" in called
    assert "split_into_chunks" not in called
