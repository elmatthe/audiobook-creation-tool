"""v0.6.1 Plan 4 — the registry preservation gate and the phase boundary.

Phase 8 widened the ``BACKEND`` literal and added an engine module. Phase 9 added
the listening-evaluation mode to ``generate_voice_samples.py``. Phase 10 — after
the maintainer listened to all four evaluation outputs on 2026-08-15 and approved
every one of them — registered the four approved rows and taught the TTS panel a
three-way backend dispatch.

**The boundary these tests draw now sits after Phase 10.** Two guards were
retargeted rather than deleted, and the distinction matters:

* the registry is no longer asserted to hold *twelve* rows, because four approved
  rows were legitimately appended. What survives, and is asserted here in more
  detail than before, is that **the original twelve are untouched** — every field
  of every row, in the original order, as the first twelve of sixteen;
* ``epub2tts_gui.py`` left the "no Chatterbox may appear here" list, because
  integrating the approved voices into the one unified queue is precisely what
  Phase 10 was authorized to do. The four modules still on that list —
  ``epub2tts_edge/runner.py``, ``batch_convert.py``, ``kokoro_synth.py`` and
  ``pdf_extractor.py`` — are the ones adding a third engine must **not** have
  touched, and they remain guarded.

The panel-side contract that replaced the retired guard is asserted in full by
``test_chatterbox_integration.py``; nothing was dropped without a stronger
replacement.

The **Phase 10 remediation** retargeted a third guard for the same reason. The
sample generator's ordinary mode used to be asserted free of the word
``chatterbox`` entirely — a claim that was only true while no Chatterbox voice was
registered. It now dispatches on ``VoiceEntry.backend`` like the panel does, so
that assertion was replaced by two: one proving the Phase 9 *listening evaluation*
is still reachable only behind ``--chatterbox-eval``, and one proving ordinary mode
really does branch on the backend rather than treating "not Kokoro" as Edge.

The twelve pre-existing ``VoiceEntry`` rows are asserted by value — every field of
every row — because a count check would pass a silently edited preset.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tts import voice_registry  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TTS_DIR = REPO_ROOT / "scripts" / "Universal" / "tts"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


# --------------------------------------------------------------------------- #
# The backend literal is widened — and only widened
# --------------------------------------------------------------------------- #
def test_the_backend_literal_now_admits_chatterbox():
    import typing

    assert set(typing.get_args(voice_registry.BACKEND)) == {"edge", "kokoro", "chatterbox"}


def test_a_chatterbox_preset_helper_exists_beside_the_other_two():
    assert callable(voice_registry._chatterbox_preset)
    assert callable(voice_registry._edge_preset)
    assert callable(voice_registry._kokoro_preset)


def test_the_chatterbox_preset_carries_the_same_gui_field_names():
    preset = voice_registry._chatterbox_preset()
    reference = voice_registry._kokoro_preset()
    assert set(preset) == set(reference)


def test_the_chatterbox_preset_disables_edge_chunk_trimming():
    """Trimming is an Edge-only artefact fix; local engines must not inherit it."""
    assert voice_registry._chatterbox_preset()["trim_edge_chunks"] is False


# --------------------------------------------------------------------------- #
# The twelve existing rows, asserted by value
# --------------------------------------------------------------------------- #
EXPECTED_VOICES = [
    ("edge", "en-US-SteffanNeural", "Edge Male - Steffan (en-US)",
     "Microsoft Edge TTS — English (US)",
     {"sentencepause": "800", "paragraphpause": "850", "title_ms": "1200",
      "chapter_ms": "2000", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": True, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("edge", "en-US-AndrewMultilingualNeural", "Edge Male - Andrew (en-Multilingual)",
     "Microsoft Edge TTS — English (US)",
     {"sentencepause": "820", "paragraphpause": "870", "title_ms": "1200",
      "chapter_ms": "2000", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": True, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("edge", "en-US-AndrewNeural", "Edge Male - Andrew (en-US)",
     "Microsoft Edge TTS — English (US)",
     {"sentencepause": "820", "paragraphpause": "870", "title_ms": "1200",
      "chapter_ms": "2000", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": True, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("edge", "en-US-AriaNeural", "Edge Female - Aria (en-US)",
     "Microsoft Edge TTS — English (US)",
     {"sentencepause": "780", "paragraphpause": "830", "title_ms": "1200",
      "chapter_ms": "2000", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": True, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("edge", "en-US-AvaMultilingualNeural", "Edge Female - Ava (en-Multilingual)",
     "Microsoft Edge TTS — English (US)",
     {"sentencepause": "780", "paragraphpause": "830", "title_ms": "1200",
      "chapter_ms": "2000", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": True, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("edge", "en-US-AvaNeural", "Edge Female - Ava (en-US)",
     "Microsoft Edge TTS — English (US)",
     {"sentencepause": "780", "paragraphpause": "830", "title_ms": "1200",
      "chapter_ms": "2000", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": True, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("edge", "en-US-JennyNeural", "Edge Female - Jenny (en-US)",
     "Microsoft Edge TTS — English (US)",
     {"sentencepause": "750", "paragraphpause": "800", "title_ms": "1200",
      "chapter_ms": "2000", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": True, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("kokoro", "af_heart", "Kokoro Female (Default) - Heart (en-US)",
     "Kokoro Local AI — American English",
     {"sentencepause": "600", "paragraphpause": "700", "title_ms": "1000",
      "chapter_ms": "1800", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": False, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("kokoro", "af_bella", "Kokoro Female - Bella (en-US)",
     "Kokoro Local AI — American English",
     {"sentencepause": "620", "paragraphpause": "700", "title_ms": "1000",
      "chapter_ms": "1800", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": False, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("kokoro", "am_michael", "Kokoro Male - Michael (en-US)",
     "Kokoro Local AI — American English",
     {"sentencepause": "580", "paragraphpause": "700", "title_ms": "1000",
      "chapter_ms": "1800", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": False, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("kokoro", "bf_emma", "Kokoro Female - Emma (en-UK)",
     "Kokoro Local AI — British English",
     {"sentencepause": "640", "paragraphpause": "700", "title_ms": "1000",
      "chapter_ms": "1800", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": False, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("kokoro", "bm_george", "Kokoro Male - George (en-UK)",
     "Kokoro Local AI — British English",
     {"sentencepause": "600", "paragraphpause": "700", "title_ms": "1000",
      "chapter_ms": "1800", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": False, "rate": "+0%", "kokoro_speed": "1.0"}),
]


def test_the_twelve_pre_existing_rows_are_still_the_first_twelve():
    """Phase 10 appended; it did not insert, re-order or replace."""
    assert len(voice_registry.VOICES) == 16
    assert len([v for v in voice_registry.VOICES[:12]
                if v.backend in ("edge", "kokoro")]) == 12


@pytest.mark.parametrize("index,expected", list(enumerate(EXPECTED_VOICES)))
def test_each_existing_voice_row_keeps_its_engine_identity_and_timing(index, expected):
    """Everything the engines read is still exactly what Phase 8 froze.

    The ``display_label`` column carries the wording the maintainer specified in
    Phase 13A.3, which explicitly supersedes the drop's byte-identical-label
    constraint. That is the *only* column the rename was allowed to touch, so the
    backend, the voice id, the group and the whole timing preset are still
    asserted here value for value.
    """
    backend, voice_id, display, group, preset = expected
    entry = voice_registry.VOICES[index]
    assert entry.backend == backend
    assert entry.voice_id == voice_id
    assert entry.display_label == display
    assert entry.group_label == group
    assert entry.timing_preset == preset


def test_the_default_voice_is_still_steffan():
    assert voice_registry.DEFAULT_VOICE_LABEL == "Edge Male - Steffan (en-US)"
    assert voice_registry.DEFAULT_VOICE_LABEL == voice_registry.VOICES[0].display_label


def test_the_dropdown_still_opens_with_the_same_twelve_labels_in_order():
    assert voice_registry.display_labels()[:12] == [v[2] for v in EXPECTED_VOICES]


def test_exactly_four_chatterbox_rows_exist_and_all_sit_after_the_twelve():
    """The set is closed at four (drop §5.7) and none of them displaced a row."""
    chatterbox = [v for v in voice_registry.VOICES if v.backend == "chatterbox"]
    assert len(chatterbox) == 4
    assert voice_registry.VOICES[12:] == chatterbox


def test_the_em_dash_labels_this_drop_proposed_are_not_what_was_registered():
    """§5.7 proposed em dashes; the maintainer approved ASCII hyphens instead."""
    for label in ("Chatterbox — Female 1", "Chatterbox — Female 2",
                  "Chatterbox — Male 1", "Chatterbox — Male 2"):
        assert voice_registry.get_voice(label) is None


def test_the_registry_source_declares_exactly_the_rows_it_should():
    """Belt and braces: an AST check, so a stray or duplicated row cannot creep in."""
    tree = _tree(TTS_DIR / "voice_registry.py")
    rows = [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "VoiceEntry"]
    assert len(rows) == 16
    backends = [next(k.value.value for k in row.keywords if k.arg == "backend")
                for row in rows]
    assert backends[:12] == ["edge"] * 7 + ["kokoro"] * 5
    assert backends[12:] == ["chatterbox"] * 4


# --------------------------------------------------------------------------- #
# The phase boundary — the engines themselves were never edited
# --------------------------------------------------------------------------- #
#
# ``epub2tts_gui.py`` left this list at Phase 10, which was authorized to add the
# GUI dispatch. Everything else here is an engine or an engine's runner: adding a
# third backend must not have reached into any of them, and that is still true.
UNTOUCHED_BY_CHATTERBOX = [
    "epub2tts_edge/runner.py",
    "batch_convert.py",
    "kokoro_synth.py",
    "pdf_extractor.py",
]


@pytest.mark.parametrize("filename", UNTOUCHED_BY_CHATTERBOX)
def test_no_chatterbox_dispatch_was_added_to_an_existing_tts_module(filename):
    tree = _tree(TTS_DIR / filename)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module}.{a.name}" for a in node.names)
    assert not any("chatterbox" in name for name in imported), \
        f"{filename} imports the Chatterbox engine — engines stay untouched"


@pytest.mark.parametrize("filename", UNTOUCHED_BY_CHATTERBOX)
def test_no_existing_tts_module_names_a_chatterbox_symbol(filename):
    tree = _tree(TTS_DIR / filename)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.value for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not any("chatterbox" in str(n).lower() for n in names), \
        f"{filename} references Chatterbox — engines stay untouched"


def test_the_phase_nine_evaluation_folder_stays_out_of_the_repository():
    """Phase 9 creates it locally; git must never see it or anything inside it."""
    import subprocess

    eval_dir = (REPO_ROOT / "files" / "test-for-manual-listen-elmatthe"
                / "chatterbox-eval")
    checked = subprocess.run(
        ["git", "check-ignore", "-q", str(eval_dir / "chatterbox-female-1.wav")],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert checked.returncode == 0, "the evaluation folder is not gitignored"


def _sample_generator_main() -> tuple[str, ast.FunctionDef]:
    src = (TTS_DIR / "generate_voice_samples.py").read_text(encoding="utf-8")
    tree = _tree(TTS_DIR / "generate_voice_samples.py")
    main = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    return src, main


def _sample_generator_main_split() -> tuple[str, str]:
    """``main()`` cut in two: the ``--chatterbox-eval`` branch, and everything else."""
    src, main = _sample_generator_main()
    gated = [branch for branch in ast.walk(main)
             if isinstance(branch, ast.If)
             and "chatterbox_eval" in ast.get_source_segment(src, branch.test)]
    assert len(gated) == 1, "the Chatterbox evaluation is not gated behind its flag"
    inside = ast.get_source_segment(src, gated[0])
    outside = ast.get_source_segment(src, main).replace(inside, "")
    return inside, outside


def test_the_listening_evaluation_reaches_chatterbox_only_behind_its_own_flag():
    """Phase 9's *evaluation* is opt-in: an ordinary sample refresh must not run it.

    **Migrated by the Phase 10 remediation, not weakened.** This guard used to
    assert the far broader "the word ``chatterbox`` appears nowhere in ``main()``
    outside the flag branch". That was true only while no Chatterbox voice was
    registered. Phase 10 registered four, so ordinary mode must now reach the
    Chatterbox *engine* — while the four-WAV listening evaluation stays exactly as
    isolated as it was. The replacement therefore names the evaluation's own
    symbols instead of the engine's, and is paired with the positive test below,
    which proves ordinary mode really does dispatch on the backend. Behavioural
    proof of both halves lives in ``test_chatterbox_evaluation.py`` section R.
    """
    inside, outside = _sample_generator_main_split()

    assert "run_chatterbox_evaluation" in inside
    for evaluation_only in ("run_chatterbox_evaluation",
                            "_report_chatterbox_evaluation",
                            "CHATTERBOX_EVAL_TEXT",
                            "CHATTERBOX_EVAL_VOICE_IDS",
                            "CHATTERBOX_EVAL_SUBDIR",
                            "_chatterbox_eval_dir",
                            "synthesize_text_to_wav",
                            ".wav"):
        assert evaluation_only not in outside, (
            f"ordinary sample generation reaches {evaluation_only!r} — the Phase 9 "
            "listening evaluation must stay behind --chatterbox-eval")


def test_ordinary_sample_generation_dispatches_on_the_voice_row_backend():
    """The replacement for the half of the old guard that went stale.

    The regression the remediation fixed was structural: "kokoro -> Kokoro,
    everything else -> Edge" silently reclassified the four newly registered
    Chatterbox rows as Edge. Every branch must compare ``VoiceEntry.backend``
    against a named backend, so there is no "everything else" to fall into.
    """
    _src, main = _sample_generator_main()

    compared: list[str] = []
    for node in ast.walk(main):
        if not isinstance(node, ast.Compare):
            continue
        left = node.left
        if not (isinstance(left, ast.Attribute) and left.attr == "backend"):
            continue
        compared.extend(c.value for c in node.comparators
                        if isinstance(c, ast.Constant) and isinstance(c.value, str))

    assert set(compared) == {"edge", "kokoro", "chatterbox"}, (
        "ordinary sample dispatch does not test all three backends by name")

    _inside, outside = _sample_generator_main_split()
    assert "chatterbox_synth" in outside, (
        "the ordinary Chatterbox branch does not reach the engine module")
    assert "edge_tts" in outside and "kokoro_synth" in outside


def test_the_ordinary_chatterbox_branch_is_not_the_edge_branch():
    """A Chatterbox voice_id posted to the Edge service is exactly the old bug."""
    src, main = _sample_generator_main()

    edge_calls = [n for n in ast.walk(main) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "Communicate"]
    assert len(edge_calls) == 1, "the Edge sample call is no longer a single seam"

    # An if/elif chain nests, so several ``If`` nodes contain the call; the one
    # that actually guards it is the innermost, i.e. the smallest subtree.
    enclosing = [n for n in ast.walk(main) if isinstance(n, ast.If)
                 and edge_calls[0] in list(ast.walk(n))]
    branch = min(enclosing, key=lambda n: len(list(ast.walk(n))))
    assert isinstance(branch.test, ast.Compare)
    assert isinstance(branch.test.left, ast.Attribute)
    assert branch.test.left.attr == "backend"
    assert [c.value for c in branch.test.comparators] == ["edge"], (
        "the Edge sample branch is not guarded by backend == 'edge'")
    assert "chatterbox" not in ast.get_source_segment(src, branch).lower()


# --------------------------------------------------------------------------- #
# Protected local assets are never tracked
# --------------------------------------------------------------------------- #
def test_the_protected_uploads_folder_is_ignored():
    ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "files/Chatterbox-Voice-Uploads/" in ignore


def test_the_runtime_data_tree_holding_derivatives_is_ignored():
    ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "files/runtime-data/" in ignore


def test_no_reference_audio_is_tracked_anywhere_in_the_repository():
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "files/Chatterbox-Voice-Uploads/", "files/runtime-data/"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert tracked.stdout.strip() == ""
