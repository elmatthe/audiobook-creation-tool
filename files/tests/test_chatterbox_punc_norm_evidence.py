"""v0.6.5 Phase 5 — the pinned chatterbox-tts wheel's own colon normalization.

**Documents a found defect in a pinned third-party dependency; this is not
correctness and nothing here is fixed.** ``chatterbox.tts_turbo.punc_norm``
(called unconditionally, immediately before tokenization, inside
``ChatterboxTurboTTS.generate()`` — confirmed by reading the installed
0.1.7 wheel's source) performs a blanket ``text.replace(":", ",")`` with no
context awareness at all. This corrupts every structured colon our own text
ever contains before the model sees it: "6:45" becomes "6,45", "3:1" becomes
"3,1", and "https://example.com" becomes "https,//example.com" (destroying
the URL scheme separator entirely). An ordinary prose colon ("The pattern
held: two turns") also becomes a comma — that part is unremarkable, since a
comma is a reasonable rendering of a prose colon's pause.

This is a **different symptom** from the historical Phase 12 finding
recorded in ``chatterbox_synth.py``'s own comments ("a text-only fix is
impossible... the pause therefore has to come from assembly"). That
investigation was about recovering *pause duration* after a prose colon
(every spacing variant collapses to the same comma, so
``COLON_PAUSE_MS``/``split_at_prose_colon`` supply the pause at the assembly
level instead). This module is about *pronunciation correctness* for
structured digit:digit and URL-scheme colons, which ``split_at_prose_colon``
never touches (no whitespace follows those colons, so they reach
``generate()`` — and this same blanket replace — unprotected).

These tests only call the wheel's own pure ``punc_norm`` text function — no
model weights, no reference recording, no network, no GPU/CPU inference —
so they belong in the ordinary fast tracked suite like every other test
here. A v0.6.5 Phase 5 A/B experiment (evidence at
``files/dev-work/v0.6.5-phase5-chatterbox-colon-ab/``, gitignored) proved a
structural, non-word-specific candidate — a colon is a comma only when
followed by whitespace or end-of-string, otherwise left untouched — removes
this corruption for every digit:digit and ``://`` case tested, with zero
change to ordinary prose colons, and is not yet adopted into production.

If a future ``chatterbox-tts`` release changes this behavior, these tests
are expected to need updating — that would mean the upstream defect is
gone, not that this suite broke.
"""

from __future__ import annotations

import pytest

from chatterbox.tts_turbo import punc_norm

STRUCTURAL_COLON_CASES = [
    pytest.param("It was 6:45 when the ferry departed.", "6:45", "6,45", id="time-1"),
    pytest.param("The ferry would not arrive before 7:15.", "7:15", "7,15", id="time-2"),
    pytest.param("The ratio felt close to 3:1.", "3:1", "3,1", id="ratio"),
    pytest.param(
        "She had read the report at https://example.com/lighthouse-log before setting it aside.",
        "https://", "https,//", id="url-scheme",
    ),
]


@pytest.mark.parametrize("source_text,structured_form,corrupted_form", STRUCTURAL_COLON_CASES)
def test_the_pinned_wheel_currently_corrupts_structural_colons(
    source_text, structured_form, corrupted_form
):
    """**Found, not fixed.** Documents the exact corruption for each class the
    Phase 5 evidence covered — a digit:digit form and a URL scheme."""
    out = punc_norm(source_text)
    assert structured_form not in out, (
        f"{structured_form!r} unexpectedly survived punc_norm intact — "
        "the upstream defect may have been fixed; update this test if so")
    assert corrupted_form in out, (
        f"expected the known corruption {corrupted_form!r} in {out!r}")


def test_the_pinned_wheel_still_converts_an_ordinary_prose_colon_to_a_comma():
    """The one colon behavior that is NOT a defect — a prose colon reasonably
    becomes a comma, and production's own COLON_PAUSE_MS/split_at_prose_colon
    already compensate for the lost pause at the assembly level (unrelated to
    this module, unchanged by it)."""
    out = punc_norm("The pattern held: two full turns at the ordinary pace.")
    assert ":" not in out
    assert "held, two" in out


def test_the_call_site_normalizes_immediately_before_tokenization():
    """Confirms the exact adjacency this module's docstring describes, so a
    future wheel upgrade that reorders this is caught here rather than
    rediscovered by ear."""
    import inspect

    from chatterbox.tts_turbo import ChatterboxTurboTTS

    src = inspect.getsource(ChatterboxTurboTTS.generate)
    punc_norm_line = src.index("punc_norm(text)")
    tokenizer_line = src.index("self.tokenizer(text")
    between = src[punc_norm_line:tokenizer_line]
    # Only whitespace/the assignment itself between the two calls — nothing
    # else touches `text` in between.
    assert between.count("\n") <= 2, (
        "something now sits between punc_norm and tokenization; re-verify "
        "the adjacency this module's docstring depends on")
