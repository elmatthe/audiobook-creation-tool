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

#: Names the one thread that runs the collections dropped requests are owed. It belongs to no request, so it is not one of theirs.
_COLLECTOR_THREAD_NAME = "act-dropped-requests-collector"

#: How many times, and how far apart, that thread tries for a collection of its own while another thread's is under way: 30 s in
#: all. Only a finalizer that blocks can make it wait that long, and then it goes, so that it can never stay.
_COLLECTION_LOOKS = 1500
_COLLECTION_LOOK_SECONDS = 0.02

#: How long that thread stands aside after each collection. A collection holds up every other thread, so the requests it held up
#: have not yet had a turn to say they were dropped; start the next at once and it covers few of them. Eight workers on a heap
#: like a full run's cost three collections and 3.6-3.7 s without this pause, two and 2.7-2.8 s with it (measured). This buys
#: sharing, never correctness: a drop it misses is covered by the next collection.
_COLLECTION_GATHER_SECONDS = 0.1

#: What dropped requests are owed, as numbers rather than a queue: each drop takes the next number, and a collection that began
#: after a drop covers that number and every one before it. Guards the three below and is never held across a collection.
_collections = threading.Condition()
_drops = 0
_drops_covered = 0
_collector_running = False


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
    ``with`` blocks so that a partial file it holds is let go, and a collection that begins after that closes the sockets it held
    (:func:`_collect_dropped`). An asynchronous generator left open gets the same deadline: past it, its cleanup is cancelled and
    then dropped.
    Nothing is claimed that was not seen: ``note`` is told about anything that had to be dropped, about a generator's cleanup
    that was cut short, about a collection that could not be set going, and about any blocking call still under way on an
    executor thread, which Python cannot interrupt. Such a call makes no further request, its answer goes nowhere and its thread
    ends when the operating system answers; closing the application waits for that thread.

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
    collection_on_its_way = True
    if refused or cleanup_dropped:
        # The dropped tasks' sockets are closed when they are collected; do not leave that to chance.
        collection_on_its_way = _collect_dropped(remaining())
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
    if not collection_on_its_way:
        _say(note, "A dropped network request may keep its connection open for now, because the program could not start a thread "
                   "to release it, usually for lack of memory. It closes later, at the latest when the application closes.")


def _collect_dropped(wait_seconds: float) -> bool:
    """See to it that a full collection begins after this call, and wait up to ``wait_seconds`` for it to end. ``False`` if no
    thread could be started for one, so that nothing is on its way.

    Something a dropped request holds in a reference cycle, as a real client's session and connection are, is released by nothing
    else. But a full collection costs the whole process's heap (0.33-0.45 s on a full run's), every other thread waits while it
    runs, and one for each request made eight workers' Cancel wait for up to eight in a row. So requests dropped together share:
    a collection covers whatever was dropped before it began, and only that, since it chose its garbage when it began. Whatever is
    dropped while it runs is covered by the next, however many they are.

    They run on one thread that exists only while something is owed, so a finalizer that blocks holds that thread and not a Cancel.
    A caller that stops waiting leaves its number on the account and is still covered. What no wait can shorten is a collection
    already running: it holds the interpreter, and with it every thread here, until it ends or a finalizer lets go.

    No collection ever runs on the caller, even when the thread cannot be started. A collection has no deadline and cannot be
    stopped, so one here could hold the Cancel for as long as a finalizer liked (measured), and Cancel comes first. So that case
    costs the connection instead: the number stays owed and ``False`` comes back, because nothing is on its way. The next drop that
    gets a thread covers it; until then only the interpreter's own collections, or the process's end, can release what it held.
    """
    global _drops, _collector_running
    with _collections:
        _drops += 1
        mine = _drops
        start = not _collector_running
        _collector_running = True
    if start:
        try:
            threading.Thread(target=_collect_what_is_owed, name=_COLLECTOR_THREAD_NAME, daemon=True).start()
        except (RuntimeError, MemoryError):  # no room for a thread, or the interpreter is going away
            with _collections:
                _collector_running = False
            return False
    # This runs in run_request's ``finally``, so it must not replace the outcome. A wait allocates a lock, and memory can refuse
    # that too; the collection does not depend on anyone waiting for it.
    with contextlib.suppress(RuntimeError, MemoryError), _collections:
        _collections.wait_for(lambda: _drops_covered >= mine, wait_seconds)
    return True


def _collect_what_is_owed() -> None:
    """The collector thread: one full collection at a time until nothing is owed, then gone. Starting afresh is a later drop's job."""
    global _drops_covered, _collector_running
    try:
        looks_left = _COLLECTION_LOOKS
        pause = threading.Event()
        while True:
            with _collections:
                covering = _drops  # read before the collection begins: it covers these and perhaps more, never fewer
                if not looks_left or covering == _drops_covered:
                    _collector_running = False  # in one step with that look: a drop after this one starts another thread
                    return
            if _a_full_collection_began():
                looks_left = _COLLECTION_LOOKS
                with _collections:
                    _drops_covered = covering
                    _collections.notify_all()
                pause.wait(_COLLECTION_GATHER_SECONDS)
            else:
                looks_left -= 1
                pause.wait(_COLLECTION_LOOK_SECONDS)
    except BaseException:  # above all MemoryError, at any step: this thread must not die holding its place
        with _collections:
            _collector_running = False  # what is owed stays owed, and a later drop starts another thread
        raise  # to threading.excepthook: not hidden


def _a_full_collection_began() -> bool:
    """Ask for a full collection and say whether one really began; when this returns ``True`` it has also ended.

    While a collection is under way on another thread ``gc.collect()`` does nothing and returns 0 (measured: at once), and 0 is
    also what it returns having found nothing. That other collection chose its garbage too early to count, so the only report to
    trust is the interpreter's own that a collection began on this thread.
    """
    this_thread = threading.get_ident()
    began: list[bool] = []

    def watch(phase: str, info: dict) -> None:
        if phase == "start" and info["generation"] == 2 and threading.get_ident() == this_thread:
            began.append(True)

    gc.callbacks.append(watch)
    try:
        gc.collect()
    finally:
        gc.callbacks.remove(watch)
    return bool(began)


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
