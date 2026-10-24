"""The one TTS output filename policy: ``<source-stem>-<frozen display label>.mp3`` (v0.7.0 P02B).

Every narration route names its file the same way: Edge direct and folder, Kokoro, Chatterbox, Qwen3 presets and
clones, and the standalone ``batch_convert`` helper. The label is the one the run froze when it was accepted, so a
renamed or reordered registry cannot move an existing run or its retry. Nothing here chooses an engine, model,
reference recording or transcript; a label only ever becomes text in a file name. No backend or voice-id suffix is
added: a clash is resolved by the shared planner's ``stem-1.mp3`` numbering, never by a longer name.

What is TTS-local, on top of :mod:`shared.output_paths` (whose sanitiser and :class:`DestinationPlanner` still decide
the final path):

* the stem and the label are cleaned **separately**, so a separator inside a label (``AC/DC``) becomes ``_`` rather
  than cutting the name down to its last element;
* a Windows device name is also caught before the *first* dot (``nul.backup-Label.mp3``), not only the last;
* the name is kept short enough for the shared collision suffix and the longest temporary name an engine publishes
  through, both in its own component and in the whole path when the platform limits that. Only the source stem is
  shortened, from its end, and only as far as needed. A label that cannot fit is refused before anything is
  synthesised, never cut and never written somewhere else.
"""

from __future__ import annotations

import functools
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from shared import output_paths

#: Every narration route writes MP3.
EXTENSION = ".mp3"
#: Between the source stem and the label.
SEPARATOR = "-"
#: Room for the shared planner's longest collision suffix (``-10000``).
COLLISION_HEADROOM = len(f"-{output_paths.MAX_COLLISION_ATTEMPTS}")
#: Room for the longest temporary sibling an engine publishes through: Qwen3's ``.<8 hex>.part`` (Chatterbox uses
#: ``.partial``). The finished file is renamed onto the planned name, so its temporary name must fit too.
PUBLISH_HEADROOM = len(".0123abcd.part")
#: The longest single name NTFS, APFS and ext4 accept.
COMPONENT_LIMIT = output_paths.MAX_COMPONENT_LENGTH
#: Windows without long-path support: MAX_PATH less its terminating NUL, and the shorter limit CreateDirectory has.
WINDOWS_PATH_LIMIT = 259
WINDOWS_DIRECTORY_LIMIT = 247
#: macOS PATH_MAX less its NUL (Linux allows more; the stricter value keeps one policy).
POSIX_PATH_LIMIT = 1023


class OutputNameError(output_paths.OutputPathError):
    """No safe file name fits this destination. Raised while planning, before any synthesis."""


@dataclass(frozen=True)
class NameBudget:
    """How long a name may be where it is going. Tests pass one explicitly; :func:`current_budget` reads the machine."""

    #: Longest full path, in platform units, or ``None`` when the platform has no practical limit.
    path_limit: int | None
    #: Longest folder path that can still be created, or ``None``.
    directory_limit: int | None
    #: ``True`` counts UTF-16 code units (Windows); ``False`` counts UTF-8 bytes (macOS/Linux).
    windows: bool
    component_limit: int = COMPONENT_LIMIT

    def units(self, text: str) -> int:
        if self.windows:
            return len(text.encode("utf-16-le", "surrogatepass")) // 2
        return len(text.encode("utf-8", "surrogateescape"))


@functools.lru_cache(maxsize=1)
def long_paths_enabled() -> bool:
    """Whether this Windows process may use paths beyond MAX_PATH. ``False`` whenever it cannot be proved."""
    if os.name != "nt":
        return False
    try:
        import ctypes

        check = ctypes.WinDLL("ntdll").RtlAreLongPathsEnabled
        check.restype = ctypes.c_ubyte
        check.argtypes = []
        return bool(check())
    except (OSError, AttributeError):
        return False


def current_budget() -> NameBudget:
    """This machine's limits: Windows counts UTF-16 units and limits the path unless long paths are on."""
    if os.name == "nt":
        if long_paths_enabled():
            return NameBudget(path_limit=None, directory_limit=None, windows=True)
        return NameBudget(path_limit=WINDOWS_PATH_LIMIT, directory_limit=WINDOWS_DIRECTORY_LIMIT, windows=True)
    return NameBudget(path_limit=POSIX_PATH_LIMIT, directory_limit=POSIX_PATH_LIMIT, windows=False)


def clean_part(text: str) -> str:
    """One half of a name made safe on its own: NFC, controls dropped, forbidden characters and separators as ``_``.

    Spaces, punctuation such as parentheses, and any legal Unicode are kept as written. An unpaired surrogate cannot
    be stored or logged, so it becomes ``_`` as well.
    """
    value = unicodedata.normalize("NFC", "" if text is None else str(text))
    kept = []
    for ch in value:
        category = unicodedata.category(ch)
        if category == "Cc":
            continue
        kept.append("_" if ch in output_paths._FORBIDDEN_CHARS or category == "Cs" else ch)
    return "".join(kept).strip()


def _guard_device_name(stem: str) -> str:
    """Prefix ``_`` when Windows would read the finished name as a device (``nul.backup-…``, ``COM1 .x-…``).

    Windows looks at what precedes the *first* dot. Without a dot in the stem that is ``<stem>-<label>``, which no
    device name contains, so ``CON-Label.mp3`` is legal and kept as written.
    """
    if "." not in stem:
        return stem
    head = stem.split(".", 1)[0].rstrip(" ")
    if head.upper() in output_paths._RESERVED_NAMES:
        return f"_{stem}"
    return stem


def _parts(source, label) -> tuple[str, str]:
    stem = clean_part(Path(source).stem) or output_paths.FALLBACK_COMPONENT
    label_part = clean_part(label)
    if not label_part:
        raise OutputNameError(
            "the voice has no usable name for an output file; give it a visible label in tts/voice_registry.py",
            f"label={label!r}",
        )
    return _guard_device_name(stem), label_part


def canonical_name(source, label: str) -> str:
    """``<stem>-<label>.mp3`` with both halves cleaned and nothing shortened."""
    stem, label_part = _parts(source, label)
    return f"{stem}{SEPARATOR}{label_part}{EXTENSION}"


def planned_name(source, label: str, directory, *, budget: NameBudget | None = None) -> str:
    """The name *source* narrated as *label* takes inside *directory*, shortened only if it must be.

    Room is left for the collision suffix and the engines' temporary publish names. Only the source stem is
    shortened, from its end, so the label stays whole. Raises :class:`OutputNameError` when even a one-character
    stem cannot fit, or when *directory* itself is beyond what can be created.
    """
    budget = current_budget() if budget is None else budget
    stem, label_part = _parts(source, label)
    tail = f"{SEPARATOR}{label_part}{EXTENSION}"
    headroom = COLLISION_HEADROOM + PUBLISH_HEADROOM
    allowed = budget.component_limit - headroom
    if budget.path_limit is not None:
        folder = str(Path(directory))
        if budget.directory_limit is not None and budget.units(folder) > budget.directory_limit:
            raise OutputNameError(
                "the output folder path is too long to hold a narrated file; choose a shorter output location "
                "or a less deeply nested source folder",
                f"{budget.units(folder)} > {budget.directory_limit} units: {folder}",
            )
        allowed = min(allowed, budget.path_limit - budget.units(folder) - 1 - headroom)
    room = allowed - budget.units(tail)
    if budget.units(stem) > room:
        cut = ""
        for ch in stem:
            if budget.units(cut + ch) > room:
                break
            cut += ch
        stem = cut.rstrip(" ") or cut
    if not stem:
        shown = label_part if len(label_part) <= 60 else f"{label_part[:57]}..."
        raise OutputNameError(
            f"the voice name {shown!r} is too long to fit in an output file name here; shorten the voice label "
            "or choose a shorter output location",
            f"allowed={allowed} units, label part={budget.units(tail)} units, directory={directory}",
        )
    return f"{stem}{tail}"


#: The placeholder the folder-finding pass of :func:`plan_named` reserves; it never leaves that pass.
_PROBE_NAME = f"probe{EXTENSION}"


def plan_named(plan_function, root, *args, label: str, planner, budget: NameBudget | None = None):
    """Run one shared ``plan_flat``/``plan_mirrored``/``plan_multi_root`` with TTS names.

    The shared planners hand a rename callback only the source, but a name's length budget depends on the folder it
    lands in. So a first pass on a throwaway tracker (no disk check, nothing reserved in *planner*) learns each
    source's folder through the very same planner, and the real pass reserves each name in *planner*. A source path
    always lands in the same folder within one plan, so keying the folders by source is exact.
    """
    root = Path(root)
    budget = current_budget() if budget is None else budget
    probe = plan_function(root, *args, planner=output_paths.DestinationPlanner(root, check_filesystem=False),
                          rename=lambda source: _PROBE_NAME)
    folders = {item.source: item.destination.parent for item in probe.items}
    return plan_function(root, *args, planner=planner,
                         rename=lambda source: planned_name(source, label, folders[source], budget=budget))
