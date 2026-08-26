"""The one number a run has to earn.

Three different numbers appear in a Converter run and Decision 5 keeps them
apart. Two of them are **structural**: a split output's filename prefix and its
``track`` are both the segment's position inside its own book, frozen into the
``ConversionPlan`` before anything is written, identical on every attempt, and
untouched by whether any other book succeeded. Neither of them lives here.

The third does live here, and it is the only one that interacts with success:
the optional sequential ``track`` a **whole book** carries when *Auto-number
tracks* is on. Decision 21A says it must not be pre-assigned, and 28A says the
result must have no gaps — so if the second of three books fails, the third is
number **2**, not 3.

**Why the API is shaped like this.** The number has to exist *before* ffmpeg
runs, because it is encoded into the file's metadata; but it must not count
until the file actually exists. Those are two different events, so they are two
different calls. :meth:`SuccessNumbers.propose` reads the next value and
advances nothing — asking is free, and asking twice is the same answer.
:meth:`SuccessNumbers.commit` is the only thing that moves the counter, it takes
the token it is confirming, and it refuses one that has already been spent. So
"forgot to commit" costs a number nothing, and "committed twice" is an error
rather than a silent skipped number.

**Why this state is not in the plan.** ``ConversionPlan`` is immutable and is
what a retry re-reads; a success counter is the opposite of that — it is a fact
about one attempt's execution, discovered while it runs. Keeping it out of the
plan is what lets the plan stay retry-stable.

Pure: integers in, integers out. No Tk, no filesystem, no ffmpeg, no metadata
vocabulary, no controller, no paths, and no knowledge of what a book is.
"""

from __future__ import annotations

from dataclasses import dataclass


class NumberingError(RuntimeError):
    """A number was confirmed that this counter had not offered."""


@dataclass(frozen=True, slots=True)
class Tentative:
    """One attempt's proposed number. Worth nothing until it is earned.

    Deliberately a value rather than a bare ``int``: handing :meth:`commit` the
    token it issued is what lets it tell "this attempt succeeded" from "somebody
    passed a number in".
    """

    number: int


class SuccessNumbers:
    """The whole-book sequential counter, advanced only by a completed success.

    Created once per run attempt, from the frozen ``start_number``. A run with
    *Auto-number tracks* off never creates one at all.
    """

    __slots__ = ("_start", "_next", "_consumed")

    def __init__(self, start: int) -> None:
        if isinstance(start, bool) or not isinstance(start, int):
            raise TypeError(f"start must be an int, got {type(start).__name__}")
        # Deliberately not clamped or defaulted here. What counts as a usable
        # Start # was already decided when the run was frozen; re-deciding it in
        # a second place is how two answers to one question appear.
        self._start = start
        self._next = start
        self._consumed = 0

    @property
    def start(self) -> int:
        """The frozen ``Start #`` this run began from."""
        return self._start

    @property
    def next_number(self) -> int:
        """What the next success will be given. Reading it changes nothing."""
        return self._next

    @property
    def consumed(self) -> int:
        """How many books have actually succeeded so far."""
        return self._consumed

    def propose(self) -> Tentative:
        """The number this attempt would carry. **Advances nothing.**

        Safe to call repeatedly for the same item: until something commits, the
        answer does not move.
        """
        return Tentative(self._next)

    def commit(self, tentative: Tentative) -> int:
        """Confirm that *tentative* was earned, and advance exactly once.

        Refuses a token this counter is not currently offering — which is what
        makes committing the same attempt twice an error rather than a silently
        skipped number.
        """
        if not isinstance(tentative, Tentative):
            raise TypeError(
                f"commit takes the Tentative it issued, got {type(tentative).__name__}")
        if tentative.number != self._next:
            raise NumberingError(
                f"{tentative.number} is not the number on offer ({self._next}); "
                "a tentative number may be confirmed once and only by the "
                "attempt it was issued for")
        consumed = self._next
        self._next += 1
        self._consumed += 1
        return consumed

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"SuccessNumbers(start={self._start}, next={self._next}, "
                f"consumed={self._consumed})")
