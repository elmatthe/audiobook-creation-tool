"""
voice_registry.py — Central registry of all supported TTS voices for epub2tts-edge v1.1.

Each entry defines:
  - backend:        "edge" | "kokoro" | "chatterbox" | "qwen3"
  - voice_id:       The voice identifier passed to the TTS engine
  - display_label:  Short human-readable name shown in the GUI dropdown
  - group_label:    Category header shown in the dropdown (cosmetic only)
  - timing_preset:  Dict of this voice's approved pause/trim/rate policy.
                    **v0.6.5 Phase 7 (Compact TTS UI)** removed the user-editable
                    sentence/paragraph/title/chapter pause, end-silence and trim
                    controls these keys used to back one-to-one as tkinter
                    StringVar names in epub2tts_gui.py. The maintainer-approved
                    values are unchanged; ``epub2tts_gui.TtsPanel.run_job`` now
                    reads this dict directly at run time instead, so a voice's
                    policy can no longer be edited from the panel at all — only
                    ``rate``/``kokoro_speed`` remain live, user-editable Band 3
                    controls (and still take their default from here).
                    For edge voices: sentencepause, paragraphpause, title_ms, chapter_ms,
                                     end_pause, trim_dbfs, trim_edge_chunks, rate.
                    For kokoro voices: speed (float str), sentencepause, paragraphpause,
                                       title_ms, chapter_ms, end_pause.
                    trim_edge_chunks is always False for kokoro.
                    For chatterbox voices: the same field names as kokoro (one shared
                    shape read for every backend, regardless of which fields that
                    backend's engine actually consumes — see each preset helper).

The "chatterbox" backend was admitted here in v0.6.1 Plan 4 Phase 8 so the engine
module and the preset helper have somewhere to land. **Phase 10 registered the four
approved cloned voices**, after the maintainer listened to all four Phase 9
evaluation outputs on 2026-08-15 and approved every one of them. The twelve
pre-existing rows were unchanged by both phases, in value and in order; the four
approved rows are appended after them.

**Phase 13A.3 renamed the first twelve ``display_label`` strings** to the exact
wording the maintainer specified on 2026-08-20, which explicitly supersedes the
drop's earlier "byte-identical labels" constraint. The rename is user-facing text
only: every ``backend``, ``voice_id``, ``group_label`` and ``timing_preset`` — and
the order of all sixteen rows — is untouched, Steffan is still row 0 and still the
default, and the four Chatterbox labels were already the requested strings and were
not retyped. Nothing persists a voice by label (no ``settings.set`` writes one and
no key for it exists in ``shared.config.USER_STATE_SETTINGS``), so the rename needs
no migration and none was invented.

**v0.6.7 Decision B (owner roster decision, 2026-10-19) added four Kokoro rows**, ``am_fenrir``,
``am_puck`` and ``am_onyx`` (American) and ``bm_daniel`` (British), each registered **inside the existing Kokoro
block** next to its language siblings and taking the shared neutral Kokoro preset unmodified (speed 1.0, no per-voice
tuning). Every pre-existing row keeps its backend, voice id, label, group, timing and its *relative* order; Steffan is
still row 0 and the default. They were heard first in the evaluation harness, which called the production Kokoro
engine directly with these ids (``tts.kokoro_synth`` routes ``am_``/``bm_`` to the American/British pipelines). A
new Kokoro voice file is fetched on first use, exactly like the existing five.

**v0.6.7 CP6 registered the eight Qwen3-TTS voices** (owner roster decision B, 2026-10-19; architecture
approved the same day): CustomVoice presets ``Qwen3 - Aiden`` and ``Qwen3 - Ryan`` and the six cloned voices
``Qwen3 - Female 1``/``Female 2``/``Male 1``/``Male 2``/``Male 3``/``Male 4``. They are appended after the
Chatterbox block, so every earlier row keeps its backend, id, label, group, timing and position, and Steffan is
still row 0 and the default. A Qwen3 clone shares only the *reference recording* with its Chatterbox namesake; it has
its own backend (``"qwen3"``), its own internal id and its own engine, and dispatch reads the backend, never the label.
Availability is owned by ``tts/qwen3_runtime.py`` (platform, isolated environment, model files, and for clones the
reference recording and an approved transcript).

**Registered is not the same as available.** A row here says a voice is part of the
supported configuration. Whether it can actually run on *this* machine is a separate
question, owned by ``tts/chatterbox_synth.py`` — the Chatterbox voices are backed by
local, maintainer-supplied reference recordings that exist on one machine only. A
missing recording leaves the row in place and reports "setup required"; it never
removes a voice, substitutes another, or fetches anything.

**v0.7.0 P02A (owner Q5): identity is ``(backend, voice_id)``; labels and order are cosmetic.**
``display_label`` and the position of a row may be edited freely: the dropdown shows the rows in
``VOICES`` order exactly as written (engine groups may interleave), and no engine, model, preset
speaker or reference recording is ever chosen by a label. The six cloned voices' recordings are
named by the explicit ``VOICE_REFERENCES`` → ``REFERENCE_RECORDINGS`` tables below, so renaming
"Chatterbox - Female 1" changes no file name. Every visible engine label (Chatterbox and Qwen3 status,
setup and error text) is looked up here by stable key. The module checks itself on import and refuses
an empty, padded, duplicate (NFC-compared) or otherwise ambiguous registry with a message naming the
stable keys involved, rather than silently taking the first match.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

BACKEND = Literal["edge", "kokoro", "chatterbox", "qwen3"]
#: The engines a row may name. Adding one is an engine change, never a registry edit.
BACKENDS: tuple[str, ...] = ("edge", "kokoro", "chatterbox", "qwen3")


@dataclass(frozen=True)
class VoiceEntry:
    backend: BACKEND
    voice_id: str  # edge-tts voice string  OR  kokoro voice code
    display_label: str  # shown in the Combobox
    group_label: str  # category separator label
    timing_preset: dict  # GUI field values to load when this voice is selected

    @property
    def key(self) -> tuple[str, str]:
        """The durable identity ``(backend, voice_id)``. The label and the row's position are not part of it."""
        return (self.backend, self.voice_id)


def _edge_preset(
    sentence: int = 800,
    paragraph: int = 850,
    title: int = 1200,
    chapter: int = 2000,
    end: int = 0,  # v0.7.0 Q1: an Edge narration ends with its last sound, no closing pause
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
    end: int = 0,  # v0.7.0 Q1: a local-engine narration ends with its last sound, no closing pause
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


def _chatterbox_preset(
    sentence: int = 600,
    paragraph: int = 700,
    title: int = 1000,
    chapter: int = 1800,
    end: int = 0,  # v0.7.0 Q1: a local-engine narration ends with its last sound, no closing pause
) -> dict:
    """Timing defaults for the local Chatterbox engine.

    Deliberately identical in *shape* to ``_kokoro_preset`` — the GUI reads one set
    of timing fields regardless of backend — and identical in *values* to it as
    well, because both are local engines that emit clean chunk boundaries. There is
    no ``rate``/speed control: the pinned Chatterbox Turbo API exposes no speed
    parameter, so the field is carried at its neutral value rather than invented.
    ``trim_edge_chunks`` stays off; edge-chunk trimming corrects an Edge TTS
    artefact that local engines do not produce.

    Added in v0.6.1 Plan 4 Phase 8 as engine foundation; Phase 10's four rows are
    its only callers, and all four take it **unmodified**. The maintainer approved
    every voice under one common set of model parameters, so there is deliberately
    no per-voice tuning here: Female 1 is not timed differently from Male 2.
    """
    return {
        "sentencepause": str(sentence),
        "paragraphpause": str(paragraph),
        "title_ms": str(title),
        "chapter_ms": str(chapter),
        "end_pause": str(end),
        "trim_dbfs": "-58",
        "trim_edge_chunks": False,
        "rate": "+0%",
        "kokoro_speed": "1.0",
    }


def _qwen3_preset(
    sentence: int = 600,
    paragraph: int = 700,
    title: int = 1000,
    chapter: int = 1800,
    end: int = 0,  # v0.7.0 Q1: a local-engine narration ends with its last sound, no closing pause
) -> dict:
    """Timing defaults for the local Qwen3-TTS engine.

    The same *shape* and the same *values* as ``_chatterbox_preset`` and ``_kokoro_preset``: all three are local
    engines whose chunk boundaries are clean, and the owner ruled (CP6, Q6) that Qwen3 follows ACT's existing
    narration policy rather than the evaluation's fixed pauses. The panel hands ``paragraphpause`` to the engine as
    the pause between chunks and ``end_pause`` (0 since v0.7.0 Q1: no closing pause) exactly as it does for the other
    local engines. There is no rate/speed control (the Qwen3 API exposes none), so ``rate`` and ``kokoro_speed`` are carried
    at their neutral values, and ``trim_edge_chunks`` stays off. No per-voice tuning: Aiden is not timed differently
    from Male 4.
    """
    return {
        "sentencepause": str(sentence),
        "paragraphpause": str(paragraph),
        "title_ms": str(title),
        "chapter_ms": str(chapter),
        "end_pause": str(end),
        "trim_dbfs": "-58",
        "trim_edge_chunks": False,
        "rate": "+0%",
        "kokoro_speed": "1.0",
    }


#: The one cosmetic heading the four Chatterbox rows share, in the same
#: "<engine> — <category>" shape the Edge and Kokoro groups already use. It is a
#: dropdown separator only and never part of a voice's name.
CHATTERBOX_GROUP_LABEL = "Chatterbox Turbo Local AI — Cloned Voices"

#: The heading the eight Qwen3 rows share. A separate, clearly identified group (owner ruling): it never reuses the
#: Chatterbox heading even though six of the voices share a reference recording with a Chatterbox voice.
QWEN3_GROUP_LABEL = "Qwen3-TTS Local AI — Preset and Cloned Voices"

# Twenty-eight rows: five Edge, nine Kokoro (the original five plus the four Decision B additions of
# 2026-10-19), six approved Chatterbox voices (the original four plus Male 3 and Male 4,
# both approved 2026-09-20), then the eight Qwen3 voices (v0.6.7 CP6).
# v0.6.5 Phase 2 also removed the two multilingual Edge rows
# (en-US-AndrewMultilingualNeural, en-US-AvaMultilingualNeural) per the
# plan's final voice inventory (Section 3) — ordinary Andrew and Ava are
# unaffected.
# The remaining rows keep the order, voice ids and timing they had before, and
# carry the display wording the maintainer specified in Phase 13A.3.
VOICES: list[VoiceEntry] = [
    VoiceEntry(
        backend="edge",
        voice_id="en-US-SteffanNeural",
        display_label="Edge Male - Steffan (en-US)",
        group_label="Microsoft Edge TTS — English (US)",
        timing_preset=_edge_preset(),
    ),
    VoiceEntry(
        backend="edge",
        voice_id="en-US-AndrewNeural",
        display_label="Edge Male - Andrew (en-US)",
        group_label="Microsoft Edge TTS — English (US)",
        timing_preset=_edge_preset(sentence=820, paragraph=870),
    ),
    VoiceEntry(
        backend="edge",
        voice_id="en-US-AriaNeural",
        display_label="Edge Female - Aria (en-US)",
        group_label="Microsoft Edge TTS — English (US)",
        timing_preset=_edge_preset(sentence=780, paragraph=830),
    ),
    VoiceEntry(
        backend="edge",
        voice_id="en-US-AvaNeural",
        display_label="Edge Female - Ava (en-US)",
        group_label="Microsoft Edge TTS — English (US)",
        timing_preset=_edge_preset(sentence=780, paragraph=830),
    ),
    VoiceEntry(
        backend="edge",
        voice_id="en-US-JennyNeural",
        display_label="Edge Female - Jenny (en-US)",
        group_label="Microsoft Edge TTS — English (US)",
        # Measured against Steffan on the same source: in single-file mode Jenny's
        # real gaps are already ~75ms SHORTER than his (877ms vs 951ms), so this is
        # a deliberately minimal trim, not a correction. Her extra gappiness on
        # full-book runs comes from Edge's own prosody in the batch path, which
        # ignores these fields entirely — see CHANGELOG 2026-07-19.
        timing_preset=_edge_preset(sentence=750, paragraph=800),
    ),
    VoiceEntry(
        backend="kokoro",
        voice_id="af_heart",
        display_label="Kokoro Female (Default) - Heart (en-US)",
        group_label="Kokoro Local AI — American English",
        timing_preset=_kokoro_preset(speed=1.0),
    ),
    VoiceEntry(
        backend="kokoro",
        voice_id="af_bella",
        display_label="Kokoro Female - Bella (en-US)",
        group_label="Kokoro Local AI — American English",
        timing_preset=_kokoro_preset(speed=1.0, sentence=620),
    ),
    VoiceEntry(
        backend="kokoro",
        voice_id="am_michael",
        display_label="Kokoro Male - Michael (en-US)",
        group_label="Kokoro Local AI — American English",
        timing_preset=_kokoro_preset(speed=1.0, sentence=580),
    ),
    # ---- v0.6.7 Decision B: three American Kokoro voices added by the owner's roster decision
    # of 2026-10-19, placed with their American siblings. Shared neutral preset, unmodified.
    VoiceEntry(
        backend="kokoro",
        voice_id="am_fenrir",
        display_label="Kokoro Male - Fenrir (en-US)",
        group_label="Kokoro Local AI — American English",
        timing_preset=_kokoro_preset(speed=1.0),
    ),
    VoiceEntry(
        backend="kokoro",
        voice_id="am_puck",
        display_label="Kokoro Male - Puck (en-US)",
        group_label="Kokoro Local AI — American English",
        timing_preset=_kokoro_preset(speed=1.0),
    ),
    VoiceEntry(
        backend="kokoro",
        voice_id="am_onyx",
        display_label="Kokoro Male - Onyx (en-US)",
        group_label="Kokoro Local AI — American English",
        timing_preset=_kokoro_preset(speed=1.0),
    ),
    VoiceEntry(
        backend="kokoro",
        voice_id="bf_emma",
        display_label="Kokoro Female - Emma (en-UK)",
        group_label="Kokoro Local AI — British English",
        timing_preset=_kokoro_preset(speed=1.0, sentence=640),
    ),
    VoiceEntry(
        backend="kokoro",
        voice_id="bm_george",
        display_label="Kokoro Male - George (en-UK)",
        group_label="Kokoro Local AI — British English",
        timing_preset=_kokoro_preset(speed=1.0, sentence=600),
    ),
    # ---- v0.6.7 Decision B: the British addition, with its British siblings.
    VoiceEntry(
        backend="kokoro",
        voice_id="bm_daniel",
        display_label="Kokoro Male - Daniel (en-UK)",
        group_label="Kokoro Local AI — British English",
        timing_preset=_kokoro_preset(speed=1.0),
    ),
    # ---- v0.6.1 Plan 4 Phase 10: the four approved Chatterbox voices ---- #
    # The display labels are the maintainer's own, written exactly as approved on
    # 2026-08-15: an ASCII hyphen surrounded by spaces, not the em dash the drop's
    # §5.7 had proposed. Phase 13A.3 asked for these same four strings, so they are
    # left exactly as they are rather than retyped into an identical diff. No engine
    # detail ("Turbo", "CPU", "cloned") belongs in them — that wording lives in the
    # panel's engine/status line.
    VoiceEntry(
        backend="chatterbox",
        voice_id="chatterbox-female-1",
        display_label="Chatterbox - Female 1",
        group_label=CHATTERBOX_GROUP_LABEL,
        timing_preset=_chatterbox_preset(),
    ),
    VoiceEntry(
        backend="chatterbox",
        voice_id="chatterbox-female-2",
        display_label="Chatterbox - Female 2",
        group_label=CHATTERBOX_GROUP_LABEL,
        timing_preset=_chatterbox_preset(),
    ),
    VoiceEntry(
        backend="chatterbox",
        voice_id="chatterbox-male-1",
        display_label="Chatterbox - Male 1",
        group_label=CHATTERBOX_GROUP_LABEL,
        timing_preset=_chatterbox_preset(),
    ),
    VoiceEntry(
        backend="chatterbox",
        voice_id="chatterbox-male-2",
        display_label="Chatterbox - Male 2",
        group_label=CHATTERBOX_GROUP_LABEL,
        timing_preset=_chatterbox_preset(),
    ),
    # ---- v0.6.5 Phase 2: Male 3 and Male 4 approved by the maintainer's
    # final listening ruling on 2026-09-20. Male 3 is the ORIGINAL candidate
    # sample — a separate bounded pitch-retry variant was tried and rejected;
    # the maintainer preferred the voice exactly as it was before that retry,
    # so no pitch/timbre adjustment of any kind reached this registration.
    # Both take the same shared, unmodified preset as the other four
    # Chatterbox rows (no per-voice tuning, per §6/the Phase 9 convention);
    # display labels per plan Section 3.
    VoiceEntry(
        backend="chatterbox",
        voice_id="chatterbox-male-3",
        display_label="Chatterbox - Male 3",
        group_label=CHATTERBOX_GROUP_LABEL,
        timing_preset=_chatterbox_preset(),
    ),
    VoiceEntry(
        backend="chatterbox",
        voice_id="chatterbox-male-4",
        display_label="Chatterbox - Male 4",
        group_label=CHATTERBOX_GROUP_LABEL,
        timing_preset=_chatterbox_preset(),
    ),
    # ---- v0.6.7 CP6: the eight Qwen3-TTS voices, labels exactly as the owner specified on 2026-10-19 ---- #
    # Internal ids are distinct from every Chatterbox id and dispatch reads ``backend``, never the label. The
    # presets need only the CustomVoice model; the six clones need the Base model, their bundled reference
    # recording and an approved transcript (see tts/qwen3_runtime.py).
    VoiceEntry(
        backend="qwen3",
        voice_id="qwen3-aiden",
        display_label="Qwen3 - Aiden",
        group_label=QWEN3_GROUP_LABEL,
        timing_preset=_qwen3_preset(),
    ),
    VoiceEntry(
        backend="qwen3",
        voice_id="qwen3-ryan",
        display_label="Qwen3 - Ryan",
        group_label=QWEN3_GROUP_LABEL,
        timing_preset=_qwen3_preset(),
    ),
    VoiceEntry(
        backend="qwen3",
        voice_id="qwen3-female-1",
        display_label="Qwen3 - Female 1",
        group_label=QWEN3_GROUP_LABEL,
        timing_preset=_qwen3_preset(),
    ),
    VoiceEntry(
        backend="qwen3",
        voice_id="qwen3-female-2",
        display_label="Qwen3 - Female 2",
        group_label=QWEN3_GROUP_LABEL,
        timing_preset=_qwen3_preset(),
    ),
    VoiceEntry(
        backend="qwen3",
        voice_id="qwen3-male-1",
        display_label="Qwen3 - Male 1",
        group_label=QWEN3_GROUP_LABEL,
        timing_preset=_qwen3_preset(),
    ),
    VoiceEntry(
        backend="qwen3",
        voice_id="qwen3-male-2",
        display_label="Qwen3 - Male 2",
        group_label=QWEN3_GROUP_LABEL,
        timing_preset=_qwen3_preset(),
    ),
    VoiceEntry(
        backend="qwen3",
        voice_id="qwen3-male-3",
        display_label="Qwen3 - Male 3",
        group_label=QWEN3_GROUP_LABEL,
        timing_preset=_qwen3_preset(),
    ),
    VoiceEntry(
        backend="qwen3",
        voice_id="qwen3-male-4",
        display_label="Qwen3 - Male 4",
        group_label=QWEN3_GROUP_LABEL,
        timing_preset=_qwen3_preset(),
    ),
]


#: The voice the panel starts on, by identity: Steffan stays the default wherever his row sits and whatever it is called.
DEFAULT_VOICE_KEY: tuple[str, str] = ("edge", "en-US-SteffanNeural")


# --------------------------------------------------------------------------- #
# The six bundled reference recordings (v0.7.0 P02A): explicit data, never derived from a label
# --------------------------------------------------------------------------- #
#: Stable reference id -> the fixed basename of its one bundled copy. The ids are the Qwen3 transcript keys
#: (``qwen3_runtime.Qwen3Voice.reference_name``); the basenames are the v0.6.7 file names, kept byte-for-byte (owner
#: Q31) even though they read like the Chatterbox labels. Renaming a voice never renames its recording.
REFERENCE_RECORDINGS: dict[str, str] = {
    "Female-1": "Chatterbox - Female 1.wav",
    "Female-2": "Chatterbox - Female 2.wav",
    "Male-1": "Chatterbox - Male 1.wav",
    "Male-2": "Chatterbox - Male 2.wav",
    "Male-3": "Chatterbox - Male 3.wav",
    "Male-4": "Chatterbox - Male 4.wav",
}

#: Where the six recordings live, repo-relative (v0.7.0 P03A). The only place either engine looks: there is no
#: fallback to the pre-v0.7.0 ``files/Chatterbox-Voice-Uploads/`` folder, because every supported install (a fresh
#: archive, or a git checkout) brings the recordings here itself.
REFERENCE_DIRECTORY: tuple[str, ...] = ("files", "Cloned-Voice-Uploads")

#: Which recording a cloned voice is conditioned on, by stable ``(backend, voice_id)``. A Chatterbox voice and the
#: Qwen3 clone of the same speaker share the recording and nothing else: their engines, ids and models stay separate.
VOICE_REFERENCES: dict[tuple[str, str], str] = {
    ("chatterbox", "chatterbox-female-1"): "Female-1",
    ("chatterbox", "chatterbox-female-2"): "Female-2",
    ("chatterbox", "chatterbox-male-1"): "Male-1",
    ("chatterbox", "chatterbox-male-2"): "Male-2",
    ("chatterbox", "chatterbox-male-3"): "Male-3",
    ("chatterbox", "chatterbox-male-4"): "Male-4",
    ("qwen3", "qwen3-female-1"): "Female-1",
    ("qwen3", "qwen3-female-2"): "Female-2",
    ("qwen3", "qwen3-male-1"): "Male-1",
    ("qwen3", "qwen3-male-2"): "Male-2",
    ("qwen3", "qwen3-male-3"): "Male-3",
    ("qwen3", "qwen3-male-4"): "Male-4",
}


def reference_id(backend: str, voice_id: str) -> str:
    """The stable reference id (``"Female-1"``) a cloned voice uses. ``KeyError`` for a voice that clones nothing."""
    try:
        return VOICE_REFERENCES[(backend, voice_id)]
    except KeyError:
        raise KeyError(f"{backend}/{voice_id} has no bundled reference recording") from None


def reference_recording_filename(backend: str, voice_id: str) -> str:
    """The fixed basename of the recording ``backend``/``voice_id`` is cloned from, e.g. ``"Chatterbox - Female 1.wav"``."""
    return REFERENCE_RECORDINGS[reference_id(backend, voice_id)]


# --------------------------------------------------------------------------- #
# Validation: an edited registry is refused, never half-used
# --------------------------------------------------------------------------- #
class VoiceRegistryError(ValueError):
    """The voice table cannot be used as written. The message names every problem and the stable keys involved."""


#: A voice id is passed straight to an engine and names preview files, so it is a plain token.
_VOICE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def _label_key(label: str) -> str:
    """How two labels are compared for sameness: Unicode NFC. The displayed text itself is kept exactly as written."""
    return unicodedata.normalize("NFC", label)


def registry_problems(voices: list[VoiceEntry]) -> list[str]:
    """Every reason ``voices`` cannot be offered, as sentences that name the stable keys. ``[]`` means usable."""
    problems: list[str] = []
    seen_keys: set[tuple[str, str]] = set()
    seen_ids: dict[str, str] = {}
    labels: dict[str, list[str]] = {}
    for index, entry in enumerate(voices):
        where = f"row {index + 1} ({entry.backend}/{entry.voice_id})"
        if entry.backend not in BACKENDS:
            problems.append(f"{where}: unknown backend {entry.backend!r}; use one of {', '.join(BACKENDS)}")
        if not isinstance(entry.voice_id, str) or not _VOICE_ID.fullmatch(entry.voice_id):
            problems.append(f"{where}: the voice id {entry.voice_id!r} is not a plain token "
                            "(letters, digits, '_', '.', '-'; no spaces)")
        if entry.key in seen_keys:
            problems.append(f"{where}: this voice is listed twice; each (backend, voice_id) may appear once")
        elif entry.voice_id in seen_ids and seen_ids[entry.voice_id] != entry.backend:
            problems.append(f"{where}: the voice id is also used by the {seen_ids[entry.voice_id]} backend; "
                            "a voice id may belong to one backend only")
        seen_keys.add(entry.key)
        seen_ids.setdefault(entry.voice_id, entry.backend)
        label = entry.display_label
        if not isinstance(label, str) or not label.strip():
            problems.append(f"{where}: the display label is empty; give it visible text")
            continue
        if label != label.strip():
            problems.append(f"{where}: the display label {label!r} starts or ends with whitespace; remove it")
        if any(unicodedata.category(ch) == "Cc" for ch in label):
            problems.append(f"{where}: the display label {label!r} contains a control character (e.g. a line break)")
        labels.setdefault(_label_key(label), []).append(f"{entry.backend}/{entry.voice_id}")
    for label, owners in labels.items():
        if len(owners) > 1:
            problems.append(f"the display label {label!r} is used by {len(owners)} voices ({', '.join(owners)}); "
                            "labels must differ (compared after Unicode NFC normalisation)")
    if voices and DEFAULT_VOICE_KEY not in seen_keys:
        problems.append(f"the default voice {DEFAULT_VOICE_KEY[0]}/{DEFAULT_VOICE_KEY[1]} is not registered")
    for entry in voices:
        if entry.backend == "chatterbox" and entry.key not in VOICE_REFERENCES:
            problems.append(f"{entry.backend}/{entry.voice_id}: no reference recording is mapped for this cloned voice "
                            "(add it to VOICE_REFERENCES)")
    if not voices:
        problems.append("no voices are registered")
    return problems


def reference_table_problems() -> list[str]:
    """Contradictions inside the two reference tables themselves (independent of labels and order)."""
    problems = [f"{backend}/{voice_id}: unknown reference id {ref!r}"
                for (backend, voice_id), ref in VOICE_REFERENCES.items() if ref not in REFERENCE_RECORDINGS]
    names = list(REFERENCE_RECORDINGS.values())
    if len({n.casefold() for n in names}) != len(names):
        problems.append("two reference ids name the same recording file")
    return problems


def check_registry(voices: list[VoiceEntry]) -> None:
    """Raise ``VoiceRegistryError`` listing every problem, or return quietly."""
    problems = registry_problems(voices) + reference_table_problems()
    if problems:
        raise VoiceRegistryError("The voice list in tts/voice_registry.py cannot be used:\n- " + "\n- ".join(problems))


# --------------------------------------------------------------------------- #
# Lookups. Each reads VOICES at call time; none caches a label.
# --------------------------------------------------------------------------- #
def get_voice(display_label: str) -> VoiceEntry | None:
    """Return the VoiceEntry for a given display_label, or None if not found.

    The panel's dropdown holds labels, so this is the one place a label is turned back into an identity. Labels are
    validated unique, so at most one row can match.
    """
    return next((v for v in VOICES if v.display_label == display_label), None)


def voice_by_key(backend: str, voice_id: str) -> VoiceEntry | None:
    """The row for a stable identity, wherever it sits and whatever it is called."""
    return next((v for v in VOICES if v.key == (backend, voice_id)), None)


def label_for(backend: str, voice_id: str) -> str:
    """The current display label of ``backend``/``voice_id``; ``KeyError`` if that voice is not registered."""
    entry = voice_by_key(backend, voice_id)
    if entry is None:
        raise KeyError(f"{backend}/{voice_id} is not a registered voice")
    return entry.display_label


def display_labels() -> list[str]:
    """Ordered list of display labels for the Combobox values: ``VOICES`` order exactly, never regrouped or sorted."""
    return [v.display_label for v in VOICES]


def default_voice_label() -> str:
    """The label the panel starts on: the default voice's *current* label."""
    return label_for(*DEFAULT_VOICE_KEY)


check_registry(VOICES)

DEFAULT_VOICE_LABEL: str = default_voice_label()
