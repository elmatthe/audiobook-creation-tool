"""Preferences & Data: output preferences, reset, and downloaded-data cleanup.

Presentation only. Every rule these dialogs enforce — what a valid output base
is, what precedence applies, what a reset clears, which downloaded assets exist,
what they are allowed to point at, how big they are — lives in ``shared.config``,
``shared.settings`` and ``shared.maintenance`` and is tested without Tk. This
module collects choices and shows results; it decides nothing.

Nothing here deletes. The Clear Downloaded Data flow inventories, lets the user
select, confirms in the strongest terms, builds one immutable
:class:`~shared.maintenance.CleanupRequest` and hands it to an injected
callback. Until Phase 7 supplies the real post-exit coordinator that callback is
:func:`~shared.maintenance.unavailable_cleanup_handler`, which fails closed:
nothing is written, nothing is started, the app stays open, and the user is told
so plainly rather than being told cleanup was scheduled.

Platform handling follows the Plan 1 contract. On Windows every widget names an
``ACT.*`` style from ``theme["styles"]``; on macOS and Linux that map is absent,
:func:`_style` returns ``""``, and a widget with no style resolves the platform's
generic one — which is exactly what keeps aqua native. There is no
platform-specific *logic* anywhere in this file, only styling lookups that
degrade to nothing.

``confirm`` and ``ask_directory`` are injected so the suite can drive the reset
and browse flows deterministically without a real message box.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import config, maintenance, paths

DIALOG_TITLE = "Preferences & Data"
MENU_LABEL = "Preferences & Data…"

#: Shown beside the Clear Downloaded Data button. It reviews and confirms; the
#: post-exit coordinator that actually removes anything is Phase 7.
CLEANUP_PLACEHOLDER_TEXT = "Review what can be safely removed. Nothing is deleted yet."
CLEANUP_BUTTON_LABEL = "Clear Downloaded Data"

#: Keyboard accelerators — the platform-conventional Preferences shortcuts.
ACCELERATORS = ("<Control-comma>", "<Command-comma>")

_SOURCE_TEXT = {
    config.SOURCE_DEFAULT: "the built-in default",
    config.SOURCE_TOML: "config.toml",
    config.SOURCE_SETTINGS: "your saved preference",
}


# --------------------------------------------------------------------------- #
# Theme access that degrades safely off Windows
# --------------------------------------------------------------------------- #


def _style(theme, name: str) -> str:
    """The ``ACT.*`` style for *name*, or ``""`` where the map does not exist.

    An empty style string is not a fallback hack — it is how a widget resolves
    the platform's generic ttk style, which is what keeps macOS native and is
    the same mechanism that leaves the five unconverted panels alone.
    """
    styles = (theme or {}).get("styles") or {}
    return styles.get(name, "")


def _metric(theme, name: str, fallback):
    metrics = (theme or {}).get("metrics") or {}
    value = metrics.get(name)
    return fallback if value is None else value


def _describe_source(effective) -> str:
    """Plain English for where the effective output base actually came from."""
    source = effective.source_of("output.base_directory")
    if effective.output.is_default:
        if source == config.SOURCE_DEFAULT:
            return "Using the default Downloads location (nothing has overridden it)."
        return f"Using the default Downloads location ({_SOURCE_TEXT[source]} leaves it unset)."
    return f"Using a custom location from {_SOURCE_TEXT[source]}."


# --------------------------------------------------------------------------- #
# The dialog
# --------------------------------------------------------------------------- #


class PreferencesDialog(tk.Toplevel):
    """Non-modal, single-instance Preferences & Data window.

    Deliberately not modal: the launcher stays usable behind it, and the
    launcher holds the one live instance so repeated activation focuses this
    window instead of stacking duplicates.
    """

    def __init__(self, master, theme=None, *, confirm=None, ask_directory=None,
                 logger=None, repo_root=None, start_cleanup=None):
        super().__init__(master)
        self.theme = theme or {}
        self._confirm = confirm if confirm is not None else self._default_confirm
        self._ask_directory = ask_directory if ask_directory is not None else self._default_browse
        self._logger = logger
        #: Always explicit downstream, so the suite inventories a fake tree.
        self._repo_root = paths.REPO_ROOT if repo_root is None else repo_root
        self._start_cleanup = start_cleanup
        #: The one live cleanup window, held for the same reason the launcher
        #: holds this one: repeated activation focuses rather than stacks.
        self.cleanup_dialog = None

        self.title(DIALOG_TITLE)
        self.transient(master)
        self.resizable(True, True)

        colors = self.theme.get("colors") or {}
        if self.theme.get("mode") == "windows" and colors.get("window"):
            self.configure(background=colors["window"])

        self.var_mode = tk.StringVar(value="default")
        self.var_path = tk.StringVar(value="")
        self.var_effective = tk.StringVar(value="")
        self.var_source = tk.StringVar(value="")
        self.var_status = tk.StringVar(value="")
        self._status_kind = "info"

        self._build()
        self.refresh_from_config()

        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _e: self.close())
        # Sized from its own content, then pinned so the bounded form can never
        # be squeezed below the point where Save/Close stop being reachable.
        self.update_idletasks()
        self.minsize(max(520, self.winfo_reqwidth()), max(360, self.winfo_reqheight()))

    # -- construction ------------------------------------------------------ #

    #: Text wrap width. Wide enough that every explanatory line stays one or two
    #: rows tall, which is what keeps the whole bounded form inside the app's
    #: 920x600 supported minimum without a scroll region.
    WRAP = 600

    def _build(self) -> None:
        t = self.theme
        gap_sm = _metric(t, "gap_sm", 8)
        gap_md = _metric(t, "gap_md", 12)
        # The tight end of the spacing scale, not content_pad: the Windows build
        # renders at larger font and button sizes than the native macOS one, and
        # these are the pixels that keep the whole bounded form inside 920x600.
        pad = gap_md

        outer = ttk.Frame(self, style=_style(t, "window"), padding=pad)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)

        header = ttk.Frame(outer, style=_style(t, "window"))
        header.grid(row=0, column=0, sticky="ew", pady=(0, gap_md))
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text=DIALOG_TITLE, style=_style(t, "title")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header, text="Saved to your settings — config.toml is never modified.",
            style=_style(t, "secondary_label"), anchor="e",
        ).grid(row=0, column=1, sticky="e")

        self._build_output_section(outer, row=1)
        self._build_reset_section(outer, row=2)
        self._build_cleanup_section(outer, row=3)

        # -- status + close ------------------------------------------------ #
        footer = ttk.Frame(outer, style=_style(t, "window"))
        footer.grid(row=4, column=0, sticky="ew", pady=(gap_md, 0))
        footer.columnconfigure(0, weight=1)
        self._status_label = ttk.Label(
            footer, textvariable=self.var_status, style=_style(t, "secondary_label"),
            wraplength=self.WRAP - 90, justify="left",
        )
        self._status_label.grid(row=0, column=0, sticky="w", padx=(0, gap_sm))
        self.button_close = ttk.Button(
            footer, text="Close", style=_style(t, "button"), command=self.close
        )
        self.button_close.grid(row=0, column=1, sticky="e")

    def _card(self, parent, row: int, title: str, *, last: bool = False):
        t = self.theme
        card = ttk.Frame(parent, style=_style(t, "card"),
                         padding=_metric(t, "card_pad", 14))
        card.grid(row=row, column=0, sticky="ew",
                  pady=(0, 0 if last else _metric(t, "gap_sm", 8)))
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text=title, style=_style(t, "heading")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        return card

    def _build_output_section(self, parent, row: int) -> None:
        t = self.theme
        gap_sm = _metric(t, "gap_sm", 8)
        card = self._card(parent, row, "Output location")

        ttk.Label(
            card, textvariable=self.var_effective, style=_style(t, "label"),
            wraplength=self.WRAP, justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(gap_sm, 0))
        ttk.Label(
            card, textvariable=self.var_source, style=_style(t, "secondary_label"),
            wraplength=self.WRAP, justify="left",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(1, gap_sm))

        self.radio_default = ttk.Radiobutton(
            card, text="Use the default Downloads location",
            variable=self.var_mode, value="default",
            style=_style(t, "radiobutton"), command=self._on_mode_change,
        )
        self.radio_default.grid(row=3, column=0, columnspan=3, sticky="w")

        self.radio_custom = ttk.Radiobutton(
            card, text="Use a custom folder", variable=self.var_mode, value="custom",
            style=_style(t, "radiobutton"), command=self._on_mode_change,
        )
        self.radio_custom.grid(row=4, column=0, columnspan=3, sticky="w", pady=(1, gap_sm))

        # Entry, Browse and Save share one row. Three controls on a line rather
        # than three stacked rows is most of what keeps the Windows build —
        # larger fonts and button padding than the native macOS one — inside the
        # 920x600 supported minimum without a scroll region.
        self.entry_path = ttk.Entry(card, textvariable=self.var_path, style=_style(t, "entry"))
        self.entry_path.grid(row=5, column=0, sticky="ew", padx=(0, gap_sm))
        self.button_browse = ttk.Button(
            card, text="Browse…", style=_style(t, "button"), command=self.browse
        )
        self.button_browse.grid(row=5, column=1, sticky="e", padx=(0, gap_sm))
        self.button_save = ttk.Button(
            card, text="Save", style=_style(t, "primary_button"),
            command=self.save_output_base,
        )
        self.button_save.grid(row=5, column=2, sticky="e")

        ttk.Label(
            card,
            text="A full path, or one starting with ~. Relative paths and environment "
                 "variables are not accepted.",
            style=_style(t, "secondary_label"), wraplength=self.WRAP, justify="left",
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(gap_sm, 0))

    def _build_reset_section(self, parent, row: int) -> None:
        t = self.theme
        gap_sm = _metric(t, "gap_sm", 8)
        card = self._card(parent, row, "Reset preferences")
        card.columnconfigure(0, weight=1)

        # The action sits on the heading row, so the card costs two rows rather
        # than three (see the note on the output row above).
        self.button_reset = ttk.Button(
            card, text="Reset Preferences…", style=_style(t, "button"),
            command=self.reset_preferences,
        )
        self.button_reset.grid(row=0, column=1, sticky="e")

        ttk.Label(
            card,
            text="Clears saved preferences only — last tool, remembered folders and any "
                 "custom output location. Nothing you downloaded or produced is removed.",
            style=_style(t, "secondary_label"), wraplength=self.WRAP, justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(gap_sm, 0))

    def _build_cleanup_section(self, parent, row: int) -> None:
        """Clear Downloaded Data — a separate action, never bundled with Reset.

        Deliberately its own card with its own button: a reset of preferences
        and a removal of downloaded data are different decisions and are never
        offered as one control or one confirmation.
        """
        t = self.theme
        gap_sm = _metric(t, "gap_sm", 8)
        card = self._card(parent, row, "Downloaded data", last=True)
        card.columnconfigure(1, weight=1)

        self.button_cleanup = ttk.Button(
            card, text=CLEANUP_BUTTON_LABEL, style=_style(t, "button"),
            command=self.open_cleanup,
        )
        self.button_cleanup.grid(row=1, column=0, sticky="w", pady=(gap_sm, 0))
        self.label_cleanup_placeholder = ttk.Label(
            card, text=CLEANUP_PLACEHOLDER_TEXT, style=_style(t, "secondary_label"),
            wraplength=self.WRAP - 160, justify="left",
        )
        self.label_cleanup_placeholder.grid(row=1, column=1, sticky="w",
                                            padx=(gap_sm, 0), pady=(gap_sm, 0))

    # -- state ------------------------------------------------------------- #

    def refresh_from_config(self) -> None:
        """Repaint every field from a freshly read effective configuration."""
        effective = config.get_effective()
        self.var_effective.set(str(effective.output.base_directory))
        self.var_source.set(_describe_source(effective))
        if effective.output.is_default:
            self.var_mode.set("default")
            self.var_path.set("")
        else:
            self.var_mode.set("custom")
            self.var_path.set(str(effective.output.base_directory))
        self._on_mode_change()

    def _on_mode_change(self) -> None:
        custom = self.var_mode.get() == "custom"
        state = "normal" if custom else "disabled"
        self.entry_path.configure(state=state)
        self.button_browse.configure(state=state)

    def _set_status(self, message: str, kind: str = "info") -> None:
        self._status_kind = kind
        self.var_status.set(message)
        style_name = {
            "success": "success_label",
            "error": "danger_label",
        }.get(kind, "secondary_label")
        try:
            self._status_label.configure(style=_style(self.theme, style_name))
        except tk.TclError:
            pass

    @property
    def status_kind(self) -> str:
        return self._status_kind

    def _log(self, message: str) -> None:
        if self._logger is not None:
            try:
                self._logger.warning(message)
            except Exception:
                pass

    # -- actions ----------------------------------------------------------- #

    def _default_browse(self):
        return filedialog.askdirectory(parent=self, title="Choose an output folder")

    def _default_confirm(self, title: str, message: str) -> bool:
        return bool(messagebox.askyesno(title, message, parent=self))

    def browse(self) -> None:
        chosen = self._ask_directory()
        if not chosen:
            return
        self.var_mode.set("custom")
        self._on_mode_change()
        self.var_path.set(str(chosen))

    def save_output_base(self) -> bool:
        """Validate, persist atomically, then reload. True when it stuck."""
        if self.var_mode.get() == "default":
            return self._commit(None, "Output location reset to the default Downloads folder.")

        raw = self.var_path.get().strip()
        if not raw:
            self._set_status("Enter a folder, or choose the default location.", "error")
            return False

        resolved, reason = config.validate_output_base(raw)
        if resolved is None:
            # The reason is written for a person; nothing raw reaches the GUI.
            self._set_status(f"That folder cannot be used — {reason}.", "error")
            self._log(f"preferences: rejected output base {raw!r} ({reason})")
            return False
        return self._commit(resolved, f"Output location saved: {resolved}")

    def _commit(self, value, success_message: str) -> bool:
        try:
            ok = config.set_output_base(value)
        except ValueError as exc:
            self._set_status(f"That folder cannot be used — {exc}.", "error")
            self._log(f"preferences: {exc}")
            return False
        except OSError as exc:
            self._set_status("Your preferences could not be saved. The previous "
                             "setting is still in use.", "error")
            self._log(f"preferences: settings write raised {type(exc).__name__}: {exc}")
            self.refresh_from_config()
            return False
        if not ok:
            # settings.set rolls the in-memory value back on a failed write, so
            # refreshing shows what is genuinely still in force.
            self._set_status("Your preferences could not be saved. The previous "
                             "setting is still in use.", "error")
            self._log("preferences: atomic settings write failed; previous value retained")
            self.refresh_from_config()
            return False
        self.refresh_from_config()
        self._set_status(success_message, "success")
        return True

    def reset_preferences(self) -> bool:
        """Confirm, then clear mutable preferences only. True when it happened."""
        agreed = self._confirm(
            "Reset preferences?",
            "This clears your saved preferences: the last tool you had open, remembered "
            "folders, and any custom output location.\n\n"
            "It does not delete downloaded data, models, logs, produced files or any of "
            "your own media, and it does not change the project's config.toml.\n\n"
            "Reset them now?",
        )
        if not agreed:
            self._set_status("Reset cancelled. Nothing was changed.", "info")
            return False

        if not config.reset_preferences():
            self._set_status("Preferences could not be reset. Your existing settings "
                             "file is unchanged.", "error")
            self._log("preferences: atomic reset failed; settings file left intact")
            self.refresh_from_config()
            return False

        self.refresh_from_config()
        self._set_status("Preferences reset. Defaults are back in force.", "success")
        return True

    def open_cleanup(self):
        """Open the Clear Downloaded Data review, or focus the open one."""
        self.cleanup_dialog = open_cleanup_dialog(
            self, self.theme, self.cleanup_dialog,
            repo_root=self._repo_root, start_cleanup=self._start_cleanup,
            logger=self._logger,
        )
        return self.cleanup_dialog

    def focus_dialog(self) -> None:
        """Bring this window forward — the single-instance path."""
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def close(self) -> None:
        try:
            self.destroy()
        except tk.TclError:
            pass


# --------------------------------------------------------------------------- #
# Single-instance entry point
# --------------------------------------------------------------------------- #


def _is_alive(dialog) -> bool:
    try:
        return bool(dialog is not None and dialog.winfo_exists())
    except tk.TclError:
        return False


def open_preferences(master, theme=None, existing=None, **kwargs):
    """Focus the live Preferences dialog, or create the one instance.

    The caller keeps the returned reference and hands it back next time, which
    is what makes repeated activation focus rather than stack duplicates.
    """
    if _is_alive(existing):
        existing.focus_dialog()
        return existing
    dialog = PreferencesDialog(master, theme, **kwargs)
    dialog.focus_dialog()
    return dialog


# --------------------------------------------------------------------------- #
# Clear Downloaded Data — inventory and selection
# --------------------------------------------------------------------------- #


class CleanupDialog(tk.Toplevel):
    """The itemized downloaded-data review. Selects and confirms; deletes nothing.

    Safe by construction rather than by discipline:

    * every checkbox is created unchecked, on every open, and no selection is
      ever written down or read back — closing and reopening starts over;
    * a missing or unsafe item has no usable checkbox at all;
    * ``Review Selected Data…`` stays disabled until something eligible is
      deliberately ticked;
    * the size walk runs on a worker thread and every Tk update is applied on
      the main thread through ``after``, because a full ``.venv`` walk on the
      Tk thread would freeze the window.
    """

    WRAP = 620

    def __init__(self, master, theme=None, *, repo_root=None, start_cleanup=None,
                 logger=None, confirm_factory=None, measure=True):
        super().__init__(master)
        self.theme = theme or {}
        self._repo_root = paths.REPO_ROOT if repo_root is None else repo_root
        #: Phase 6's production callback fails closed. Phase 7 replaces it.
        self._start_cleanup = (
            maintenance.unavailable_cleanup_handler if start_cleanup is None
            else start_cleanup
        )
        self._logger = logger
        self._confirm_factory = confirm_factory or CleanupConfirmationDialog

        self.title(maintenance.CLEANUP_DIALOG_TITLE)
        self.transient(master)
        self.resizable(True, True)

        colors = self.theme.get("colors") or {}
        if self.theme.get("mode") == "windows" and colors.get("window"):
            self.configure(background=colors["window"])

        #: The request handed to the callback on the last acceptance. Held for
        #: the suite and for logging; never persisted.
        self.last_request = None
        self._closed = False
        self._after_id = None
        self._queue: queue.Queue = queue.Queue()
        self._vars: dict[str, tk.BooleanVar] = {}
        self._rows: dict[str, dict] = {}
        self.var_status = tk.StringVar(value=maintenance.NOTHING_SELECTED_TEXT)
        self._status_kind = "info"

        # Unmeasured first: the rows paint immediately and the sizes arrive
        # from the worker, so opening the dialog is never a stall.
        self.items = maintenance.inventory(self._repo_root, measure=False)
        self._build()
        self._on_selection_change()

        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _e: self.close())
        self.update_idletasks()
        self.minsize(max(560, self.winfo_reqwidth()), max(320, self.winfo_reqheight()))

        if measure:
            self.start_inventory()

    # -- construction ------------------------------------------------------ #

    def _build(self) -> None:
        t = self.theme
        gap_sm = _metric(t, "gap_sm", 8)
        gap_md = _metric(t, "gap_md", 12)

        outer = ttk.Frame(self, style=_style(t, "window"), padding=gap_md)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        ttk.Label(outer, text=maintenance.CLEANUP_DIALOG_TITLE,
                  style=_style(t, "title")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            outer, text=maintenance.CLEANUP_INTRO, style=_style(t, "secondary_label"),
            wraplength=self.WRAP, justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(2, gap_md))

        # The one region allowed to grow: four rows today, and a local scroll
        # rather than a scrolling dialog if a later plan adds more.
        self.item_frame = ttk.Frame(outer, style=_style(t, "card"),
                                    padding=_metric(t, "card_pad", 14))
        self.item_frame.grid(row=2, column=0, sticky="nsew")
        self.item_frame.columnconfigure(0, weight=1)

        for index, item in enumerate(self.items):
            self._build_row(self.item_frame, index * 2, item)

        footer = ttk.Frame(outer, style=_style(t, "window"))
        footer.grid(row=3, column=0, sticky="ew", pady=(gap_md, 0))
        footer.columnconfigure(0, weight=1)

        self.label_status = ttk.Label(
            footer, textvariable=self.var_status, style=_style(t, "secondary_label"),
            wraplength=self.WRAP - 220, justify="left",
        )
        self.label_status.grid(row=0, column=0, sticky="w", padx=(0, gap_sm))
        self.button_cancel = ttk.Button(
            footer, text=maintenance.CANCEL_BUTTON_LABEL, style=_style(t, "button"),
            command=self.close,
        )
        self.button_cancel.grid(row=0, column=1, sticky="e", padx=(0, gap_sm))
        self.button_review = ttk.Button(
            footer, text=maintenance.REVIEW_BUTTON_LABEL,
            style=_style(t, "primary_button"), command=self.review_selection,
            state="disabled",
        )
        self.button_review.grid(row=0, column=2, sticky="e")

        # Cancel is the safe landing place for the keyboard on open.
        self.button_cancel.focus_set()
        self.default_widget = self.button_cancel

    def _build_row(self, parent, row: int, item) -> None:
        t = self.theme
        gap_sm = _metric(t, "gap_sm", 8)
        parent.columnconfigure(0, weight=1)

        var = tk.BooleanVar(value=False)          # unchecked, always
        self._vars[item.asset_id] = var
        check = ttk.Checkbutton(
            parent, text=item.display_name, variable=var,
            style=_style(t, "checkbutton"), command=self._on_selection_change,
        )
        check.grid(row=row, column=0, sticky="w", pady=(gap_sm if row else 0, 0))
        if not item.selectable:
            check.configure(state="disabled")

        state = ttk.Label(parent, text=item.state_text,
                          style=_style(t, "secondary_label"))
        state.grid(row=row, column=1, sticky="e", padx=(gap_sm, gap_sm),
                   pady=(gap_sm if row else 0, 0))
        size = ttk.Label(parent, text=item.size_text, style=_style(t, "label"))
        size.grid(row=row, column=2, sticky="e", pady=(gap_sm if row else 0, 0))

        detail = ttk.Label(
            parent, text=self._detail_text(item), style=_style(t, "secondary_label"),
            wraplength=self.WRAP - 40, justify="left",
        )
        detail.grid(row=row + 1, column=0, columnspan=3, sticky="w", padx=(20, 0))

        self._rows[item.asset_id] = {
            "check": check, "state": state, "size": size, "detail": detail,
        }

    @staticmethod
    def _detail_text(item) -> str:
        """The consequence, or the reason this item cannot be chosen."""
        return item.problem if item.problem else item.consequence

    # -- background inventory --------------------------------------------- #

    def start_inventory(self) -> None:
        """Measure sizes off the Tk thread; results land through :meth:`_poll`."""
        root = self._repo_root
        result_queue = self._queue

        def work():
            try:
                result_queue.put(("items", maintenance.inventory(root, measure=True)))
            except Exception as exc:                      # never kill the worker
                result_queue.put(("error", exc))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()
        self._poll()

    def _poll(self) -> None:
        """Drain the worker's queue on the main thread. Safe after close."""
        if self._closed or not self._alive():
            return
        try:
            kind, payload = self._queue.get_nowait()
        except queue.Empty:
            self._after_id = self.after(60, self._poll)
            return
        if kind == "items":
            self.apply_measured(payload)
        else:
            self._log(f"cleanup inventory failed: {payload!r}")
            self._set_status("Some sizes could not be read. Nothing was changed.",
                             "error")

    def _alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def apply_measured(self, items) -> None:
        """Repaint sizes and details from a measured snapshot.

        Every write is guarded: the worker can finish after the user has closed
        the window, and updating a destroyed widget must be a no-op rather than
        a traceback.
        """
        if self._closed or not self._alive():
            return
        self.items = tuple(items)
        try:
            for item in self.items:
                widgets = self._rows.get(item.asset_id)
                if not widgets:
                    continue
                widgets["state"].configure(text=item.state_text)
                widgets["size"].configure(text=item.size_text)
                widgets["detail"].configure(text=self._detail_text(item))
                if not item.selectable:
                    # A target that became unsafe while we measured loses both
                    # its tick and its control.
                    self._vars[item.asset_id].set(False)
                    widgets["check"].configure(state="disabled")
        except tk.TclError:
            return
        self._on_selection_change()

    # -- selection --------------------------------------------------------- #

    def selected_ids(self) -> tuple[str, ...]:
        """Ticked *and* eligible, in catalog order. Never anything else."""
        eligible = {i.asset_id for i in self.items if i.selectable}
        return tuple(
            item.asset_id for item in self.items
            if item.asset_id in eligible and self._vars[item.asset_id].get()
        )

    def _on_selection_change(self) -> None:
        chosen = self.selected_ids()
        try:
            summary = maintenance.summarise_selection(self.items, chosen)
        except maintenance.MaintenanceError:
            # Cannot happen through the UI; if it ever did, refuse to proceed
            # rather than describe a selection we could not verify.
            self._set_status(maintenance.NOTHING_SELECTED_TEXT, "info")
            self._set_review_enabled(False)
            return
        self._set_status(maintenance.selected_total_text(summary), "info")
        self._set_review_enabled(bool(summary.asset_ids))

    def _set_review_enabled(self, enabled: bool) -> None:
        try:
            self.button_review.configure(state="normal" if enabled else "disabled")
        except tk.TclError:
            pass

    def _set_status(self, message: str, kind: str = "info") -> None:
        self._status_kind = kind
        self.var_status.set(message)
        style_name = {"success": "success_label", "error": "danger_label"}.get(
            kind, "secondary_label"
        )
        try:
            self.label_status.configure(style=_style(self.theme, style_name))
        except tk.TclError:
            pass

    @property
    def status_kind(self) -> str:
        return self._status_kind

    def _log(self, message: str) -> None:
        if self._logger is not None:
            try:
                self._logger.warning(message)
            except Exception:
                pass

    # -- review and confirm ------------------------------------------------ #

    def build_confirmation(self):
        """The confirmation window for the current selection, built fresh.

        Split from :meth:`review_selection` so the suite can inspect and drive
        the real dialog without entering its modal loop.
        """
        chosen = self.selected_ids()
        body = maintenance.confirmation_body(self.items, chosen)
        return self._confirm_factory(self, body, len(chosen), self.theme)

    def review_selection(self) -> bool:
        """Confirm, then hand one validated request to the callback.

        Returns True only when the callback accepted it. Declining, or a
        callback that refuses, changes nothing at all.
        """
        chosen = self.selected_ids()
        if not chosen:
            self._set_status(maintenance.NOTHING_SELECTED_TEXT, "info")
            return False

        window = self.build_confirmation()
        if not window.show():
            self._set_status("Cleanup cancelled. Nothing was changed.", "info")
            return False
        return self.submit(chosen)

    def submit(self, chosen) -> bool:
        """Validate, build the immutable request, and call only the callback."""
        try:
            request = maintenance.build_request(chosen)
        except maintenance.MaintenanceError as exc:
            self._log(f"cleanup request refused: {exc}")
            self._set_status("That selection could not be prepared. Nothing was "
                             "changed.", "error")
            return False

        self.last_request = request
        started = False
        try:
            started = bool(self._start_cleanup(request))
        except Exception as exc:                      # a callback must never crash us
            self._log(f"cleanup handoff raised {type(exc).__name__}: {exc}")
            started = False

        if not started:
            # Fail closed: say so exactly, and leave everything usable.
            self._set_status(maintenance.CLEANUP_UNAVAILABLE_MESSAGE, "error")
            self._log("cleanup did not start; no data was changed")
            return False
        return True

    def close(self) -> None:
        """Cancel: stop polling first, then destroy. Nothing is written."""
        self._closed = True
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        try:
            self.destroy()
        except tk.TclError:
            pass

    def focus_dialog(self) -> None:
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass


def open_cleanup_dialog(master, theme=None, existing=None, **kwargs):
    """Focus the live cleanup review, or create the one instance."""
    if _is_alive(existing):
        existing.focus_dialog()
        return existing
    dialog = CleanupDialog(master, theme, **kwargs)
    dialog.focus_dialog()
    return dialog


# --------------------------------------------------------------------------- #
# The strong confirmation
# --------------------------------------------------------------------------- #


class CleanupConfirmationDialog(tk.Toplevel):
    """One custom confirmation, never a generic Yes/No box.

    Cancel is the focused default and the destructive button never is, so a
    reflexive Return dismisses the dialog safely. Escape and the window close
    control both cancel. There is no "don't ask again": the window is rebuilt
    from the live selection every time it is needed.
    """

    #: Wide enough that each item's consequence stays on one line. Every line
    #: that wraps costs ~19px of height, and with all four items selected this
    #: is the difference between comfortably inside the 920x600 supported
    #: minimum and pressing against it.
    WRAP = 780

    def __init__(self, master, body: str, count: int, theme=None):
        super().__init__(master)
        self.theme = theme or {}
        t = self.theme
        self.title(maintenance.CONFIRM_TITLE)
        self.transient(master)
        self.resizable(False, False)

        colors = t.get("colors") or {}
        if t.get("mode") == "windows" and colors.get("window"):
            self.configure(background=colors["window"])

        self.result = False
        self.body_text = body

        pad = _metric(t, "gap_md", 12)
        gap_sm = _metric(t, "gap_sm", 8)

        outer = ttk.Frame(self, style=_style(t, "window"), padding=pad)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=maintenance.CONFIRM_TITLE,
                  style=_style(t, "heading")).pack(anchor="w", pady=(0, gap_sm))
        self.label_message = ttk.Label(
            outer, text=body, style=_style(t, "label"),
            wraplength=self.WRAP, justify="left",
        )
        self.label_message.pack(anchor="w")

        actions = ttk.Frame(outer, style=_style(t, "window"))
        actions.pack(fill="x", pady=(pad, 0))
        self.btn_confirm = ttk.Button(
            actions, text=maintenance.confirmation_button_label(count),
            style=_style(t, "danger_button"), command=self.confirm,
        )
        self.btn_confirm.pack(side="right")
        self.btn_cancel = ttk.Button(
            actions, text=maintenance.CANCEL_BUTTON_LABEL,
            style=_style(t, "button"), command=self.cancel,
        )
        self.btn_cancel.pack(side="right", padx=(0, gap_sm))

        # Recorded as well as set: focus cannot be observed reliably on a
        # withdrawn root, so the intended default is stated explicitly.
        self.default_widget = self.btn_cancel
        self.btn_cancel.focus_set()

        self.bind("<Escape>", lambda _e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.update_idletasks()

    def cancel(self) -> None:
        self.result = False
        self._finish()

    def confirm(self) -> None:
        self.result = True
        self._finish()

    def _finish(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass

    def show(self) -> bool:
        """Run modally and report the choice. False on every safe exit."""
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.wait_window()
        return bool(self.result)


# --------------------------------------------------------------------------- #
# The once-per-launch configuration warning
# --------------------------------------------------------------------------- #


class ConfigWarningDialog(tk.Toplevel):
    """One non-modal window carrying the whole aggregated summary.

    Deliberately not a ``messagebox``: it must not block, and it must be one
    window for every diagnostic rather than one per bad key.
    """

    def __init__(self, master, summary: str, theme=None):
        super().__init__(master)
        self.theme = theme or {}
        t = self.theme
        self.title("Configuration warnings")
        self.transient(master)

        colors = t.get("colors") or {}
        if t.get("mode") == "windows" and colors.get("window"):
            self.configure(background=colors["window"])

        pad = _metric(t, "content_pad", 16)
        gap_sm = _metric(t, "gap_sm", 8)
        gap_md = _metric(t, "gap_md", 12)

        outer = ttk.Frame(self, style=_style(t, "window"), padding=pad)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Some settings could not be used",
                  style=_style(t, "heading")).pack(anchor="w")
        ttk.Label(
            outer,
            text="The application started normally using safe default values. "
                 "You can carry on; fix these when convenient.",
            style=_style(t, "secondary_label"), wraplength=460, justify="left",
        ).pack(anchor="w", pady=(gap_sm, gap_md))
        self.label_summary = ttk.Label(
            outer, text=summary, style=_style(t, "label"), wraplength=460, justify="left"
        )
        self.label_summary.pack(anchor="w")
        ttk.Label(
            outer, text="Full technical details are in the session log.",
            style=_style(t, "secondary_label"), wraplength=460, justify="left",
        ).pack(anchor="w", pady=(gap_md, gap_md))

        ttk.Button(outer, text="Continue", style=_style(t, "primary_button"),
                   command=self.destroy).pack(anchor="e")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        self.minsize(max(420, self.winfo_reqwidth()), max(200, self.winfo_reqheight()))


def present_launch_warnings(master, theme=None, logger=None, dialog_factory=None):
    """Show the aggregated configuration summary at most once per process.

    Returns the summary that was presented, or ``None`` when there was nothing
    actionable to say (or the guard had already been consumed). The technical
    detail goes to the log; only the human-readable summary reaches the window.
    """
    effective = config.get_effective()
    summary = config.take_launch_warning()
    if not summary:
        return None

    if logger is not None:
        for line in effective.technical_details():
            try:
                logger.warning("configuration: %s", line)
            except Exception:
                pass

    factory = dialog_factory if dialog_factory is not None else ConfigWarningDialog
    try:
        factory(master, summary, theme)
    except tk.TclError:
        # No display (headless). The summary is already in the log; never let
        # a warning about configuration become a startup failure.
        pass
    return summary
