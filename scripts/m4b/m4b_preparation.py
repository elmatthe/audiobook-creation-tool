"""Preparing one M4B Maker or Metadata Editor operation off the Tk thread — v0.8.2 Checkpoint 2.

Build M4B(s) and the Editor's three actions used to reserve their output and plan every Book inside the button's
Tk callback. The planners checked each Book's two paths against every source by resolving every source again, so
the window froze for as long as that took (18 s for 250 one-track Maker Books, 15 s for 250 Editor files) with
"Ready" still painted. The planners now normalise their inputs once (``shared.output_paths.InputIndex``); this
module moves what is left of the work -- reserving, validating a custom destination, planning -- onto one
short-lived preparation worker per press.

The two panels have the same contract here, so they share this code, as they share ``m4b_staging``. Nothing in
it touches Tk, a widget or a panel: the press freezes its inputs on Tk, :func:`prepare` runs on the worker and
speaks only through the *post* callable the panel gives it (a queue its pump drains), and the pump decides on Tk.

**Who owns what a preparation reserved.** The worker, from the moment *reserve* returns until :meth:`Preparation.offer`
hands the finished result over; when the offer is refused (Cancel or Close came first), when planning fails, or when
anything else goes wrong, the worker releases it itself before it posts its ending. Once offered, the panel owns it:
:meth:`Preparation.adopt` takes it to run it, :meth:`Preparation.withdraw` takes it back for the panel to release. One
lock makes offer, adopt and withdraw one decision each, so exactly one side releases what was reserved, and a result
nobody adopted can never start media.

This is not a job controller. A preparation has no Pause; its Cancel is its own ``threading.Event``, seen at every
:meth:`Preparation.checkpoint` (between sources and Books) through the shared ``ConversionCancelled``. The operation
still gets exactly one controller, created only when the panel adopts the plan.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from shared.cancellation import ConversionCancelled

__all__ = [
    "PROGRESS",
    "PREPARED",
    "CANCELLED",
    "REFUSED",
    "FAULT",
    "PROGRESS_INTERVAL",
    "PAINT_WAIT",
    "Refusal",
    "Preparation",
    "PreparationMessage",
    "prepare",
]

#: The message kinds. Exactly one of the last four is a preparation's final message.
PROGRESS = "progress"
PREPARED = "prepared"
CANCELLED = "cancelled"
REFUSED = "refused"
FAULT = "fault"

#: Seconds between two progress messages of one preparation (the first and the last always go).
PROGRESS_INTERVAL = 0.1

#: The longest the worker waits for the panel to say it has painted "Preparing job…" before it starts work anyway.
#:
#: Measured on HOME-PC (v0.8.2 Checkpoint 2, Editor, 5,000 files): the repaint after the press takes ~15 ms on its
#: own, but 100-130 ms when the worker is already planning, because every tkinter call releases the GIL and must win
#: it back from a CPU-bound thread. So the worker lets Tk finish that one repaint first.
PAINT_WAIT = 0.25


class Refusal(Exception):
    """An operation the tool refuses for an ordinary, explainable reason: *text* is shown, *detail* is logged."""

    def __init__(self, text: str, detail: str = "", *, warning: bool = False) -> None:
        super().__init__(text)
        self.text = text
        self.detail = detail
        #: Shown as a warning rather than an error (the Editor's "nothing could be read").
        self.warning = warning


class Preparation:
    """One accepted press, from the click until its result is adopted or it ends.

    *label* names the operation in messages; *inputs* is whatever the panel froze on Tk at the press (the immutable
    workspace snapshot, the options, the configuration, the lock-guarded id factory). The worker reads only these.
    """

    def __init__(self, *, label: str, inputs: Any, number: int) -> None:
        self.label = label
        self.inputs = inputs
        self.number = number
        self.cancel_requested = threading.Event()
        #: Set by the panel once Tk has painted the press (an idle callback), or when it stops wanting it.
        self.painted = threading.Event()
        self._lock = threading.Lock()
        self._offered: Any = None
        self._handed_over = False

    def checkpoint(self) -> None:
        """The worker's cooperative stop: raises once Cancel or Close asked for it."""
        if self.cancel_requested.is_set():
            raise ConversionCancelled("preparation cancelled")

    def offer(self, result: Any) -> bool:
        """Worker: hand the finished result to the panel. False when the panel no longer wants it.

        Once only: a second offer for the same press (a replayed worker body) is refused, so its worker releases
        what it reserved instead of replacing -- and leaking -- the result already handed over.
        """
        with self._lock:
            if self.cancel_requested.is_set() or self._handed_over:
                return False
            self._handed_over = True
            self._offered = result
            return True

    def adopt(self) -> Any:
        """Panel: take the offered result to run it, or ``None`` when there is none or Cancel came first."""
        with self._lock:
            if self.cancel_requested.is_set():
                return None
            result, self._offered = self._offered, None
            return result

    def withdraw(self) -> Any:
        """Panel: stop wanting this preparation. Returns an offered result the caller must now release, if any."""
        with self._lock:
            self.cancel_requested.set()
            self.painted.set()  # nothing is left to wait for
            result, self._offered = self._offered, None
            return result

    def wait_until_painted(self) -> None:
        """Worker: give Tk the chance to paint the press before CPU-bound work competes with it for the GIL.

        Bounded by :data:`PAINT_WAIT`. A body running on the main thread itself (a test's inline thread) cannot wait
        for the thread it is blocking, so it never waits.
        """
        if threading.current_thread() is not threading.main_thread():
            self.painted.wait(PAINT_WAIT)


class PreparationMessage:
    """What the worker tells the panel. Exactly one non-progress message per preparation, always its last."""

    __slots__ = ("preparation", "kind", "text", "detail", "warning", "done", "total")

    def __init__(self, preparation: Preparation, kind: str, *, text: str = "", detail: str = "",
                 warning: bool = False, done: int = 0, total: int = 0) -> None:
        self.preparation = preparation
        self.kind = kind
        self.text = text
        self.detail = detail
        self.warning = warning
        self.done = done
        self.total = total


def prepare(preparation: Preparation, post: Callable[[PreparationMessage], object], *,
            reserve: Callable[[], Any],
            build: Callable[[Any, Callable[[int, int], None]], Any],
            release: Callable[[Any], object],
            refusal: Callable[[BaseException], Refusal | None]) -> None:
    """The preparation worker's whole body. Never raises; touches no widget.

    *reserve* takes what the operation writes into (a run reservation, a validated custom folder and its owned work
    area) and returns it; *build* plans from it, told a progress callable, and returns the result to offer; *release*
    gives back what *reserve* took, only ever while nothing has been written into it; *refusal* turns a tool's own
    exception into a :class:`Refusal` (``None`` for anything that is not one, which then ends as a fault). Each may
    call :meth:`Preparation.checkpoint`.

    The last message is always exactly one ending -- prepared, cancelled, refused or fault -- and whatever this
    preparation reserved but did not hand over is released *before* that message is posted, so the panel never sees
    an ending while something of this press is still held.
    """
    holding: Any = None
    held = False
    ending: PreparationMessage | None = None
    last = [float("-inf")]

    def progress(done: int, total: int) -> None:
        # At most one message per PROGRESS_INTERVAL, plus the first and the last: thousands of one-track Books must
        # not become thousands of status repaints on Tk.
        now = time.monotonic()
        if done in (0, total) or now - last[0] >= PROGRESS_INTERVAL:
            last[0] = now
            post(PreparationMessage(preparation, PROGRESS, done=done, total=total))

    try:
        preparation.wait_until_painted()
        preparation.checkpoint()
        holding = reserve()
        held = True
        result = build(holding, progress)
        if preparation.offer(result):
            held = False  # the panel owns it now
            ending = PreparationMessage(preparation, PREPARED)
        else:
            ending = PreparationMessage(preparation, CANCELLED)
    except ConversionCancelled:
        ending = PreparationMessage(preparation, CANCELLED)
    except BaseException as exc:  # noqa: BLE001 - deliberately everything: the panel must hear an ending
        try:
            refused = exc if isinstance(exc, Refusal) else refusal(exc)
        except Exception:  # noqa: BLE001 - a broken mapping is a fault, not a reason to go silent
            refused = None
        if refused is not None:
            ending = PreparationMessage(preparation, REFUSED, text=refused.text, detail=refused.detail,
                                        warning=refused.warning)
        else:
            ending = PreparationMessage(
                preparation, FAULT,
                text=f"{preparation.label}: the job could not be prepared, and nothing was started.",
                detail=f"{type(exc).__name__}: {exc}")
    finally:
        if held:
            try:
                release(holding)
            except Exception:  # noqa: BLE001 - releasing is best effort; the ending must still go
                pass
        post(ending if ending is not None else PreparationMessage(
            preparation, FAULT, text=f"{preparation.label}: the job could not be prepared.",
            detail="the preparation ended without a result"))
