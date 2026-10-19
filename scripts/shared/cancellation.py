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

v0.6.0 Drop 3 (Plan 3), Phase 5 — extended, never replaced
----------------------------------------------------------
``shared.job_control.JobController`` adds pause and resume around this same
pattern. It **consumes** what is here rather than growing a parallel one: its
worker-facing checkpoint raises this module's :class:`ConversionCancelled`, and it
exposes a ``cancel_check`` of exactly the shape above, so a worker written against
``raise_if_cancelled`` keeps working unchanged whether it is handed a bare
``threading.Event().is_set`` or a controller.

Everything that existed before Phase 5 still exists, with the same signature and
the same observable behaviour. The only addition is :func:`is_cancelled`, the
non-raising counterpart: the controller has to *ask* whether cancellation was
requested while it decides whether to keep a paused worker waiting, and three
existing callers already open-code the identical ``None``-tolerant test. One
predicate means the convention is defined once instead of four times.

Note what this module still is **not**. It does not stop an operating-system
process, it does not suspend a thread, and it makes no claim that an in-flight
subprocess ended. Cancel is a request honoured at the next checkpoint, and
``shared.importing``'s separate import cancellation is deliberately unrelated to
it — importing a folder and converting a book are different jobs with different
Cancel buttons.
"""

from __future__ import annotations

from typing import Callable, Optional

# A cancel check is a zero-arg predicate; ``None`` means cancellation is not wired up.
CancelCheck = Optional[Callable[[], bool]]


class ConversionCancelled(Exception):
    """Raised at a checkpoint when the user has requested cancellation."""


def is_cancelled(cancel_check: CancelCheck) -> bool:
    """Report whether ``cancel_check`` says cancellation was requested.

    The same ``None``-tolerant rule as :func:`raise_if_cancelled`, without the
    raise: ``None`` means cancellation is not wired up and answers ``False``. Use
    this where a caller must *decide* rather than unwind — choosing whether to keep
    waiting, which message to show, or whether cleanup is worth starting.

    Added in Phase 5 alongside the cooperative controller. It changes nothing about
    the two names above.
    """
    return cancel_check is not None and bool(cancel_check())


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
