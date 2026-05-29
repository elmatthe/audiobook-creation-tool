"""
voice_registry.py — Central registry of all supported TTS voices for epub2tts-edge v1.1.

Each entry defines:
  - backend:        "edge" | "kokoro"
  - voice_id:       The voice identifier passed to the TTS engine
  - display_label:  Short human-readable name shown in the GUI dropdown
  - group_label:    Category header shown in the dropdown (cosmetic only)
  - timing_preset:  Dict of GUI timing field values to apply when voice is selected.
                    Keys match the tkinter StringVar names in epub2tts_gui.py.
                    For edge voices: sentencepause, paragraphpause, title_ms, chapter_ms,
                                     end_pause, trim_dbfs, trim_edge_chunks, rate.
                    For kokoro voices: speed (float str), sentencepause, paragraphpause,
                                       title_ms, chapter_ms, end_pause.
                    trim_edge_chunks is always False for kokoro.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BACKEND = Literal["edge", "kokoro"]


@dataclass(frozen=True)
class VoiceEntry:
    backend: BACKEND
    voice_id: str  # edge-tts voice string  OR  kokoro voice code
    display_label: str  # shown in the Combobox
    group_label: str  # category separator label
    timing_preset: dict  # GUI field values to load when this voice is selected


def _edge_preset(
    sentence: int = 800,
    paragraph: int = 850,
    title: int = 1200,
    chapter: int = 2000,
    end: int = 3000,
    trim_db: int = -58,
    trim_chunks: bool = True,
    rate: str = "+0%",
) -> dict:
    return {
        "sentencepause": str(sentence),
        "paragraphpause": str(paragraph),
        "title_ms": str(title),
        "chapter_ms": str(chapter),
        "end_pause": str(end),
        "trim_dbfs": str(trim_db),
        "trim_edge_chunks": trim_chunks,
        "rate": rate,
        "kokoro_speed": "1.0",
    }


def _kokoro_preset(
    speed: float = 1.0,
    sentence: int = 600,
    paragraph: int = 700,
    title: int = 1000,
    chapter: int = 1800,
    end: int = 3000,
) -> dict:
    return {
        "sentencepause": str(sentence),
        "paragraphpause": str(paragraph),
        "title_ms": str(title),
        "chapter_ms": str(chapter),
        "end_pause": str(end),
        "trim_dbfs": "-58",
        "trim_edge_chunks": False,
        "rate": "+0%",
        "kokoro_speed": str(speed),
    }


VOICES: list[VoiceEntry] = [
    VoiceEntry(
        backend="edge",
        voice_id="en-US-SteffanNeural",
        display_label="Steffan — en-US Male (default)",
        group_label="Microsoft Edge TTS — English (US)",
        timing_preset=_edge_preset(),
    ),
    VoiceEntry(
        backend="edge",
        voice_id="en-US-AndrewMultilingualNeural",
        display_label="Andrew Multilingual — en-US Male",
        group_label="Microsoft Edge TTS — English (US)",
        timing_preset=_edge_preset(sentence=820, paragraph=870),
    ),
    VoiceEntry(
        backend="edge",
        voice_id="en-US-AndrewNeural",
        display_label="Andrew — en-US Male",
        group_label="Microsoft Edge TTS — English (US)",
        timing_preset=_edge_preset(sentence=820, paragraph=870),
    ),
    VoiceEntry(
        backend="edge",
        voice_id="en-US-AriaNeural",
        display_label="Aria — en-US Female",
        group_label="Microsoft Edge TTS — English (US)",
        timing_preset=_edge_preset(sentence=780, paragraph=830),
    ),
    VoiceEntry(
        backend="edge",
        voice_id="en-US-AvaMultilingualNeural",
        display_label="Ava Multilingual — en-US Female",
        group_label="Microsoft Edge TTS — English (US)",
        timing_preset=_edge_preset(sentence=780, paragraph=830),
    ),
    VoiceEntry(
        backend="edge",
        voice_id="en-US-AvaNeural",
        display_label="Ava — en-US Female",
        group_label="Microsoft Edge TTS — English (US)",
        timing_preset=_edge_preset(sentence=780, paragraph=830),
    ),
    VoiceEntry(
        backend="kokoro",
        voice_id="af_heart",
        display_label="Heart (af_heart) — US Female (Kokoro default)",
        group_label="Kokoro Local AI — American English",
        timing_preset=_kokoro_preset(speed=1.0),
    ),
    VoiceEntry(
        backend="kokoro",
        voice_id="af_bella",
        display_label="Bella (af_bella) — US Female",
        group_label="Kokoro Local AI — American English",
        timing_preset=_kokoro_preset(speed=1.0, sentence=620),
    ),
    VoiceEntry(
        backend="kokoro",
        voice_id="am_michael",
        display_label="Michael (am_michael) — US Male",
        group_label="Kokoro Local AI — American English",
        timing_preset=_kokoro_preset(speed=1.0, sentence=580),
    ),
    VoiceEntry(
        backend="kokoro",
        voice_id="bf_emma",
        display_label="Emma (bf_emma) — British Female",
        group_label="Kokoro Local AI — British English",
        timing_preset=_kokoro_preset(speed=1.0, sentence=640),
    ),
    VoiceEntry(
        backend="kokoro",
        voice_id="bm_george",
        display_label="George (bm_george) — British Male",
        group_label="Kokoro Local AI — British English",
        timing_preset=_kokoro_preset(speed=1.0, sentence=600),
    ),
]


def get_voice(display_label: str) -> VoiceEntry | None:
    """Return the VoiceEntry for a given display_label, or None if not found."""
    return next((v for v in VOICES if v.display_label == display_label), None)


def display_labels() -> list[str]:
    """Ordered list of display labels for the Combobox values."""
    return [v.display_label for v in VOICES]


DEFAULT_VOICE_LABEL: str = VOICES[0].display_label
