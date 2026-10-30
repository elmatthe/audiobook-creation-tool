"""voice_install.py — which optional component a voice needs, and whether that component's models are installed.

v0.7.0 release (Install & Continue). Since P05B Stage 2, Kokoro and Chatterbox never download on first use: they load
only verified local files (``tts.model_assets``). So the TTS panel must know, before it starts a run, whether the
selected voice's models are on this computer, and if not, which of the four optional components installs them. This
module answers both, cheaply and without importing an engine. Qwen3 voices keep their own complete answer
(``qwen3_runtime.voice_availability``); this module only names their component.
"""

from __future__ import annotations

from typing import Optional

from shared import optional_setup_protocol as proto

#: The reason prefix the panel shows for a voice whose component can be installed with Install & Continue.
NOT_INSTALLED = "not installed"


def component_for(backend: str, voice_id: str) -> Optional[str]:
    """The optional component a voice belongs to, or ``None`` (Edge, or an unknown voice)."""
    if backend == "kokoro":
        return proto.KOKORO
    if backend == "chatterbox":
        return proto.CHATTERBOX
    if backend == "qwen3":
        try:
            from tts import qwen3_runtime as rt
            key = rt.get_voice(voice_id).model_key
        except Exception:  # noqa: BLE001 - an unknown voice has no component
            return None
        for component, model_key in proto.QWEN3_MODEL_KEYS.items():
            if model_key == key:
                return component
    return None


def models_status(backend: str, voice_id: str) -> tuple[bool, str]:
    """``(ok, reason)`` for the local model files a Kokoro or Chatterbox voice loads (other backends: ``(True, "")``).

    Reads the pinned identities only (size, then SHA-256 unless a verification record vouches for the unchanged file);
    never downloads, imports an engine or writes anything.
    """
    try:
        from tts import model_assets as assets
        if backend == "kokoro":
            names = assets.KOKORO_MODEL_NAMES + (assets.kokoro_voice_name(voice_id),)
            states = assets.assess(assets.kokoro_set(), names)
            if any(state != assets.READY for state, _detail in states.values()):
                return False, ("The Kokoro voices are " + NOT_INSTALLED + " on this computer yet. Choose Install & "
                               "Continue to review the download and install them; Edge voices work meanwhile.")
            state, detail = assets.spacy_english_state()
            if state == assets.MISSING:
                return False, ("Kokoro's English pronunciation model is " + NOT_INSTALLED + " yet. Choose Install & "
                               "Continue to review the download and install it.")
            if state != assets.READY:
                return False, f"Kokoro cannot run here: {detail}."
            return True, ""
        if backend == "chatterbox":
            states = assets.assess(assets.chatterbox_set(), tuple(assets.CHATTERBOX_FILES))
            if any(state != assets.READY for state, _detail in states.values()):
                return False, ("The Chatterbox Turbo model is " + NOT_INSTALLED + " on this computer yet. Choose "
                               "Install & Continue to review the download and install it.")
            return True, ""
    except Exception as exc:  # noqa: BLE001 - reported, never a crash of the panel
        return False, f"The voice's model files could not be checked ({exc})."
    return True, ""


def installable(backend: str, voice_id: str, reason: str) -> Optional[str]:
    """The component Install & Continue should offer for an unavailable voice, or ``None`` when installing models
    cannot help (a missing reference recording, an unsupported platform, a busy engine, ...)."""
    component = component_for(backend, voice_id)
    if component is None:
        return None
    if backend in ("kokoro", "chatterbox"):
        return component if NOT_INSTALLED in reason else None
    # Qwen3: the runtime's own reasons for a missing engine or model.
    try:
        from tts import qwen3_runtime as rt
        if not rt.platform_supported():
            return None
        voice = rt.get_voice(voice_id)
        engine_ok, _ = rt.environment_status()
        model_ok, _ = rt.model_status(voice.model_key)
    except Exception:  # noqa: BLE001
        return None
    return component if not (engine_ok and model_ok) else None
