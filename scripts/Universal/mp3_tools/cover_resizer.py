#!/usr/bin/env python3
"""Cover Image Resizer — batch resize cover art to a square (letterbox or crop).

Refactored for the unified launcher: the UI is built by :func:`build_ui` into
any parent frame, so it can live inside the launcher's content panel. Running
this file directly still opens it in its own window via :func:`main`.

Phase 5: Cancel button (cooperative, checked between images) and a remembered
input folder via shared.settings (default = home).

v0.6.0 Drop 2 Phase 4 moved standard output off the source folder: a validated
resize reserves one run under ``<output base>/Cover-Image-Outputs/Cover-Image-N/``
and writes there.

v0.6.0 Drop 2 Phase 5 adds the two source-side modes of Decision 10A, behind
three independent gates. Replacement happens only when **all** of these hold:

1. ``Save beside source images`` is enabled (off on every fresh build);
2. ``Replace original files`` is selected (``Create numbered copies`` is the
   default, and switching the toggle off resets to it);
3. the per-run confirmation is accepted — Cancel is the focused default, Escape
   and closing the window cancel, and nothing about it can be remembered.

Numbered-copy mode writes ``stem-1.ext`` beside each source, never the
unnumbered name, because that name *is* the source. Replacement writes a
complete temporary sibling, validates the finished image, and only then
installs it with a single atomic ``os.replace`` — never delete-then-rename. A
failure before that boundary leaves the original byte-for-byte unchanged and
removes only this operation's own temporary file.
"""

import queue
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Make the scripts/ root importable so `shared.*` resolves whether this tool is
# run standalone or imported by the launcher.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from shared import output_paths
from shared import paths
from shared import settings
from shared import ui_theme

from PIL import Image  # needs: pip install pillow

# Try to add HEIC/HEIF support if pillow-heif is installed
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:
    pass

APP_TITLE = "Audiobook Cover Resizer v1.1"
TARGET_SIZE = 1024  # default square size for covers

# settings.json keys (Phase 5)
SOURCE_SIDE_LABEL = "Save beside source images"
MODE_STANDARD = "standard"
ACTION_NUMBERED = "numbered"
ACTION_REPLACE = "replace"

#: Extensions the writer can round-trip in place. Anything else is written as
#: .jpg, so it cannot be replaced under its own name and is refused before the
#: confirmation dialog rather than surprising the user mid-run.
REPLACEABLE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif"})

TOOL_KEY = "cover"
SLUG = paths.TOOL_SLUGS[TOOL_KEY]

KEY_INPUT_DIR = "cover_resizer.input_dir"


# ---------- helpers ----------


def _remembered_dir(key: str) -> Path:
    """Return the saved folder for ``key`` if it still exists, else the home dir."""
    val = settings.get(key)
    if val:
        p = Path(val)
        if p.exists():
            return p
    return Path.home()


def written_suffix(suffix: str) -> str:
    """The extension :func:`resize_for_audiobook` will actually write.

    It falls back to ``.jpg`` for anything it cannot encode, so a caller that
    plans a destination has to plan the *written* name, not the source's.
    """
    lowered = (suffix or "").lower()
    return lowered if lowered in REPLACEABLE_SUFFIXES else ".jpg"


def next_version_path(p: Path) -> Path:
    """Return first available Name-1.ext, Name-2.ext, ... in same folder.

    .. deprecated:: v0.6.0 Drop 2 Phase 5

       Superseded by ``output_paths.SourceSidePlanner``, which tracks planned
       names as well as existing ones and keeps separate sequences per source
       directory. Retained only because the standalone entry point and older
       tests still import it; no production path calls it.
    """
    stem = p.stem
    suffix = p.suffix
    parent = p.parent
    n = 1
    while True:
        candidate = parent / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


#: Title of the per-run replacement confirmation.
REPLACEMENT_TITLE = "Confirm replacement of original images"


def replacement_message(count: int) -> str:
    """The approved confirmation wording, with singular/plural grammar.

    Kept as a function so the dialog and the suite read the *same* text — a
    test that restates the wording would let the two drift apart, and this is
    the one message a user relies on before an irreversible action.
    """
    plural = "" if count == 1 else "s"
    return (
        f"You selected Replace original files for {count} image{plural}.\n\n"
        "This will permanently replace the selected source image files. "
        "Audiobook Creation Tool cannot undo this action.\n\n"
        "Each replacement is written to a temporary file first and installed "
        "only after successful processing. Files already replaced before a "
        "later failure or cancellation remain replaced.\n\n"
        "Continue?"
    )


def replacement_button_label(count: int) -> str:
    """The destructive button's label — never a bare "OK"."""
    return ("Replace 1 Original File" if count == 1
            else f"Replace {count} Original Files")


def build_replacement_dialog(parent, title: str, message: str, confirm_label: str):
    """Build the confirmation window and return it, without waiting on it.

    Separated from :func:`_ask_replacement` purely so the suite can inspect the
    wording, the focused widget and each button's effect without driving a
    modal event loop, which is unreliable headlessly. The window carries its own
    ``result`` dict, so a test reads the same answer the modal caller would.
    """
    answer = {"ok": False}
    win = tk.Toplevel(parent)
    win.title(title)
    try:
        win.transient(parent.winfo_toplevel())
    except tk.TclError:
        pass
    win.resizable(False, False)

    body = ttk.Frame(win, padding=16)
    body.pack(fill=tk.BOTH, expand=True)
    label = ttk.Label(body, text=message, wraplength=460, justify="left")
    label.pack(anchor="w")
    win.label_message = label

    actions = ttk.Frame(body)
    actions.pack(anchor="e", pady=(16, 0))

    def cancel(*_a):
        answer["ok"] = False
        win.destroy()

    def confirm(*_a):
        answer["ok"] = True
        win.destroy()

    btn_cancel = ttk.Button(actions, text="Cancel", command=cancel)
    btn_cancel.pack(side=tk.RIGHT)
    btn_confirm = ttk.Button(actions, text=confirm_label, command=confirm)
    btn_confirm.pack(side=tk.RIGHT, padx=(0, 8))
    # Exposed so a headless test can drive the dialog without a display server.
    win.btn_cancel = btn_cancel
    win.btn_confirm = btn_confirm
    win.result = answer

    win.protocol("WM_DELETE_WINDOW", cancel)
    win.bind("<Escape>", cancel)
    win.cancel = cancel
    # Cancel is the initial focus, so Return activates the safe answer. Recorded
    # explicitly as well: Tk defers focus on an unmapped window, so the intent
    # has to be inspectable without a mapped display.
    win.default_widget = btn_cancel
    btn_cancel.focus_set()
    return win


def _ask_replacement(parent, title: str, message: str, confirm_label: str) -> bool:
    """A modal confirm whose safe answer is the default and holds focus.

    Deliberately not ``messagebox.askyesno``: the destructive action needs its
    own explicit label ("Replace 3 Original Files"), and Cancel must hold focus
    so a stray Enter cannot start a replacement. Escape and the window close
    both cancel, and the window is rebuilt for every run — there is nothing to
    remember, suppress or reuse.
    """
    win = build_replacement_dialog(parent, title, message, confirm_label)
    try:
        win.grab_set()
    except tk.TclError:
        pass
    win.wait_window()
    return bool(win.result["ok"])


# ---------- image logic ----------


def resize_for_audiobook(in_path: Path, out_path: Path, size: int, letterbox: bool):
    """
    Always keep full image visible when letterbox=True:
      - Scale so the LONG side == size
      - Paste on a square canvas with bars if needed.
    """
    img = Image.open(in_path).convert("RGB")
    w, h = img.size

    if letterbox:
        scale = size / max(w, h)
        new_w, new_h = int(round(w * scale)), int(round(h * scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)

        canvas = Image.new("RGB", (size, size), color=(0, 0, 0))
        offset_x = (size - new_w) // 2
        offset_y = (size - new_h) // 2
        canvas.paste(img, (offset_x, offset_y))
        img = canvas
    else:
        scale = size / min(w, h)
        new_w, new_h = int(round(w * scale)), int(round(h * scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - size) // 2
        upper = (new_h - size) // 2
        right = left + size
        lower = upper + size
        img = img.crop((left, upper, right, lower))

    ext = out_path.suffix.lower()
    save_kwargs = {}

    if ext in [".jpg", ".jpeg"]:
        save_kwargs = {"format": "JPEG", "quality": 95}
    elif ext == ".png":
        save_kwargs = {"format": "PNG", "compress_level": 6}
    elif ext in [".heic", ".heif"]:
        save_kwargs = {"format": "HEIF", "quality": 95}
    else:
        out_path = out_path.with_suffix(".jpg")
        save_kwargs = {"format": "JPEG", "quality": 95}

    img.save(out_path, **save_kwargs)
    return out_path


# ---------- GUI ----------


class CoverResizerUI(ttk.Frame):
    """The Cover Resizer tool as an embeddable frame."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)

        self.files: list[Path] = []

        # Cancellation / worker plumbing (mirrors the TTS tool's pattern).
        self._busy = threading.Event()
        self._cancel_event = threading.Event()
        self._log_q: queue.Queue = queue.Queue()

        # Where the next run will go, shown read-only. The numbered run folder
        # is reserved when a validated resize starts, so building this panel
        # creates nothing. The base is changed in Preferences & Data.
        self.var_outdir = tk.StringVar(value=output_paths.destination_hint(TOOL_KEY))
        self._last_run_dir = None

        # Top buttons
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(10, 6))

        self.btn_add = ttk.Button(top, text="Import Images", command=self.add_files)
        self.btn_add.pack(side=tk.LEFT)

        self.btn_remove = ttk.Button(top, text="Remove Selected", command=self.remove_selected)
        self.btn_remove.pack(side=tk.LEFT, padx=8)

        self.btn_clear = ttk.Button(top, text="Clear List", command=self.clear_list)
        self.btn_clear.pack(side=tk.LEFT)

        self.count_var = tk.StringVar(value="0 file(s)")
        ttk.Label(top, textvariable=self.count_var).pack(side=tk.RIGHT)

        # File list
        list_frame = ttk.Frame(self)
        list_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10)

        self.listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=12)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.configure(yscrollcommand=sb.set)

        # Options
        options = ttk.LabelFrame(self, text="Resize Options (applies to all images)")
        options.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10, ipady=4)

        row = 0

        ttk.Label(options, text="Target size (square, px):").grid(
            row=row, column=0, sticky="w", padx=8, pady=4
        )
        self.var_size = tk.IntVar(value=TARGET_SIZE)
        self.entry_size = ttk.Spinbox(
            options, from_=256, to=4096, textvariable=self.var_size, width=6, increment=64
        )
        self.entry_size.grid(row=row, column=1, sticky="w", padx=8, pady=4)

        row += 1
        self.var_letterbox = tk.BooleanVar(value=True)
        self.chk_letterbox = ttk.Checkbutton(
            options,
            text="Keep full image (letterbox into square, no cropping)",
            variable=self.var_letterbox,
        )
        self.chk_letterbox.grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(2, 4)
        )

        # --- source-side mode (Decision 10A) ---------------------------------
        # Off by default, and the safe numbered-copy action is preselected.
        # Replacement needs all three of: this toggle on, that radio chosen,
        # and the per-run confirmation accepted.
        row += 1
        self.var_source_side = tk.BooleanVar(value=False)
        self.chk_source_side = ttk.Checkbutton(
            options,
            text=SOURCE_SIDE_LABEL,
            variable=self.var_source_side,
            command=self._on_source_side_change,
        )
        self.chk_source_side.grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(6, 2)
        )

        row += 1
        self.var_source_action = tk.StringVar(value=ACTION_NUMBERED)
        self.rb_numbered = ttk.Radiobutton(
            options,
            text="Create numbered copies",
            variable=self.var_source_action,
            value=ACTION_NUMBERED,
        )
        self.rb_numbered.grid(row=row, column=0, columnspan=3, sticky="w",
                              padx=(28, 8), pady=(0, 1))
        row += 1
        self.rb_replace = ttk.Radiobutton(
            options,
            text="Replace original files",
            variable=self.var_source_action,
            value=ACTION_REPLACE,
        )
        self.rb_replace.grid(row=row, column=0, columnspan=3, sticky="w",
                             padx=(28, 8), pady=(0, 8))
        self._on_source_side_change()

        row += 1
        ttk.Label(options, text="Output folder:").grid(
            row=row, column=0, sticky="e", padx=8, pady=(2, 2)
        )
        self.entry_outdir = ttk.Entry(
            options, textvariable=self.var_outdir, state="readonly"
        )
        self.entry_outdir.grid(row=row, column=1, columnspan=2, sticky="we",
                               padx=8, pady=(2, 2))
        row += 1
        ttk.Label(
            options,
            text="Each resize gets its own numbered run folder here. "
                 "Change the location in Preferences & Data.",
        ).grid(row=row, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        # Log + progress
        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.log = tk.Text(logf, height=8, wrap="word")
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb2 = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.configure(yscrollcommand=sb2.set)

        # Progress (bar + images-done/percentage label; updated only from the
        # main-thread queue pump)
        self.progress = ui_theme.ProgressIndicator(self, length=400)
        self.progress.frame.pack(side=tk.BOTTOM, pady=(0, 10))

        # Bottom action bar
        action = ttk.Frame(self)
        action.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 10))

        self.btn_convert = ttk.Button(action, text="Resize Covers", command=self.start_resize)
        self.btn_convert.pack(side=tk.LEFT)
        self.btn_cancel = ttk.Button(
            action, text="Cancel", command=self.cancel, state=tk.DISABLED
        )
        self.btn_cancel.pack(side=tk.LEFT, padx=8)

        # Start draining the worker->GUI queue on the main thread.
        self.after(150, self._pump_queue)

    # ------- UI callbacks -------

    def add_files(self):
        files = filedialog.askopenfilenames(
            title="Select cover images",
            initialdir=str(_remembered_dir(KEY_INPUT_DIR)),
            filetypes=[
                ("Images", "*.jpg *.jpeg *.png *.heic *.heif"),
                ("All files", "*.*"),
            ],
        )
        if not files:
            return

        for f in files:
            p = Path(f)
            self.files.append(p)
            self.listbox.insert(tk.END, str(p))

        settings.set(KEY_INPUT_DIR, str(Path(files[0]).parent))
        self.update_count()

    def remove_selected(self):
        sel = list(self.listbox.curselection())
        sel.reverse()
        for idx in sel:
            self.listbox.delete(idx)
            del self.files[idx]
        self.update_count()

    def clear_list(self):
        self.listbox.delete(0, tk.END)
        self.files.clear()
        self.update_count()

    def update_count(self):
        self.count_var.set(f"{len(self.files)} file(s)")

    def _on_source_side_change(self):
        """Enable the two choices only while source-side mode is on.

        Turning the mode off also resets the action to numbered copies, so a
        Replace selection can never survive as a hidden active mode.
        """
        on = bool(self.var_source_side.get())
        if not on:
            self.var_source_action.set(ACTION_NUMBERED)
        state = tk.NORMAL if on else tk.DISABLED
        for widget in (self.rb_numbered, self.rb_replace):
            widget.configure(state=state)

    def effective_mode(self) -> str:
        """The route this panel would actually take right now.

        Replacement requires the toggle *and* the radio; either alone yields a
        safe mode, so a stale radio value behind a switched-off toggle is inert.
        """
        if not self.var_source_side.get():
            return MODE_STANDARD
        return (ACTION_REPLACE if self.var_source_action.get() == ACTION_REPLACE
                else ACTION_NUMBERED)

    def _validated_replacement_sources(self, files):
        """Every source proved replaceable, or raise before anything happens."""
        validated = []
        for src in files:
            resolved = output_paths.validate_source_for_replacement(src)
            if resolved.suffix.lower() not in REPLACEABLE_SUFFIXES:
                raise output_paths.UnsafePathError(
                    f"{resolved.name} cannot be replaced in place because its "
                    f"format is written as .jpg; use numbered copies instead",
                    f"unsupported suffix {resolved.suffix!r}",
                )
            validated.append(resolved)
        if not validated:
            raise output_paths.UnsafePathError(
                "no image could be replaced", "empty validated source list"
            )
        return validated

    def confirm_replacement(self, count: int) -> bool:
        """The approved strong confirmation. Required once per replace run.

        Cancel is the default and holds focus, Escape and the window close both
        cancel, and there is no remembered or suppressible path — the dialog is
        rebuilt for every run.
        """
        return _ask_replacement(
            self,
            REPLACEMENT_TITLE,
            replacement_message(count),
            replacement_button_label(count),
        )

    def start_resize(self):
        if self._busy.is_set():
            return
        if not self.files:
            messagebox.showwarning("No files", "Please import images first.")
            return

        try:
            size = int(self.var_size.get() or TARGET_SIZE)
        except Exception:
            messagebox.showerror("Bad size", "Target size must be a number.")
            return

        if size <= 0:
            messagebox.showerror("Bad size", "Target size must be positive.")
            return

        mode = self.effective_mode()
        files = list(self.files)

        if mode == ACTION_REPLACE:
            # Validate every source *before* the dialog, so the count shown is
            # the count that can actually be processed, and so a rejected
            # import can never reach the replacement boundary.
            try:
                files = self._validated_replacement_sources(files)
            except output_paths.OutputPathError as exc:
                messagebox.showerror("Cannot replace originals", exc.message)
                return
            if not self.confirm_replacement(len(files)):
                self._log_q.put(("log", "\nReplacement cancelled. Nothing was changed.\n"))
                return

        params = {
            "size": size,
            "letterbox": self.var_letterbox.get(),
            "mode": mode,
            "files": files,
            "run_dir": None,
            "planner": None,
            "source_planner": None,
        }

        if mode == MODE_STANDARD:
            # Only the standard route reserves a run; an exception-mode
            # operation must not leave an unused numbered folder behind.
            try:
                reservation = output_paths.reserve_run_directory(TOOL_KEY)
            except output_paths.OutputPathError as exc:
                messagebox.showerror("Output folder", exc.message)
                return
            params["run_dir"] = reservation.run_directory
            params["planner"] = reservation.planner()
            self.var_outdir.set(str(reservation.run_directory))
            self._last_run_dir = reservation.run_directory
            self._log_q.put(("log", f"\nOutput folder: {reservation.run_directory}\n"))
        else:
            params["source_planner"] = output_paths.SourceSidePlanner()
            where = ("beside each source image"
                     if mode == ACTION_NUMBERED else "over each original")
            self._log_q.put(("log", f"\nWriting {where}.\n"))

        self._busy.set()
        self._cancel_event.clear()
        self.progress.update(0, len(params["files"]))
        self.disable_inputs(True)
        self.btn_cancel.configure(state=tk.NORMAL)

        t = threading.Thread(target=self.resize_worker, args=(params,), daemon=True)
        t.start()

    def cancel(self):
        if not self._busy.is_set() or self._cancel_event.is_set():
            return
        self._cancel_event.set()
        self.btn_cancel.configure(state=tk.DISABLED)
        self._log_q.put(("log", "Cancelling… will stop after the current image.\n"))

    def disable_inputs(self, state: bool):
        widgets = [
            self.btn_add,
            self.btn_remove,
            self.btn_clear,
            self.entry_size,
            self.chk_letterbox,
            self.btn_convert,
        ]
        widgets.append(self.chk_source_side)
        for w in widgets:
            w.configure(state=tk.DISABLED if state else tk.NORMAL)
        # The two source-side choices follow the toggle, not the busy state, so
        # they never come back enabled while the mode is off.
        if state:
            for w in (self.rb_numbered, self.rb_replace):
                w.configure(state=tk.DISABLED)
        else:
            self._on_source_side_change()
        # The destination display is never typeable; it only greys out.
        self.entry_outdir.configure(state=tk.DISABLED if state else "readonly")

    def log_write(self, text: str):
        self.log.insert(tk.END, text)
        self.log.see(tk.END)

    # ------- worker -> GUI queue pump (main thread) -------

    def _pump_queue(self):
        try:
            while True:
                kind, payload = self._log_q.get_nowait()
                if kind == "log":
                    self.log_write(payload)
                elif kind == "progress":
                    self.progress.update(*payload)
                elif kind == "done":
                    self.log_write(payload)
                    self._finish_idle()
        except queue.Empty:
            pass
        self.after(150, self._pump_queue)

    def _finish_idle(self):
        self._busy.clear()
        self._cancel_event.clear()
        self.disable_inputs(False)
        self.btn_cancel.configure(state=tk.DISABLED)

    # ------- worker (thread) -------

    def resize_worker(self, params: dict):
        files = params["files"]
        size = params["size"]
        letterbox = params["letterbox"]
        mode = params["mode"]
        planner = params["planner"]
        source_planner = params["source_planner"]
        total = len(files)
        cancelled = False
        replaced = 0

        for idx, in_file in enumerate(files, start=1):
            if self._cancel_event.is_set():
                cancelled = True
                break
            temp_out = None
            try:
                planned_name = in_file.stem + written_suffix(in_file.suffix)
                if mode == ACTION_REPLACE:
                    # A complete sibling is written first; the original stays
                    # untouched until the atomic install below succeeds.
                    temp_out = output_paths.temporary_sibling(
                        in_file, suffix=written_suffix(in_file.suffix)
                    )
                    final_out = in_file
                elif mode == ACTION_NUMBERED:
                    final_out = source_planner.plan_beside(in_file, name=planned_name)
                    output_paths.assert_not_input(final_out, files)
                else:
                    final_out = planner.plan(planned_name)
                    output_paths.assert_not_input(final_out, files)

                self._log_q.put(("log", f"\n[{idx}/{total}] Resizing:\n {in_file}\n -> {final_out}\n"))

                written = resize_for_audiobook(
                    in_file,
                    temp_out if temp_out is not None else final_out,
                    size=size,
                    letterbox=letterbox,
                )

                if mode == ACTION_REPLACE:
                    # Validate the finished image before installing it, so a
                    # truncated or unreadable write never reaches the original.
                    with Image.open(written) as check:
                        check.load()
                        if check.size != (size, size):
                            raise ValueError(
                                f"resized image is {check.size}, expected {(size, size)}"
                            )
                    output_paths.atomic_replace(written, final_out)
                    temp_out = None       # ownership transferred by the replace
                    replaced += 1

                self._log_q.put(("log", " ✓ Done\n"))

            except Exception as e:
                # Remove only this operation's own temporary artifact. The
                # original is byte-for-byte untouched, because the replacement
                # boundary was never crossed.
                try:
                    output_paths.discard_temporary(temp_out)
                except output_paths.OutputPathError:
                    pass
                self._log_q.put(("log", f" ✗ Error: {e}\n"))

            finally:
                self._log_q.put(("progress", (idx, total)))

        # Truthful about a partial batch: anything already installed stays
        # installed, and cancellation never rolls a completed replacement back.
        tail = ""
        if mode == ACTION_REPLACE:
            tail = (f"{replaced} of {total} original(s) replaced; "
                    "any not reached are unchanged.\n")
        if cancelled:
            self._log_q.put(("done", "\nCancelled. " + tail))
        else:
            self._log_q.put(("done", "\nAll done. " + tail))


def build_ui(parent: tk.Misc) -> CoverResizerUI:
    """Build the Cover Resizer UI into ``parent`` and return the frame."""
    ui = CoverResizerUI(parent)
    ui.pack(fill=tk.BOTH, expand=True)
    return ui


def main():
    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("900x640")
    root.minsize(900, 640)
    build_ui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
