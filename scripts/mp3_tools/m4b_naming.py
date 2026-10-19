"""Turning one source chapter title into one safe split-output filename.

**Why this is its own module.** ``m4b_chapters`` is deliberately stdlib-only — a
pure value/geometry layer with no dependency on anything shared, and a guard that
keeps it that way. Naming is a different concern: it is about what the filesystem
will accept, and it must consume the repository's existing
:func:`shared.output_paths.sanitize_component`. Keeping the two apart lets the
chapter layer stay dependency-free instead of loosening its purity guard to make
room for a filename.

**Why the seam has two stages, in this order.** ``sanitize_component`` treats
``/`` and ``\\`` as *path hierarchy* and reduces anything path-like to its last
element — correct for a path argument, wrong for a metadata title, which is one
component that merely happens to contain slashes. Handing it a real chapter title
directly is silently destructive:

    sanitize_component("1 — There is no food here / Meg ate all the "
                       "Swedish Fish / Please get off my hearse")
    -> "Please get off my hearse"

Two thirds of the title, gone, with no error. So stage 1 rewrites separators into
visible punctuation *first*, and only then does stage 2 hand a genuine single
component to the shared sanitiser. That ordering is the whole point of this
module, and the regression test for it uses the real title above.

**Nothing about filename safety is implemented here.** Forbidden characters,
Windows reserved device names, control characters, NFC normalisation, trailing
dots and spaces, the 255-character cap and extension preservation all belong to
``sanitize_component`` and are consumed unchanged. This module owns exactly two
things the shared helper cannot know about: that a metadata title is not a path,
and how a split output is numbered.

Pure: strings in, strings out. No filesystem, no ``Path``, no media, no Tk.
"""

from __future__ import annotations

from shared.output_paths import sanitize_component

#: Characters that mean "hierarchy" to a path parser but are ordinary punctuation
#: inside a chapter title. Slashes become a visible separator so the text on both
#: sides survives; NUL is simply removed, since it cannot be displayed and cannot
#: appear in a filename on any supported platform.
_SEPARATORS = {
    "/": " - ",
    "\\": " - ",
    "\x00": "",
}

#: The extension every split output carries.
_EXTENSION = ".mp3"

#: Minimum zero-padding for the order prefix. Two digits is the floor so a short
#: book still sorts correctly in a file manager; a longer book widens naturally.
_MINIMUM_WIDTH = 2


def flatten_title(title: str) -> str:
    """Path separators inside a metadata title are punctuation, not hierarchy.

    Rewrites ``/`` and ``\\`` to a visible ``" - "``, drops NUL, and collapses
    whitespace runs so the substitutions do not leave doubled spaces behind.
    Returns ``""`` for a blank or missing title — deciding what to do about that
    is :func:`segment_filename`'s job, not this one's.

    Performs no path operation and touches no filesystem.
    """
    text = title or ""
    for bad, good in _SEPARATORS.items():
        text = text.replace(bad, good)
    return " ".join(text.split())


def segment_filename(order: int, total: int, title: str) -> str:
    """The filename for one split output: ``<order> - <safe title>.mp3``.

    *order* is 1-based within its own source item and *total* is that item's
    chapter count, which together set the zero-padding width. Numbering restarts
    at 1 for every item, and this function holds no state across items — it
    renders exactly what it is given.

    A title that flattens to nothing falls back to ``Chapter <order>``, so an
    untitled chapter still produces a meaningful, sortable name rather than a
    bare number.

    Both the body and the finished name go through ``sanitize_component``. The
    second pass is not redundant: the first cannot see the prefix or the
    extension, so only the second can enforce the component length limit over the
    whole name and keep ``.mp3`` intact while it does.
    """
    width = max(_MINIMUM_WIDTH, len(str(total)))
    fallback = f"Chapter {order}"

    body = flatten_title(title)
    body = sanitize_component(body, fallback=fallback) if body.strip() else fallback

    return sanitize_component(f"{order:0{width}d} - {body}{_EXTENSION}")
