"""How one Edge request answers to Cancel (v0.7.2).

A conversion's request to the voice service, and the waits around it, end promptly on Cancel whatever the service or the
client library is doing. Only the Edge routes need this, so it lives here and not in :mod:`shared.cancellation`, the small
primitive every tool imports, whose names and imports are pinned (``test_plan3_boundaries``).
"""

from __future__ import annotations

import asyncio
import contextlib
import gc
import itertools
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Awaitable, Callable, Coroutine, Optional, TypeVar

from shared.cancellation import CancelCheck, ConversionCancelled, raise_if_cancelled

T = TypeVar("T")

#: How often a wait or an awaited request looks at its cancel check: the same look the FFmpeg watchdog takes.
CANCEL_POLL_SECONDS = 0.25

#: How long a cancelled request gets to stop each time it is asked; it is asked twice (:func:`run_request`). aiohttp's polite
#: close of a WebSocket waits 10 s for the far end, and a second cancellation is what aborts that wait (measured: 10.04 s on
#: the real client without it). A request that is not waiting for anything stops at once (measured: 0.01-0.04 s).
REQUEST_STOP_SECONDS = 1.0

#: Names the threads of a request's executor, so the ones still blocked at shutdown can be found with public APIs.
_REQUEST_THREAD_PREFIX = "act-request"
_request_numbers = itertools.count(1)


def wait_unless_cancelled(seconds: float, cancel_check: CancelCheck, *, step: float = CANCEL_POLL_SECONDS,
                          message: str = "Conversion cancelled by user.") -> None:
    """Sleep for ``seconds``, looking at ``cancel_check`` every ``step``; a Cancel ends the sleep at once with
    :class:`ConversionCancelled` (v0.7.2).

    A back-off between two attempts, a pause between two chunks: none of them may keep a cancelled conversion alive.
    ``cancel_check`` of ``None`` is one plain ``time.sleep(seconds)``. With a check, the wait is ``time.sleep`` in slices of
    ``step``, counted down from ``seconds`` rather than from the clock, so a test that replaces ``time.sleep`` sees the whole
    schedule and nothing spins.
    """
    raise_if_cancelled(cancel_check, message)
    remaining = max(0.0, float(seconds))
    if cancel_check is None:
        if remaining:
            time.sleep(remaining)
        return
    while remaining > 0:
        slice_ = min(step, remaining)
        time.sleep(slice_)
        remaining -= slice_
        raise_if_cancelled(cancel_check, message)


async def await_unless_cancelled(awaitable: Awaitable[T], cancel_check: CancelCheck, *, poll: float = CANCEL_POLL_SECONDS,
                                 stop_seconds: float = REQUEST_STOP_SECONDS, message: str = "Conversion cancelled by user.") -> T:
    """Await ``awaitable`` while looking at ``cancel_check`` every ``poll`` seconds (v0.7.2).

    A Cancel cancels the task, gives it ``stop_seconds`` to finish (an in-flight network request is closed by its own library's
    cleanup) and raises :class:`ConversionCancelled` whether or not it has; a task can delay or swallow a cancellation for as
    long as it likes, and Cancel must not wait for it (P1-R02). What becomes of a task still going is :func:`run_request`'s
    business, and that is what must drive this. The task's own result or exception is otherwise returned or raised as if
    awaited directly. ``cancel_check`` of ``None`` is a plain ``await``.
    """
    task = asyncio.ensure_future(awaitable)
    if cancel_check is None:
        return await task
    try:
        while True:
            done, _pending = await asyncio.wait({task}, timeout=poll)
            if done:
                return task.result()
            if cancel_check():
                task.cancel()
                await asyncio.wait({task}, timeout=stop_seconds)
                if task.done() and not task.cancelled():
                    task.exception()  # retrieved: whatever the abandoned request raised, the answer is Cancel
                raise ConversionCancelled(message)
    except BaseException:
        if not task.done():
            task.cancel()
        raise


def run_request(main: Coroutine[object, object, T], *, stop_seconds: float = REQUEST_STOP_SECONDS,
                note: Optional[Callable[[str], object]] = None) -> T:
    """``asyncio.run`` for one network request of a conversion that can be cancelled: the same loop, a bounded end (v0.7.2).

    ``asyncio.run`` finishes by cancelling whatever is left on the loop and waiting for it with no limit, then waiting up to
    300 s for the loop's executor threads, and a name lookup in progress is one. Either would hold up a Cancel: a request that
    swallows a cancellation hung it for good (review finding P1-R02). Here the end costs ``stop_seconds``, plus a last 0.05 s
    for each step still waiting when that has run out.

    A task that has still not stopped is dropped. That stops it for good and does not leave it running somewhere: a coroutine
    only ever runs when its loop runs it, and this loop is closed. Its coroutine is closed too, which runs its ``finally`` and
    ``with`` blocks so that a partial file it holds is let go, and the collection that follows closes the sockets it held. An
    asynchronous generator left open gets the same deadline: past it, its cleanup is cancelled and then dropped.
    Nothing is claimed that was not seen: ``note`` is told about anything that had to be dropped, about a generator's cleanup
    that was cut short, and about any blocking call still under way on an executor thread, which Python cannot interrupt. Such
    a call makes no further request, its answer goes nowhere and its thread ends when the operating system answers; closing the
    application waits for that thread.

    A request that finishes is unchanged: its result or exception comes back as from ``asyncio.run``, nothing is said.
    """
    prefix = f"{_REQUEST_THREAD_PREFIX}-{next(_request_numbers)}"
    loop = asyncio.new_event_loop()
    loop.set_default_executor(ThreadPoolExecutor(thread_name_prefix=prefix))
    try:
        return loop.run_until_complete(main)
    finally:
        _shut_down(loop, prefix, stop_seconds, note)


def _shut_down(loop: asyncio.AbstractEventLoop, prefix: str, stop_seconds: float, note) -> None:
    """Everything after the request's own end, sharing one deadline. See :func:`run_request`."""
    deadline = time.monotonic() + stop_seconds

    def remaining() -> float:
        return max(0.05, deadline - time.monotonic())

    try:
        refused = _end_tasks(loop, asyncio.all_tasks(loop), remaining)
        cut_short, cleanup_dropped = _close_generators(loop, remaining)
    finally:
        loop.close()  # also tells the executor to stop, without waiting for it
    if refused or cleanup_dropped:
        gc.collect()  # the dropped tasks' sockets are closed when they are collected; do not leave that to chance
    threads = [thread for thread in threading.enumerate() if thread.name.startswith(f"{prefix}_")]
    for thread in threads:
        thread.join(remaining())
    if refused:
        _say(note, "A network request did not stop when it was cancelled, so it was abandoned: none of it runs any more and "
                   "nothing of it is used.")
    if cut_short:
        _say(note, "A network request's cleanup did not finish in time, so it was cut short: none of it runs any more and "
                   "nothing of it is used.")
    if any(thread.is_alive() for thread in threads):
        _say(note, "A cancelled network request left a call still waiting for the operating system, usually a name lookup. "
                   "Nothing is waiting for it and its answer is ignored.")


def _end_tasks(loop: asyncio.AbstractEventLoop, tasks, remaining: Callable[[], float]) -> bool:
    """Cancel ``tasks``, wait for them until the deadline and drop whatever has not ended. ``True`` if anything was dropped."""
    if not tasks:
        return False
    for task in tasks:
        task.cancel()
    done, still_going = loop.run_until_complete(asyncio.wait(tasks, timeout=remaining()))
    for task in done:
        if not task.cancelled():
            task.exception()  # retrieved: the answer was settled before this shutdown began
    if still_going:
        # What asyncio would print when a dropped task is collected is said once, in words, by the caller.
        loop.set_exception_handler(lambda _loop, _context: None)
    for task in still_going:
        with contextlib.suppress(Exception):  # "coroutine ignored GeneratorExit": it had its chance
            task.get_coro().close()
    return bool(still_going)


def _close_generators(loop: asyncio.AbstractEventLoop, remaining: Callable[[], float]) -> tuple[bool, bool]:
    """``loop.shutdown_asyncgens()`` within the deadline: (a generator's cleanup was cut short, something had to be dropped).

    A cleanup that outlasts the deadline would otherwise leave this task, and one for each generator, pending on a closed loop,
    with nothing said until asyncio's "Task was destroyed" when they are collected. So they are ended like anything else left
    on the loop: cancelled, given what is left of the deadline, then dropped.
    """
    closing = loop.create_task(loop.shutdown_asyncgens())
    loop.run_until_complete(asyncio.wait({closing}, timeout=remaining()))
    if not closing.done():
        return True, _end_tasks(loop, asyncio.all_tasks(loop), remaining)
    if not closing.cancelled():
        closing.exception()  # retrieved
    return False, False


def _say(note, text: str) -> None:
    if note is not None:
        with contextlib.suppress(Exception):  # a report must never replace the outcome it reports on
            note(text)
