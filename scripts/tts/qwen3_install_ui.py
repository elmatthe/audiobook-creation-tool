"""qwen3_install_ui.py — the "Install / repair Qwen3 voices" dialog: the one in-app way to get the voices.

Owner rulings it implements (``Decisions.md``, 2026-10-19, CP6):

* Q2 — CustomVoice (Aiden, Ryan) and Base (the six clones) install independently, plus "Install Both"; the sizes are on
  the buttons and again in the confirmation, **before** anything is acquired; nothing downloads on ordinary launch,
  only when a button here is pressed and confirmed.
* The same dialog serves a first-time user and an existing user (or one who declined earlier): it is reachable from the
  voice panel whenever a Qwen3 voice is selected, and "Check and repair" re-verifies what is installed.
* Q3/Q4 — it states where Qwen3 will run (GPU or CPU, honestly) and, on a platform where the voices are not yet
  available, offers nothing to install.

Two layers, so the logic is testable without a display:

* :class:`SetupSession` -- no Tk. Runs ``qwen3_setup`` on one worker thread and reports through a queue. The worker never
  touches a widget; the dialog drains the queue on the main thread.
* :func:`build_dialog` -- the window. Returns the window without waiting on it (like the app's other dialogs) so a test
  can inspect and drive it; :func:`run_dialog` adds the modal wait.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from shared import appearance
from tts import qwen3_runtime as rt
from tts import qwen3_setup as su

POLL_MS = 150


# --------------------------------------------------------------------------- #
# The session: no Tk
# --------------------------------------------------------------------------- #
class SetupSession:
    """One install/repair at a time, run on a worker thread, reported through :attr:`events`.

    ``events`` carries ``("progress", su.Progress)``, for an analysis one ``("analysis", su.RepairPlan)``, and finally
    exactly one ``("done", su.SetupResult)``. Cancellation is a flag the installer checks between blocks; whatever
    completed is kept.
    """

    def __init__(self, *, thread_factory: Callable[..., threading.Thread] = threading.Thread) -> None:
        self._thread_factory = thread_factory
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self.events: "queue.Queue[tuple[str, object]]" = queue.Queue()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def cancel(self) -> None:
        self._cancel.set()

    def prepare_install(self, components) -> list[str]:
        """The lines to show before confirming: what will be downloaded, how big, what is reused."""
        return su.describe_plan(su.plan_install(components))

    def start_install(self, components) -> bool:
        return self._start(su.install, list(components))

    def start_analysis(self, components=None) -> bool:
        """Phase one of 'Check and repair': a read-only full check. Reports one ("analysis", RepairPlan), then "done"."""
        chosen = list(components) if components is not None else installed_or_partial_components()

        def run(progress, cancel_check):
            plan = su.analyze_repair(chosen, progress=progress, cancel_check=cancel_check)
            self.events.put(("analysis", plan))
            return su.SetupResult(True, "Check finished.")

        return self._start_job(run)

    def start_repair(self, plan) -> bool:
        """Phase two: act on the plan the user has seen and confirmed."""
        return self._start_job(lambda progress, cancel_check: su.repair(
            plan.components, plan=plan, progress=progress, cancel_check=cancel_check))

    def _start(self, operation, components) -> bool:
        if not components:
            return False
        return self._start_job(lambda progress, cancel_check: operation(
            components, progress=progress, cancel_check=cancel_check))

    def _start_job(self, job) -> bool:
        if self.running:
            return False
        self._cancel.clear()

        def run() -> None:
            try:
                result = job(lambda p: self.events.put(("progress", p)), self._cancel.is_set)
            except su.SetupCancelled:
                result = su.SetupResult(False, "Cancelled. What was completed is kept.", cancelled=True)
            except (su.SetupError, rt.Qwen3Unavailable) as exc:
                result = su.SetupResult(False, str(exc))
            except Exception as exc:  # noqa: BLE001 - the dialog must always get a result
                result = su.SetupResult(False, f"The operation stopped unexpectedly: {exc}")
            self.events.put(("done", result))

        self._thread = self._thread_factory(target=run, daemon=True)
        self._thread.start()
        return True

    def drain(self) -> list[tuple[str, object]]:
        out: list[tuple[str, object]] = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out


def installed_or_partial_components() -> list[str]:
    """Models that have a folder on disk (installed, partial or damaged); what 'Check and repair' looks at."""
    return [key for key in rt.MODEL_KEYS if rt.model_spec(key).directory.exists()]


# --------------------------------------------------------------------------- #
# What the dialog says about the present state
# --------------------------------------------------------------------------- #
def state_lines() -> list[str]:
    """Plain-language state: the platform, the engine, each model, where it will run."""
    if not rt.platform_supported():
        return [rt.platform_reason()]
    lines = []
    ok, reason = rt.environment_status()
    lines.append("Voice engine: installed." if ok else f"Voice engine: {_short(reason)}")
    for key in rt.MODEL_KEYS:
        spec = rt.model_spec(key)
        ok, reason = rt.model_status(key)
        if key == rt.MODEL_CUSTOMVOICE:  # the presets by their current registry labels (v0.7.0 P02A), never a fixed name
            voices = " and ".join(v.label for v in rt.QWEN3_VOICES if v.model_key == key)
        else:
            voices = "the six cloned voices"
        lines.append(f"{spec.label} model ({voices}): " + ("installed." if ok else _short(reason)))
        if key == rt.MODEL_BASE and ok:
            from tts import qwen3_clone_setup as qt

            approved = sum(r.state == qt.STATE_APPROVED for r in qt.rows())
            lines.append(f"Cloned voices set up: {approved} of 6"
                         + ("." if approved == 6 else " (use \"Set up cloned voices\" to finish)."))
    lines.append(rt.hardware_summary())
    return lines


def _short(reason: str) -> str:
    """The first sentence of a status reason, without its instruction (the buttons below are the instruction)."""
    first = reason.split(". ")[0].rstrip(".")
    return first + "."


def button_labels() -> dict[str, str]:
    custom, base = rt.model_spec(rt.MODEL_CUSTOMVOICE), rt.model_spec(rt.MODEL_BASE)
    return {
        "customvoice": f"Install CustomVoice ({rt.format_bytes(custom.total_bytes)})",
        "base": f"Install Base ({rt.format_bytes(base.total_bytes)})",
        "both": f"Install Both ({rt.format_bytes(su.both_total_download_bytes())})",
    }


# --------------------------------------------------------------------------- #
# The window
# --------------------------------------------------------------------------- #
def _ask_yes_no(parent: tk.Misc, title: str, message: str) -> bool:
    """The plain confirmation used when the host panel does not hand in its own."""
    from tkinter import messagebox

    return bool(messagebox.askyesno(title=title, message=message, parent=parent))


def build_dialog(parent: tk.Misc, *, theme: Optional[dict] = None, session: Optional[SetupSession] = None,
                 confirm: Optional[Callable[[tk.Misc, str, str], bool]] = None,
                 style_name: Optional[Callable[[Optional[dict], str], str]] = None,
                 on_change: Optional[Callable[[], None]] = None,
                 open_clones: Optional[Callable[[tk.Misc], None]] = None) -> tk.Toplevel:
    """Build the dialog and return it, without waiting on it.

    The returned window exposes what a test needs: ``session``, the buttons (``btn_customvoice``, ``btn_base``,
    ``btn_both``, ``btn_repair``, ``btn_clones``, ``btn_cancel``, ``btn_close``), ``state_var``, ``message_var``, ``progress`` and
    ``poll()`` (one main-thread drain of the worker's queue) / ``refresh()`` (re-read the installed state).

    ``confirm`` and ``style_name`` are handed in by the host panel (the TTS panel, which has adopted the shared job
    foundation); this module deliberately imports none of that foundation itself. Without ``style_name`` every widget
    gets the native style (``""``).
    """
    theme = theme or {}
    session = session or SetupSession()
    confirm = confirm or _ask_yes_no
    st = (lambda key: style_name(theme, key)) if style_name is not None else (lambda key: "")

    win = tk.Toplevel(parent)
    appearance.apply_native_appearance(win, theme)
    win.title("Install / repair Qwen3 voices")
    try:
        win.transient(parent.winfo_toplevel())
    except tk.TclError:
        pass
    win.resizable(False, False)
    colors = theme.get("colors") or {}
    if colors:
        try:
            win.configure(background=colors["window"])
        except tk.TclError:
            pass

    body = ttk.Frame(win, padding=16, style=st("window"))
    body.pack(fill=tk.BOTH, expand=True)
    win.session = session
    win.confirmed = confirm

    state_var, message_var = tk.StringVar(value=""), tk.StringVar(value="")
    win.state_var, win.message_var = state_var, message_var
    ttk.Label(body, textvariable=state_var, justify=tk.LEFT, wraplength=520, style=st("label")).pack(anchor="w")

    actions = ttk.Frame(body, style=st("window"))
    actions.pack(anchor="w", pady=(14, 0))
    labels = button_labels()
    win.btn_customvoice = ttk.Button(actions, text=labels["customvoice"], style=st("button"),
                                     command=lambda: _install(["customvoice"]))
    win.btn_base = ttk.Button(actions, text=labels["base"], style=st("button"), command=lambda: _install(["base"]))
    win.btn_both = ttk.Button(actions, text=labels["both"], style=st("button"), command=lambda: _install(["both"]))
    for column, button in enumerate((win.btn_customvoice, win.btn_base, win.btn_both)):
        button.grid(row=0, column=column, padx=(0, 8))
    win.btn_repair = ttk.Button(actions, text="Check and repair", style=st("button"), command=lambda: _repair())
    win.btn_repair.grid(row=1, column=0, sticky="w", pady=(8, 0))
    win.btn_clones = ttk.Button(actions, text="Set up cloned voices...", style=st("button"), command=lambda: _clones())
    win.btn_clones.grid(row=1, column=1, columnspan=2, sticky="w", pady=(8, 0))

    ttk.Label(body, text=("Nothing is downloaded until you press one of these buttons and confirm. Everything is stored "
                          "inside this app's own folder (the voice engine in .venv-qwen3, the models under "
                          "files/runtime-data/models/qwen3-tts), so deleting those folders removes it again."),
              justify=tk.LEFT, wraplength=520, style=st("secondary_label") or st("label")).pack(anchor="w", pady=(12, 0))

    win.progress = ttk.Progressbar(body, orient=tk.HORIZONTAL, mode="determinate", maximum=1000, length=520,
                                   style=st("progressbar"))
    win.progress.pack(anchor="w", pady=(14, 0))
    ttk.Label(body, textvariable=message_var, justify=tk.LEFT, wraplength=520, style=st("label")).pack(
        anchor="w", pady=(4, 0))

    footer = ttk.Frame(body, style=st("window"))
    footer.pack(anchor="e", pady=(16, 0))
    win.btn_cancel = ttk.Button(footer, text="Cancel install", style=st("button"), command=lambda: _cancel())
    win.btn_close = ttk.Button(footer, text="Close", style=st("button"), command=lambda: _close())
    win.btn_close.pack(side=tk.RIGHT)
    win.btn_cancel.pack(side=tk.RIGHT, padx=(0, 8))

    state = {"closing": False, "polling": None, "plan": None}

    def refresh() -> None:
        state_var.set("\n".join(line for line in state_lines() if line))
        running = session.running
        supported = rt.platform_supported()
        installed = {key: rt.model_status(key)[0] for key in rt.MODEL_KEYS}
        enable = supported and not running
        _set(win.btn_customvoice, enable and not installed["customvoice"])
        _set(win.btn_base, enable and not installed["base"])
        _set(win.btn_both, enable and not all(installed.values()))
        _set(win.btn_repair, enable and bool(installed_or_partial_components() or rt.venv_dir().exists()))  # engine-only too
        _set(win.btn_clones, enable and installed["base"] and rt.environment_status()[0])
        _set(win.btn_cancel, running)
        _set(win.btn_close, not running)

    def _set(button, enabled: bool) -> None:
        button.configure(state=tk.NORMAL if enabled else tk.DISABLED)

    def _install(components) -> None:
        try:
            lines = session.prepare_install(components)
        except su.SetupError as exc:
            message_var.set(str(exc))
            return
        if lines == ["Everything you selected is already installed."]:
            message_var.set(lines[0])
            return
        question = "\n".join(lines) + "\n\nDownload and install now? You can cancel at any time."
        if not confirm(win, "Install Qwen3 voices", question):
            return
        if session.start_install(components):
            message_var.set("Starting...")
            win.progress.configure(value=0)
            refresh()
            _schedule()

    def _repair() -> None:
        """Phase one: check everything read-only. What it found, and what fixing it would download, is shown and
        confirmed before anything is changed (see ``poll``)."""
        if not (installed_or_partial_components() or rt.venv_dir().exists()):
            message_var.set("Nothing is installed yet, so there is nothing to repair.")
            return
        if session.start_analysis():
            message_var.set("Checking the Qwen3 engine and every installed file (this can take a minute)...")
            win.progress.configure(value=0)
            refresh()
            _schedule()

    def _cancel() -> None:
        session.cancel()
        message_var.set("Cancelling...")
        _set(win.btn_cancel, False)

    def _clones() -> None:
        """The six cloned voices need their reference transcripts set up once (its own dialog)."""
        if open_clones is not None:
            open_clones(win)
        else:
            from tts import qwen3_clone_setup_ui

            qwen3_clone_setup_ui.run_dialog(win, theme=theme, confirm=confirm, style_name=style_name, on_change=on_change)
        refresh()

    def poll() -> None:
        state["polling"] = None  # this poll has fired; at most one is ever outstanding
        finished = False
        for kind, payload in session.drain():
            if kind == "analysis":
                state["plan"] = payload
            elif kind == "progress":
                message_var.set(payload.message)
                fraction = payload.fraction
                if fraction is not None:
                    win.progress.configure(mode="determinate", value=int(fraction * 1000))
            elif kind == "done":
                finished = True
                message_var.set(payload.message)
                win.progress.configure(value=1000 if payload.ok else win.progress["value"])
        if finished:
            refresh()
            if on_change is not None:
                on_change()
            if state["closing"]:
                _destroy()
                return
            plan, state["plan"] = state["plan"], None
            if plan is not None:
                _offer_repair(plan)
        elif session.running or not session.events.empty():
            _schedule()

    def _offer_repair(plan) -> None:
        """Phase two: say what is wrong and what fixing it would download; act only when the user confirms."""
        lines = su.describe_repair(plan)
        if plan.nothing_to_do:
            message_var.set(lines[0])
            return
        question = "\n".join(lines) + "\n\nRepair now? You can cancel at any time."
        if not confirm(win, "Repair Qwen3 voices", question):
            message_var.set("Nothing was changed.")
            return
        if session.start_repair(plan):
            message_var.set("Starting the repair...")
            refresh()
            _schedule()

    def _schedule() -> None:
        if state["polling"] is not None:
            return  # exactly one poll chain, however many things ask for one
        try:
            state["polling"] = win.after(POLL_MS, poll)
        except tk.TclError:
            state["polling"] = None

    def _close() -> None:
        if session.running:
            state["closing"] = True  # stop the work, then close once it has actually stopped
            _cancel()
            _schedule()
            return
        _destroy()

    def _destroy() -> None:
        handle = state.get("polling")
        if handle is not None:
            try:
                win.after_cancel(handle)  # a pending poll must not outlive the window it belongs to
            except tk.TclError:
                pass
            state["polling"] = None
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", _close)
    win.bind("<Escape>", lambda _event: _close())
    win.poll, win.refresh, win.close_request = poll, refresh, _close
    refresh()
    win.default_widget = win.btn_close
    return win


def run_dialog(parent: tk.Misc, **kwargs) -> None:
    """Show the dialog modally and return when it is closed."""
    win = build_dialog(parent, **kwargs)
    try:
        win.grab_set()
    except tk.TclError:
        pass
    win.wait_window()
