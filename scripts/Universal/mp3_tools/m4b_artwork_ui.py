"""The M4B artwork control — the Tk adapter over ``m4b_artwork`` (v0.6.4 Phase 6).

Deferred by Phase 1 until a real consumer existed; the M4B Maker is that
consumer, and the Metadata Editor (Phase 10) is the second. One small control:
a caption, a display-only preview and Choose… / Clear, drawn once for a Shared
slot and once for the current Book, plus the two dialog/validation helpers a
panel needs beside it. It holds **no business policy**: which files may be
chosen, whether one decodes, what it becomes and how it is previewed are all
:mod:`mp3_tools.m4b_artwork`'s (over ``shared.image_capabilities``), and
whether the Book copy is enabled is the workspace model's Decision 20B answer
handed in by the consumer.

Two unrelated reasons can disable the Book copy — a run owns it (the shared
``LockGroup`` applying the job-state matrix through :meth:`set_locked`) or a
Shared value overrides it (:meth:`set_enabled`) — and they are recorded
separately and combined, so clearing one never wrongly re-enables a control the
other still holds. The control registers with the shared lock group as a
processing option (:data:`LOCK_KIND`).

Presentation: every widget asks ``job_ui.style_name`` for the approved ``ACT.*``
style on Windows; on aqua and classic the lookup returns ``""`` and the control
is drawn natively. No colour, font or metric is declared here; the one metric
that differs — whether the buttons take the design's fixed width or the native
bezel's natural width — is a hint the consumer reads off its theme and passes.
The preview is a thumbnail scaled in memory by the service; the selected file is
never opened for writing, resized, rewritten or given a sidecar.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, ttk

from shared.job_control import ControlKind
from shared.job_ui import MainThreadGuard, style_name
from mp3_tools import m4b_artwork

__all__ = [
    "ArtworkControl",
    "LOCK_KIND",
    "PREVIEW_MAX",
    "ask_artwork",
    "validated_artwork",
]

# Tk's side of the preview: the service's in-memory thumbnail becomes an image
# a label can show. Decoding is the service's, through the shared probe.
try:
    from PIL import ImageTk
except Exception:  # pragma: no cover - Pillow is a pinned requirement
    ImageTk = None

#: The control is one of the run's processing options for the lock matrix.
LOCK_KIND = ControlKind.PROCESSING_OPTION

#: The preview is display-only: nothing embedded is ever this size.
PREVIEW_MAX = (56, 56)

NO_ARTWORK = "(none)"
NO_PREVIEW = "(no preview)"


def ask_artwork(parent: tk.Misc, *, initialdir: Path | str | None = None,
                title: str = "Select Artwork") -> str:
    """The native file dialog, filtered by what this machine can decode."""
    chosen = filedialog.askopenfilename(
        parent=parent, title=title,
        initialdir=None if initialdir is None else str(initialdir),
        filetypes=m4b_artwork.artwork_filetypes())
    return str(chosen or "")


def validated_artwork(chosen: str, on_error: Callable[[str], object]) -> str | None:
    """A chosen file the service accepts, or ``None`` after ``on_error`` was told why.

    The service decodes it the way the container will; a refusal leaves
    whatever was selected before exactly as it was.
    """
    text = str(chosen or "")
    if not text:
        return None
    try:
        m4b_artwork.load_cover(text)
    except m4b_artwork.ArtworkError as exc:
        on_error(str(exc))
        return None
    return text


class ArtworkControl:
    """Caption, preview and Choose… / Clear for one artwork slot. Owns a ``frame``."""

    __slots__ = ("_guard", "caption", "path", "has_preview", "_overridden", "_locked",
                 "_closed", "_image", "_on_choose", "_on_clear", "frame", "caption_label",
                 "preview", "btn_choose", "btn_clear")

    def __init__(self, parent: tk.Misc, *, caption: str, theme, shared: bool,
                 on_choose: Callable[[], object], on_clear: Callable[[], object],
                 natural_buttons: bool = False, thread_id: int | None = None) -> None:
        self._guard = MainThreadGuard(thread_id)
        self.caption = caption
        self.path = ""
        self.has_preview = False
        self._overridden = False
        self._locked = False
        self._closed = False
        self._image = None
        self._on_choose = on_choose
        self._on_clear = on_clear

        self.frame = ttk.Frame(
            parent, style=style_name(theme, "shared_surface" if shared else "surface"))
        self.caption_label = ttk.Label(
            self.frame, text=caption,
            style=style_name(theme, "shared_label" if shared else "label"))
        self.preview = ttk.Label(
            self.frame, text=NO_ARTWORK, anchor="center", width=7,
            style=style_name(theme, "shared_secondary" if shared else "secondary_label"))
        # The button widths are the ACT design's; a theme whose native buttons
        # carry their own bezel padding asks for the natural width.
        self.btn_choose = ttk.Button(self.frame, text="Choose…",
                                     style=style_name(theme, "button"),
                                     command=self._choose,
                                     **({} if natural_buttons else {"width": 7}))
        self.btn_clear = ttk.Button(self.frame, text="Clear",
                                    style=style_name(theme, "button"),
                                    command=self._clear,
                                    **({} if natural_buttons else {"width": 5}))
        # Two rows: caption, then the two buttons side by side, with the
        # preview spanning both on the left, so the control is no taller than
        # a label and an entry.
        self.preview.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 6))
        self.caption_label.grid(row=0, column=1, columnspan=2, sticky="w")
        self.btn_choose.grid(row=1, column=1, sticky="ew")
        self.btn_clear.grid(row=1, column=2, sticky="ew", padx=(4, 0))

    # -- presses ------------------------------------------------------------- #

    def _choose(self) -> None:
        if not self._closed and self.enabled:
            self._on_choose()

    def _clear(self) -> None:
        if not self._closed and self.enabled:
            self._on_clear()

    # -- state --------------------------------------------------------------- #

    @property
    def enabled(self) -> bool:
        """Usable only when **neither** reason holds — override or run lock."""
        return not (self._overridden or self._locked)

    @property
    def closed(self) -> bool:
        return self._closed

    def set_path(self, path: str) -> None:
        """Show *path*'s preview, or the no-artwork placeholder for blank.

        The thumbnail is the service's, scaled in memory; the stored value
        stays the source path and the source is never touched. A path that
        cannot be previewed is shown as such rather than dropped: the selection
        is the user's until they change it.
        """
        self._guard.require("set_path")
        self.path = str(path or "")
        self._image = None
        self.has_preview = False
        if self._closed:
            return
        if not self.path:
            self._show(image="", text=NO_ARTWORK)
            return
        if ImageTk is None:
            self._show(image="", text=NO_PREVIEW)
            return
        try:
            thumb = m4b_artwork.preview_image(self.path, PREVIEW_MAX)
            self._image = ImageTk.PhotoImage(thumb)
            self._show(image=self._image, text="")
            self.has_preview = True
        except Exception:
            self._show(image="", text=NO_PREVIEW)

    def _show(self, **options) -> None:
        try:
            self.preview.configure(**options)
        except tk.TclError:
            pass

    def set_enabled(self, enabled: bool) -> None:
        """The Shared-override reason. :meth:`set_locked` is the run reason."""
        self._guard.require("set_enabled")
        self._overridden = not bool(enabled)
        self._apply_state()

    def set_locked(self, locked: bool) -> None:
        """The ``job_ui.LockGroup`` seam: a run owns these controls while it runs."""
        self._guard.require("set_locked")
        self._locked = bool(locked)
        self._apply_state()

    def _apply_state(self) -> None:
        state = "normal" if self.enabled and not self._closed else "disabled"
        for button in (self.btn_choose, self.btn_clear):
            try:
                button.configure(state=state)
            except tk.TclError:
                pass

    def close(self) -> None:
        """Idempotent, and safe after the root has already been destroyed."""
        self._guard.require("close")
        if self._closed:
            return
        self._closed = True
        self._apply_state()
        self._image = None
        self._on_choose = self._on_clear = lambda: None
