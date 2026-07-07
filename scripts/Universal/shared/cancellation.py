"""Cooperative cancellation for long-running conversion jobs.

A conversion runs on a worker thread; the GUI exposes a Cancel button that sets a
``threading.Event``. Worker code is handed a ``cancel_check`` — a zero-argument
callable returning ``True`` once cancellation has been requested (e.g. the event's
``.is_set`` method) — and consults it at natural checkpoints (between chapters,
paragraphs, and TTS chunks). When the flag is set, the checkpoint raises
:class:`ConversionCancelled`, which unwinds through the existing ``try/finally``
temp-directory cleanup in the runner and the synth helpers, so no partial files
or temp folders are left behind.

This primitive lives in ``shared`` (not ``tts``) so the MP3 tools can reuse the
same Cancel pattern when they grow one (see Briefing §8, Phase 5.1).
"""

from __future__ import annotations

from typing import Callable, Optional

# A cancel check is a zero-arg predicate; ``None`` means cancellation is not wired up.
CancelCheck = Optional[Callable[[], bool]]


class ConversionCancelled(Exception):
    """Raised at a checkpoint when the user has requested cancellation."""


def raise_if_cancelled(
    cancel_check: CancelCheck, message: str = "Cancelled."
) -> None:
    """Raise :class:`ConversionCancelled` if ``cancel_check`` reports cancellation.

    ``cancel_check`` may be ``None`` (cancellation not wired up), in which case this
    is a no-op. Cheap enough to call inside tight loops — it only invokes the
    predicate and returns immediately when not cancelled.
    """
    if cancel_check is not None and cancel_check():
        raise ConversionCancelled(message)
