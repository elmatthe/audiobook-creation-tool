"""v0.6.1 Plan 4 Phase 8 — the registry preservation gate and the phase boundary.

Phase 8 widens the ``BACKEND`` literal and adds an engine module. It adds **no**
voice and **no** GUI dispatch: registering voices is Phase 10's job, and producing
listening samples is Phase 9's. These tests fail if either arrives early.

The twelve existing ``VoiceEntry`` rows are asserted by value — every field of
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
    ("edge", "en-US-SteffanNeural", "Steffan — en-US Male (default)",
     "Microsoft Edge TTS — English (US)",
     {"sentencepause": "800", "paragraphpause": "850", "title_ms": "1200",
      "chapter_ms": "2000", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": True, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("edge", "en-US-AndrewMultilingualNeural", "Andrew Multilingual — en-US Male",
     "Microsoft Edge TTS — English (US)",
     {"sentencepause": "820", "paragraphpause": "870", "title_ms": "1200",
      "chapter_ms": "2000", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": True, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("edge", "en-US-AndrewNeural", "Andrew — en-US Male",
     "Microsoft Edge TTS — English (US)",
     {"sentencepause": "820", "paragraphpause": "870", "title_ms": "1200",
      "chapter_ms": "2000", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": True, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("edge", "en-US-AriaNeural", "Aria — en-US Female",
     "Microsoft Edge TTS — English (US)",
     {"sentencepause": "780", "paragraphpause": "830", "title_ms": "1200",
      "chapter_ms": "2000", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": True, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("edge", "en-US-AvaMultilingualNeural", "Ava Multilingual — en-US Female",
     "Microsoft Edge TTS — English (US)",
     {"sentencepause": "780", "paragraphpause": "830", "title_ms": "1200",
      "chapter_ms": "2000", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": True, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("edge", "en-US-AvaNeural", "Ava — en-US Female",
     "Microsoft Edge TTS — English (US)",
     {"sentencepause": "780", "paragraphpause": "830", "title_ms": "1200",
      "chapter_ms": "2000", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": True, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("edge", "en-US-JennyNeural", "Jenny — en-US Female",
     "Microsoft Edge TTS — English (US)",
     {"sentencepause": "750", "paragraphpause": "800", "title_ms": "1200",
      "chapter_ms": "2000", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": True, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("kokoro", "af_heart", "Heart (af_heart) — US Female (Kokoro default)",
     "Kokoro Local AI — American English",
     {"sentencepause": "600", "paragraphpause": "700", "title_ms": "1000",
      "chapter_ms": "1800", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": False, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("kokoro", "af_bella", "Bella (af_bella) — US Female",
     "Kokoro Local AI — American English",
     {"sentencepause": "620", "paragraphpause": "700", "title_ms": "1000",
      "chapter_ms": "1800", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": False, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("kokoro", "am_michael", "Michael (am_michael) — US Male",
     "Kokoro Local AI — American English",
     {"sentencepause": "580", "paragraphpause": "700", "title_ms": "1000",
      "chapter_ms": "1800", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": False, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("kokoro", "bf_emma", "Emma (bf_emma) — British Female",
     "Kokoro Local AI — British English",
     {"sentencepause": "640", "paragraphpause": "700", "title_ms": "1000",
      "chapter_ms": "1800", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": False, "rate": "+0%", "kokoro_speed": "1.0"}),
    ("kokoro", "bm_george", "George (bm_george) — British Male",
     "Kokoro Local AI — British English",
     {"sentencepause": "600", "paragraphpause": "700", "title_ms": "1000",
      "chapter_ms": "1800", "end_pause": "3000", "trim_dbfs": "-58",
      "trim_edge_chunks": False, "rate": "+0%", "kokoro_speed": "1.0"}),
]


def test_the_registry_still_holds_exactly_twelve_voices():
    assert len(voice_registry.VOICES) == 12


@pytest.mark.parametrize("index,expected", list(enumerate(EXPECTED_VOICES)))
def test_each_existing_voice_row_survives_phase_eight_byte_for_byte(index, expected):
    backend, voice_id, display, group, preset = expected
    entry = voice_registry.VOICES[index]
    assert entry.backend == backend
    assert entry.voice_id == voice_id
    assert entry.display_label == display
    assert entry.group_label == group
    assert entry.timing_preset == preset


def test_the_default_voice_is_still_steffan():
    assert voice_registry.DEFAULT_VOICE_LABEL == "Steffan — en-US Male (default)"
    assert voice_registry.DEFAULT_VOICE_LABEL == voice_registry.VOICES[0].display_label


def test_the_dropdown_offers_the_same_twelve_labels_in_the_same_order():
    assert voice_registry.display_labels() == [v[2] for v in EXPECTED_VOICES]


def test_no_chatterbox_voice_is_registered_in_phase_eight():
    assert [v for v in voice_registry.VOICES if v.backend == "chatterbox"] == []


def test_no_chatterbox_voice_is_reachable_through_the_lookup():
    for label in ("Chatterbox — Female 1", "Chatterbox — Female 2",
                  "Chatterbox — Male 1", "Chatterbox — Male 2"):
        assert voice_registry.get_voice(label) is None


def test_the_registry_declares_no_voice_entry_for_chatterbox_in_source():
    """Belt and braces: an AST check, so a commented-out row cannot creep back."""
    tree = _tree(TTS_DIR / "voice_registry.py")
    rows = [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "VoiceEntry"]
    assert len(rows) == 12
    for row in rows:
        backend = next(k.value for k in row.keywords if k.arg == "backend")
        assert backend.value in ("edge", "kokoro")


# --------------------------------------------------------------------------- #
# The phase boundary — Phase 9 and Phase 10 have not started
# --------------------------------------------------------------------------- #
UNTOUCHED_BY_PHASE_EIGHT = [
    "epub2tts_gui.py",
    "generate_voice_samples.py",
    "batch_convert.py",
    "kokoro_synth.py",
    "pdf_extractor.py",
]


@pytest.mark.parametrize("filename", UNTOUCHED_BY_PHASE_EIGHT)
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
        f"{filename} imports the Chatterbox engine — that is Phase 10"


@pytest.mark.parametrize("filename", UNTOUCHED_BY_PHASE_EIGHT)
def test_no_existing_tts_module_names_a_chatterbox_symbol(filename):
    tree = _tree(TTS_DIR / filename)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.value for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not any("chatterbox" in str(n).lower() for n in names), \
        f"{filename} references Chatterbox — that is Phase 9/10"


def test_the_phase_nine_evaluation_folder_was_not_created():
    assert not (REPO_ROOT / "files" / "test-for-manual-listen-elmatthe"
                / "chatterbox-eval").exists()


def test_the_sample_generator_still_covers_only_the_registered_voices():
    tree = _tree(TTS_DIR / "generate_voice_samples.py")
    strings = {n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not any("chatterbox" in s.lower() for s in strings)


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
