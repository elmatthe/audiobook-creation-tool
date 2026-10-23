"""audio_tail.py — the one final-tail policy for finished narration PCM (ACT v0.7.0, owner decisions Q1-Q3).

A narration ends with its last sound: no deliberate closing pause, at most ~300 ms of trailing near-silence, and no
final phoneme, breath, decay or transient cut. Pauses *between* rendered chunks are the engines' business and are
never touched here; this module only ever shortens the terminal suffix of the finished PCM, immediately before the
route's one final MP3 encode. It never removes leading or internal silence, never deletes a fixed duration, and never
normalises, denoises, resamples or changes speed.

The rule (calibrated in P01A on synthetic PCM and earlier real outputs; ``files/dev-work/act070-remediation/audio/``):

* 10 ms windows, every channel separately (a downmix can cancel a quiet channel); a window is sound when its RMS
  **or** its peak reaches the threshold (RMS alone misses a short click).
* The nominal end is the last sound window at -60 dBFS. At least 150 ms after it is always kept.
* The conservative end is the same measurement at -70 dBFS. Retention reaches at least that far too, so a quiet
  decay or breath that -60 dBFS no longer sees is never cut.
* A suffix that is already shorter than that is left exactly as it is (nothing is padded).
* If no window reaches -60 dBFS at all, nothing is cut: there is no evidence of where the sound ends.

When the conservative end lies more than 300 ms past the nominal end, the policy keeps it all and says so
(``FinalTail.uncertain``) rather than clip a sound: the caller logs it and the ending needs listening. Thresholds are
measurement candidates, not proof that amplitude identifies speech; owner listening stays the acceptance test.

Pure numpy, no I/O, no model imports: importing it costs nothing for the engines that use it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

WINDOW_MS = 10
NOMINAL_THRESHOLD_DBFS = -60.0
CONSERVATIVE_THRESHOLD_DBFS = -70.0
KEEP_MS = 150
BUDGET_MS = 300

# The tail is searched backwards in blocks this long, so a whole-book array is never converted at once.
_SCAN_BLOCK_WINDOWS = 3000  # 30 s at 10 ms


def _frames(pcm: np.ndarray) -> tuple[np.ndarray, float]:
    """``pcm`` as (frames, channels) without copying, plus its full-scale value. Frames always come first."""
    arr = np.asarray(pcm)
    if arr.ndim not in (1, 2):
        raise ValueError(f"expected mono or (frames, channels) PCM, got shape {arr.shape}")
    if np.issubdtype(arr.dtype, np.integer):
        full_scale = float(-np.iinfo(arr.dtype).min)
    elif np.issubdtype(arr.dtype, np.floating):
        full_scale = 1.0
    else:
        raise ValueError(f"unsupported PCM sample type {arr.dtype}")
    return (arr if arr.ndim == 2 else arr[:, np.newaxis]), full_scale


def last_sound(pcm: np.ndarray, sample_rate: int, threshold_dbfs: float = NOMINAL_THRESHOLD_DBFS) -> int:
    """The sample index just after the last window, on any channel, whose RMS or peak reaches ``threshold_dbfs``.

    0 means no window reaches it. Windows are aligned to the start of ``pcm`` (the last one may be shorter).
    """
    frames, full_scale = _frames(pcm)
    n = frames.shape[0]
    if n == 0:
        return 0
    win = max(1, int(round(sample_rate * WINDOW_MS / 1000)))
    level = 10 ** (threshold_dbfs / 20)
    end = n
    while end > 0:
        start = max(0, (end - win * _SCAN_BLOCK_WINDOWS) // win * win)
        block = frames[start:end].astype(np.float64) / full_scale
        starts = np.arange(0, end - start, win)
        counts = np.diff(np.append(starts, end - start))
        latest = 0
        for ch in range(block.shape[1]):
            col = block[:, ch]
            active = np.add.reduceat(col * col, starts) / counts >= level * level
            active |= np.maximum.reduceat(np.abs(col), starts) >= level
            hits = np.nonzero(active)[0]
            if hits.size:
                latest = max(latest, start + int(starts[hits[-1]] + counts[hits[-1]]))
        if latest:
            return latest
        end = start
    return 0


@dataclass(frozen=True)
class FinalTail:
    """The kept PCM and the facts behind the cut, for the run log and the evidence records."""

    pcm: np.ndarray  # a prefix of the input, same dtype, rate and channel layout
    sample_rate: int
    original_samples: int
    nominal_end: int  # last sound at -60 dBFS (0: none found)
    conservative_end: int  # last sound at -70 dBFS

    @property
    def removed_samples(self) -> int:
        return self.original_samples - len(self.pcm)

    @property
    def tail_ms(self) -> float:
        """Trailing near-silence left after the nominal end."""
        return (len(self.pcm) - self.nominal_end) * 1000.0 / self.sample_rate

    @property
    def uncertain(self) -> bool:
        """Nothing identifiable as sound, or quiet sound kept beyond the budget: the ending needs listening."""
        return self.nominal_end == 0 or self.tail_ms > BUDGET_MS

    def summary(self) -> str:
        before = (self.original_samples - self.nominal_end) * 1000.0 / self.sample_rate
        if self.nominal_end == 0:
            return (f"Final tail: no sound reached {NOMINAL_THRESHOLD_DBFS:.0f} dBFS, so the ending was left "
                    f"unchanged; please listen to it.")
        if self.uncertain:
            return (f"Final tail: quiet sound continues {self.tail_ms / 1000:.2f} s after the last clearly audible "
                    f"sound; kept in full (over the {BUDGET_MS / 1000:.2f} s target); please listen to the ending.")
        if self.removed_samples:
            return (f"Final tail: {before / 1000:.2f} s of trailing near-silence shortened to "
                    f"{self.tail_ms / 1000:.2f} s.")
        return f"Final tail: {self.tail_ms / 1000:.2f} s of trailing near-silence; nothing removed."


def apply_final_tail_policy(pcm: np.ndarray, sample_rate: int) -> FinalTail:
    """Shorten only the terminal near-silent suffix of finished narration PCM, per the module rule."""
    frames, _scale = _frames(pcm)
    n = frames.shape[0]
    nominal = last_sound(pcm, sample_rate, NOMINAL_THRESHOLD_DBFS)
    if nominal == 0:
        return FinalTail(np.asarray(pcm), int(sample_rate), n, 0, last_sound(pcm, sample_rate,
                                                                                CONSERVATIVE_THRESHOLD_DBFS))
    conservative = last_sound(pcm, sample_rate, CONSERVATIVE_THRESHOLD_DBFS)
    keep = int(round(sample_rate * KEEP_MS / 1000))
    cut = min(n, max(nominal + keep, conservative))
    return FinalTail(np.asarray(pcm)[:cut], int(sample_rate), n, nominal, conservative)
