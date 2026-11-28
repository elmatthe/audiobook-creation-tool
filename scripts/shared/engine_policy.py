"""engine_policy.py — which voice engines this platform offers: the one answer every TTS surface asks (macOS P4C).

Plan §12.F and §19 P4C, Revision 3; owner decisions Q2=A (2026-11-16) and the P4A acceptance (2026-11-16).

* **Windows** (and any platform other than macOS) offers every registered engine, exactly as released: Edge, Kokoro,
  Chatterbox Turbo, Qwen3-TTS and OmniVoice, 34 voices. Each engine's own gates (platform, GPU, installed files) still
  decide whether a voice can run on a given computer; this policy never adds or removes anything there.
* **macOS** offers Edge, Kokoro and OmniVoice: 20 voices. Chatterbox Turbo and Qwen3-TTS are SKIPPED BY OWNER DECISION:
  they are absent from every macOS surface (the voice list, first-run choices, Install & Continue, setup plans, repair,
  health probes, samples and wording), and a request for one that reaches dispatch anyway is refused with a plain
  message. Nothing switches to another voice, nothing is downloaded and the engine is never imported.

**Nothing is deleted.** The registry keeps all 34 ``(backend, voice_id)`` identities, every reference recording,
transcript, preview, manifest and pin; this module filters what a platform *offers*, never what exists.

**Decided from the real platform.** :func:`current_platform` is ``sys.platform``, read at call time. There is no user
toggle and no compatibility mode. Every function takes an explicit ``platform=`` so tests (and the Windows suites run
on a Mac) can ask about either platform without touching ``sys.platform``.

Standard library only and free of every app import but the engine registry (``tts.engines.registry``, standard library
only too): the first-run setup imports it in the base interpreter before the app's environment exists, and
``tts.voice_registry`` imports it. v0.8.2 Phase 5A: the engine list, the macOS list, the names and the component map are
derived from that registry, never kept here as a second copy.
"""

from __future__ import annotations

import sys
from typing import Iterable, Optional

from tts.engines import registry as _registry

EDGE = "edge"
KOKORO = "kokoro"
CHATTERBOX = "chatterbox"
QWEN3 = "qwen3"
OMNIVOICE = "omnivoice"

#: Every engine a voice may name, in registry order (``tts.engines.registry``; ``tts.voice_registry.BACKENDS`` is the
#: same list).
ENGINES: tuple[str, ...] = _registry.TABLES.engines

#: ``sys.platform`` on macOS.
MACOS = "darwin"

#: What a Mac offers (owner decisions Q2=A and the P4A acceptance): Edge 5 + Kokoro 9 + OmniVoice 6 = 20 voices. The
#: engines whose registry definition names macOS.
MACOS_ENGINES: tuple[str, ...] = _registry.TABLES.macos_engines

#: The names a person reads.
ENGINE_NAMES: dict[str, str] = dict(_registry.TABLES.names)

#: Each optional-setup component and the engine it installs (``shared.optional_setup_protocol.COMPONENTS``, from the
#: same registry). Edge has no component: it needs no local model.
COMPONENT_ENGINES: dict[str, str] = dict(_registry.TABLES.component_engines)


class EngineNotOffered(RuntimeError):
    """A voice engine this platform does not offer was asked to run, install, repair or be probed. Nothing happened."""

    def __init__(self, engine: str, message: str) -> None:
        super().__init__(message)
        self.engine = engine


def current_platform() -> str:
    """The platform the policy answers for: ``sys.platform``, read now (never cached)."""
    return sys.platform


def _platform(platform: Optional[str]) -> str:
    return current_platform() if platform is None else platform


def platform_name(platform: Optional[str] = None) -> str:
    """How messages name *platform*."""
    plat = _platform(platform)
    if plat == MACOS:
        return "macOS"
    if plat == "win32":
        return "Windows"
    return "this platform"


def offered_engines(platform: Optional[str] = None) -> tuple[str, ...]:
    """The engines *platform* offers, in registry order."""
    return MACOS_ENGINES if _platform(platform) == MACOS else ENGINES


def is_offered(engine: str, platform: Optional[str] = None) -> bool:
    """Whether *platform* offers *engine*. An unknown engine is never offered."""
    return engine in offered_engines(platform)


def component_offered(component: str, platform: Optional[str] = None) -> bool:
    """Whether *platform* offers the engine an optional-setup *component* installs. An unknown component is not."""
    engine = COMPONENT_ENGINES.get(component)
    return engine is not None and is_offered(engine, platform)


def offered_components(components: Iterable[str], platform: Optional[str] = None) -> tuple[str, ...]:
    """*components* without the ones *platform* does not offer, order kept."""
    return tuple(c for c in components if component_offered(c, platform))


def offered_engine_list_text(platform: Optional[str] = None) -> str:
    """``"Microsoft Edge TTS, Kokoro or OmniVoice"``: the engines *platform* offers, for a sentence."""
    names = [ENGINE_NAMES[e] for e in offered_engines(platform)]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def not_offered_message(engine: str, platform: Optional[str] = None) -> str:
    """The plain, actionable refusal for *engine* on *platform*: what is not offered, that nothing happened, what to do."""
    where = platform_name(platform)
    name = ENGINE_NAMES.get(engine)
    what = f"{name} voices are" if name else f"The voice engine {engine!r} is"
    return (f"{what} not available in this app on {where}, so nothing was started, installed or downloaded. "
            f"Choose a {offered_engine_list_text(platform)} voice instead.")


def require_offered(engine: str, platform: Optional[str] = None) -> None:
    """Return quietly when *platform* offers *engine*; otherwise raise :class:`EngineNotOffered` with the message."""
    if not is_offered(engine, platform):
        raise EngineNotOffered(engine, not_offered_message(engine, platform))


def require_component_offered(component: str, platform: Optional[str] = None) -> None:
    """:func:`require_offered` for the engine an optional-setup *component* installs."""
    engine = COMPONENT_ENGINES.get(component, component)
    require_offered(engine, platform)
