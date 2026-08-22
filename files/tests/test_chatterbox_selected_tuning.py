"""v0.6.1 Plan 4 Phase 12 — the maintainer's final selected Chatterbox tuning.

After listening to the micro-gate package the maintainer chose, on 2026-08-16:

* **temperature 0.72** (candidate B) — *"best sounding one in my opinion"*.
  ``Ascended`` is pronounced correctly at this value.
* **prose-colon pause 75 ms** (candidate B), not 125 ms.

Both are pinned here so neither can drift back.

**Two things this file deliberately does NOT do.**

*It does not rewrite history.* The four approved Phase 9 listening WAVs were
produced at temperature **0.8**, and that is the contract ``--chatterbox-eval``
reproduces. Ordinary QA samples follow current production (0.72) so they describe
the engine as it actually is now. The split is asserted below, because collapsing
it would either invalidate the Phase 9 approval evidence or make the ordinary
samples lie about the shipped engine.

*It does not solve "Tamar".* The maintainer still hears "Ta-Mar" where they want
"Tay-mar". That is a **general pronunciation-override requirement**, recorded in
Handoff and deferred to its own designed feature. A guard below fails if anyone
tries to satisfy it by special-casing the word.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tts import chatterbox_synth as cbx  # noqa: E402

SRC = Path(cbx.__file__).read_text(encoding="utf-8")
SAMPLES_SRC = (Path(cbx.__file__).parent / "generate_voice_samples.py").read_text(
    encoding="utf-8")


# --------------------------------------------------------------------------- #
# A. The selected production temperature
# --------------------------------------------------------------------------- #
def test_production_temperature_is_the_selected_value():
    assert cbx.GENERATION_TEMPERATURE == 0.72


def test_generation_params_carries_the_selected_temperature():
    assert cbx.generation_params()["temperature"] == 0.72


def test_the_selected_temperature_is_declared_once():
    """No scattered 0.72 literals — one constant, one seam."""
    literals = [n.lineno for n in ast.walk(ast.parse(SRC))
                if isinstance(n, ast.Constant) and n.value == 0.72]
    assert len(literals) == 1, f"0.72 appears at lines {literals}; expected one"


@pytest.mark.parametrize("name,value", [
    ("top_p", 0.95), ("top_k", 1000), ("repetition_penalty", 1.2),
])
def test_every_other_generation_value_is_unchanged(name, value):
    assert cbx.generation_params()[name] == value


def test_the_reference_exaggeration_is_unchanged():
    assert cbx.REFERENCE_EXAGGERATION == 0.5


# --------------------------------------------------------------------------- #
# B. Phase 9 historical evidence is not rewritten
# --------------------------------------------------------------------------- #
def test_the_phase_nine_evaluation_temperature_is_recorded_separately():
    assert cbx.PHASE9_EVALUATION_TEMPERATURE == 0.8


def test_the_phase_nine_contract_differs_from_current_production():
    """If these ever collapse, one of the two records has become untrue."""
    assert cbx.phase9_evaluation_params()["temperature"] == 0.8
    assert cbx.generation_params()["temperature"] == 0.72
    assert cbx.phase9_evaluation_params() != cbx.generation_params()


def test_only_the_temperature_differs_between_the_two_contracts():
    current, historical = cbx.generation_params(), cbx.phase9_evaluation_params()
    differing = {k for k in current if current[k] != historical[k]}
    assert differing == {"temperature"}


def test_the_evaluation_command_uses_the_historical_parameters():
    tree = ast.parse(SAMPLES_SRC)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "run_chatterbox_evaluation")
    body = ast.get_source_segment(SAMPLES_SRC, fn)
    assert "phase9_evaluation_params" in body


def test_ordinary_samples_follow_current_production():
    """They must describe the engine as shipped, not the historical gate.

    ``main`` holds the ordinary per-voice sample loop; only
    ``run_chatterbox_evaluation`` may reach for the historical parameters.
    """
    tree = ast.parse(SAMPLES_SRC)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "main")
    body = ast.get_source_segment(SAMPLES_SRC, fn)
    assert "chatterbox_text_to_mp3" in body
    assert "phase9_evaluation_params" not in body


def test_the_engine_explains_why_the_two_differ():
    block = SRC[SRC.index("GENERATION_TEMPERATURE = 0.72"):
                SRC.index("PHASE9_EVALUATION_TEMPERATURE =")]
    assert "Phase 9" in block


# --------------------------------------------------------------------------- #
# C. The selected colon pause
# --------------------------------------------------------------------------- #
def test_the_colon_pause_is_the_selected_seventy_five_milliseconds():
    assert cbx.COLON_PAUSE_MS == 75


def test_the_rejected_pause_length_is_not_used():
    assert cbx.COLON_PAUSE_MS != 125


def test_a_prose_colon_is_split_for_the_pause():
    assert cbx.split_at_prose_colon("Chapter 3008: Beautiful Dream.") == [
        "Chapter 3008:", "Beautiful Dream."]


def test_the_colon_itself_is_never_deleted():
    parts = cbx.split_at_prose_colon("Chapter 3008: Beautiful Dream.")
    assert "".join(parts).count(":") == 1
    assert parts[0].endswith(":")


def test_no_text_is_lost_or_duplicated_across_a_colon_split():
    text = "Warning: the gate is closed. Note: it reopens at dawn."
    parts = cbx.split_at_prose_colon(text)
    assert "".join("".join(p.split()) for p in parts) == "".join(text.split())


def test_colon_split_ordering_is_exact():
    text = "One: two. Three: four. Five: six."
    parts = cbx.split_at_prose_colon(text)
    assert " ".join(parts) == text


def test_text_without_a_prose_colon_is_returned_whole():
    text = "There is no colon in this sentence at all."
    assert cbx.split_at_prose_colon(text) == [text]


def test_empty_segments_are_never_produced():
    assert all(p.strip() for p in cbx.split_at_prose_colon("A:   B: C."))


# --------------------------------------------------------------------------- #
# D. Non-prose colons must not gain a pause
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", [
    "The meeting is at 12:30 today.",
    "Visit https://example.com/x now.",
    "Ratio 3:1 applies.",
    "Timestamps 01:02:03 are common.",
    "See http://a.b/c and ftp://d.e/f.",
    "The score was 10:9 at half time.",
])
def test_non_prose_colon_constructs_are_left_alone(text):
    assert cbx.split_at_prose_colon(text) == [text]


def test_a_prose_colon_and_a_time_in_one_sentence_split_only_at_the_prose_one():
    text = "Reminder: the meeting is at 12:30 today."
    assert cbx.split_at_prose_colon(text) == [
        "Reminder:", "the meeting is at 12:30 today."]


# --------------------------------------------------------------------------- #
# E. Job semantics survive the pause
# --------------------------------------------------------------------------- #
@pytest.fixture
def synth_ready(monkeypatch, tmp_path):
    from test_chatterbox_engine import _StubConditionalsClass, _StubModel

    monkeypatch.setattr(cbx, "_runtime_root", lambda: tmp_path / "runtime-data")
    model = _StubModel()
    monkeypatch.setattr(cbx, "_get_model", lambda device=None: model)
    monkeypatch.setattr(cbx, "_conditionals_class", lambda: _StubConditionalsClass)
    monkeypatch.setattr(cbx, "load_conditionals",
                        lambda m, v, log=print, device=None: None)
    return model


def _source(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "source.txt"
    p.write_text(f"Title: T\nAuthor: A\n{text}\n", encoding="utf-8")
    return p


def test_a_colon_pause_does_not_inflate_the_progress_total(synth_ready, tmp_path):
    """The pause is inside a chunk. It must not invent extra work units."""
    text = "Warning: the gate is closed. " * 3
    seen: list[tuple[int, int]] = []
    cbx.chatterbox_file_to_mp3(
        str(_source(tmp_path, text)), str(tmp_path / "out.mp3"),
        "chatterbox-male-1", log=lambda _m: None,
        progress_callback=lambda d, t: seen.append((d, t)))
    expected = len(cbx.split_for_chatterbox(text.strip()))
    assert seen[0][1] == expected
    assert [d for d, _t in seen] == list(range(1, expected + 1))


def test_colon_segments_never_become_fake_source_files(synth_ready, tmp_path):
    text = "Warning: the gate is closed."
    cbx.chatterbox_file_to_mp3(
        str(_source(tmp_path, text)), str(tmp_path / "out.mp3"),
        "chatterbox-male-1", log=lambda _m: None)
    # One chunk, two colon segments -> two generate() calls, one progress unit.
    assert len(synth_ready.generated) == 2
    assert cbx.split_for_chatterbox(text) == [text]


def test_every_generated_segment_still_respects_the_ceiling(synth_ready, tmp_path):
    text = ("Warning: " + "the gate is closed and the road is long. " * 40)
    cbx.chatterbox_file_to_mp3(
        str(_source(tmp_path, text)), str(tmp_path / "out.mp3"),
        "chatterbox-male-1", log=lambda _m: None)
    assert max(len(t) for t in synth_ready.generated) <= cbx.CHATTERBOX_MAX_CHUNK_CHARS


def test_cancellation_still_stops_between_synthesis_units(synth_ready, tmp_path):
    from shared.cancellation import ConversionCancelled

    calls = {"n": 0}

    def cancel_after_two() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    text = "Alpha: one. " * 60
    with pytest.raises(ConversionCancelled):
        cbx.chatterbox_file_to_mp3(
            str(_source(tmp_path, text)), str(tmp_path / "out.mp3"),
            "chatterbox-male-1", log=lambda _m: None,
            cancel_check=cancel_after_two)
    assert synth_ready.generated, "cancellation fired before any work"


def test_the_whole_source_still_reaches_the_engine_in_order(synth_ready, tmp_path):
    text = " ".join(f"Marker{i}: value{i}." for i in range(60))
    cbx.chatterbox_file_to_mp3(
        str(_source(tmp_path, text)), str(tmp_path / "out.mp3"),
        "chatterbox-male-1", log=lambda _m: None)
    seen = [int(tok[len("Marker"):].rstrip(":"))
            for chunk in synth_ready.generated for tok in chunk.split()
            if tok.startswith("Marker")]
    assert seen == list(range(60))


# --------------------------------------------------------------------------- #
# F. Still no pronunciation hack
# --------------------------------------------------------------------------- #
def _engine_code_only() -> str:
    """The engine's executable surface: no comments, no docstrings.

    Prose *about* the maintainer's findings is documentation and belongs in the
    module; what must never exist is a word rule in the running code. Stripping
    comments and docstrings is what makes that distinction testable instead of
    banning the words outright.
    """
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and ast.get_docstring(node):
            node.body = node.body[1:]
    return ast.unparse(tree).lower()


def test_tamar_was_not_solved_by_special_casing_it():
    """The requirement is recorded in Handoff, not hard-coded in the engine."""
    code = _engine_code_only()
    for token in ("tamar", "tay-mar", "taymar", "ascended",
                  "pronunciation_map", "phoneme_overrides", "lexicon"):
        assert token not in code, (
            f"{token!r} appears in executable engine code — the pronunciation "
            f"requirement must stay a deferred general feature, not a word hack")


def test_the_pronunciation_requirement_is_still_documented_somewhere():
    """Deferring it must not mean losing it."""
    handoff = (Path(__file__).resolve().parent.parent.parent
               / "md-instructions" / "Handoff.md").read_text(encoding="utf-8")
    assert "Tay-mar" in handoff


def test_the_engine_does_not_carry_a_word_substitution_table():
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and node.keys:
            keys = [k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            assert not (len(keys) > 3 and all(k.isalpha() for k in keys)), (
                f"a word->word table appears at line {node.lineno}")
