"""qwen3_clone_setup_ui.py — the "Set up cloned voices" dialog: make the six Qwen3 clones usable, once, in the app.

Reached from "Install / repair Qwen3 voices" once the Base model is installed. Three steps, each only when the user asks
(``tts.qwen3_clone_setup`` has the rules):

1. "Install speech recognizer" -- the size is shown and confirmed before anything is downloaded;
2. "Create drafts" -- the six bundled recordings are transcribed on this computer; nothing is approved by this;
3. per voice: play the recording, correct the text, tick "I listened", then "Approve ticked voices".

Like ``qwen3_install_ui`` the work runs on one worker thread (:class:`TranscriptSession`, no Tk) and the window drains its
queue on the main thread, so the logic is testable without a display and :func:`build_dialog` returns without waiting.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from shared import appearance
from tts import qwen3_runtime as rt
from tts import qwen3_setup as su
from tts import qwen3_clone_setup as qt
from tts.qwen3_install_ui import POLL_MS, SetupSession, _ask_yes_no

STATE_WORDS = {qt.STATE_APPROVED: "Approved", qt.STATE_DRAFT: "Draft: listen, correct, approve",
               qt.STATE_MISSING: "No transcript yet", qt.STATE_STALE: "Made for a different recording: create a new draft"}
#: Shown when Approve is pressed with nothing ticked. A named constant, so a string ``.set()`` literal never names a
#: voice (``test_voice_labels`` treats one as a persisted voice setting).
NOTHING_TICKED = "Tick \"I listened\" for each voice you have checked, then approve."


class TranscriptSession(SetupSession):
    """The recognizer install and the drafting, one at a time on a worker thread (see ``SetupSession``)."""

    def start_recognizer_install(self) -> bool:
        return self._start_job(lambda progress, cancel_check: qt.install_recognizer(progress=progress,
                                                                                     cancel_check=cancel_check))

    def start_drafts(self) -> bool:
        return self._start_job(lambda progress, cancel_check: qt.create_drafts(progress=progress,
                                                                                cancel_check=cancel_check))


class WinsoundPlayer:
    """Plays one WAV at a time through Windows' own sound API (standard library; no extra package)."""

    def __init__(self) -> None:
        import winsound

        self._ws = winsound

    def play(self, path) -> None:
        self._ws.PlaySound(str(path), self._ws.SND_FILENAME | self._ws.SND_ASYNC | self._ws.SND_NODEFAULT)

    def stop(self) -> None:
        self._ws.PlaySound(None, 0)


def default_player():
    try:
        return WinsoundPlayer()
    except ImportError:  # not Windows: the Qwen3 voices are not offered there anyway
        return None


def build_dialog(parent: tk.Misc, *, theme: Optional[dict] = None, session: Optional[TranscriptSession] = None,
                 confirm: Optional[Callable[[tk.Misc, str, str], bool]] = None,
                 style_name: Optional[Callable[[Optional[dict], str], str]] = None,
                 on_change: Optional[Callable[[], None]] = None, player=None) -> tk.Toplevel:
    """Build the dialog and return it without waiting. Exposes ``rows`` (per voice: ``voice_id``, ``text``,
    ``listened``, ``state_var``, ``btn_play``), ``btn_install``, ``btn_drafts``, ``btn_approve``, ``btn_cancel``,
    ``btn_close``, ``message_var``, ``poll()`` and ``refresh()`` for tests."""
    theme = theme or {}
    session = session or TranscriptSession()
    confirm = confirm or _ask_yes_no
    player = player if player is not None else default_player()
    st = (lambda key: style_name(theme, key)) if style_name is not None else (lambda key: "")

    win = tk.Toplevel(parent)
    appearance.apply_native_appearance(win, theme)
    win.title("Set up cloned voices")
    try:
        win.transient(parent.winfo_toplevel())
    except tk.TclError:
        pass
    colors = theme.get("colors") or {}
    if colors:
        try:
            win.configure(background=colors["window"])
        except tk.TclError:
            pass
    body = ttk.Frame(win, padding=16, style=st("window"))
    body.pack(fill=tk.BOTH, expand=True)
    win.session = session

    ttk.Label(body, justify=tk.LEFT, wraplength=640, style=st("label"), text=(
        "Each cloned voice copies the speaker of a short recording that comes with the app, and it needs the exact words "
        "spoken in that recording. Set this up once: install the speech recognizer, let it draft the six transcripts on "
        "this computer (nothing is sent anywhere), then listen to each recording, correct the text if a word is wrong, tick "
        "\"I listened\" and approve. Until a voice is approved it stays unavailable.")).pack(anchor="w")

    actions = ttk.Frame(body, style=st("window"))
    actions.pack(anchor="w", pady=(12, 0))
    win.btn_install = ttk.Button(actions, style=st("button"), command=lambda: _install(),
                                 text=f"1. Install speech recognizer ({rt.format_bytes(qt.recognizer_size())})")
    win.btn_drafts = ttk.Button(actions, text="2. Create drafts", style=st("button"), command=lambda: _drafts())
    win.btn_install.grid(row=0, column=0, padx=(0, 8))
    win.btn_drafts.grid(row=0, column=1)
    win.status_var = tk.StringVar(value="")
    ttk.Label(body, textvariable=win.status_var, justify=tk.LEFT, wraplength=640, style=st("label")).pack(
        anchor="w", pady=(8, 0))

    # Six voices do not fit a 768-pixel-high screen with their text boxes, so they scroll inside a box sized to the screen.
    holder = ttk.Frame(body, style=st("window"))
    holder.pack(anchor="w", fill=tk.BOTH, expand=True, pady=(12, 0))
    canvas = tk.Canvas(holder, highlightthickness=0, borderwidth=0, width=700,
                       height=max(240, min(560, win.winfo_screenheight() - 420)))
    if colors:
        try:
            canvas.configure(background=colors["window"])
        except tk.TclError:
            pass
    scroll = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    grid = ttk.Frame(canvas, style=st("window"))
    canvas.create_window((0, 0), window=grid, anchor="nw")
    grid.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
    win.bind("<MouseWheel>", lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"))
    win.rows_canvas = canvas
    win.rows = []
    for index, row in enumerate(qt.rows()):
        frame = ttk.Frame(grid, style=st("window"))
        frame.grid(row=index, column=0, sticky="we", pady=(0, 10))
        ttk.Label(frame, text=row.label, style=st("label")).grid(row=0, column=0, sticky="w")
        state_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=state_var, style=st("secondary_label") or st("label")).grid(
            row=0, column=1, sticky="w", padx=(12, 0))
        btn_play = ttk.Button(frame, text="Play recording", style=st("button"),
                              command=lambda path=row.reference: _play(path))
        btn_play.grid(row=0, column=2, padx=(12, 0))
        btn_stop = ttk.Button(frame, text="Stop", style=st("button"), command=lambda: _stop())
        btn_stop.grid(row=0, column=3, padx=(6, 0))
        text = tk.Text(frame, height=3, width=86, wrap="word", undo=True)
        text.grid(row=1, column=0, columnspan=4, sticky="we", pady=(4, 2))
        listened = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, variable=listened, style=st("checkbutton") or "",
                        text="I listened to the whole recording and the text is exactly what is said").grid(
            row=2, column=0, columnspan=4, sticky="w")
        if player is None:
            btn_play.configure(state=tk.DISABLED)
            btn_stop.configure(state=tk.DISABLED)
        win.rows.append({"voice_id": row.voice_id, "text": text, "listened": listened, "state_var": state_var,
                         "btn_play": btn_play})

    win.progress = ttk.Progressbar(body, orient=tk.HORIZONTAL, mode="determinate", maximum=1000, length=640,
                                   style=st("progressbar"))
    win.progress.pack(anchor="w", pady=(4, 0))
    win.message_var = tk.StringVar(value="")
    ttk.Label(body, textvariable=win.message_var, justify=tk.LEFT, wraplength=640, style=st("label")).pack(
        anchor="w", pady=(4, 0))
    footer = ttk.Frame(body, style=st("window"))
    footer.pack(anchor="e", pady=(12, 0))
    win.btn_approve = ttk.Button(footer, text="3. Approve ticked voices", style=st("button"), command=lambda: _approve())
    win.btn_cancel = ttk.Button(footer, text="Cancel", style=st("button"), command=lambda: _cancel())
    win.btn_close = ttk.Button(footer, text="Close", style=st("button"), command=lambda: _close())
    win.btn_close.pack(side=tk.RIGHT)
    win.btn_cancel.pack(side=tk.RIGHT, padx=(0, 8))
    win.btn_approve.pack(side=tk.RIGHT, padx=(0, 8))

    state = {"closing": False, "polling": None}

    def _set(button, enabled: bool) -> None:
        button.configure(state=tk.NORMAL if enabled else tk.DISABLED)

    def load_rows() -> None:
        current = {r.voice_id: r for r in qt.rows()}
        for widgets in win.rows:
            row = current[widgets["voice_id"]]
            widgets["state_var"].set(STATE_WORDS[row.state])
            widgets["text"].delete("1.0", tk.END)
            widgets["text"].insert("1.0", row.text)
            widgets["listened"].set(False)

    def refresh() -> None:
        running = session.running
        recognizer_ok, recognizer_reason = rt.transcriber_status()
        problem = qt.drafting_problem()
        approved = sum(r.state == qt.STATE_APPROVED for r in qt.rows())
        win.status_var.set(("Speech recognizer: installed. " if recognizer_ok else f"{recognizer_reason} ")
                           + f"{approved} of 6 cloned voices approved.")
        supported = rt.platform_supported()
        _set(win.btn_install, supported and not running and not recognizer_ok)
        _set(win.btn_drafts, not running and problem is None)
        _set(win.btn_approve, not running)
        _set(win.btn_cancel, running)
        _set(win.btn_close, not running)

    def _install() -> None:
        size = rt.format_bytes(qt.recognizer_size())
        question = (f"Download the speech recognizer (Whisper small.en, {size}) into this app's own folder "
                    "(files/runtime-data/models/qwen3-tts)? It is used only to draft the six transcripts and runs on this "
                    "computer. You can cancel at any time.")
        if not confirm(win, "Install speech recognizer", question):
            return
        if session.start_recognizer_install():
            win.message_var.set("Starting...")
            win.progress.configure(value=0)
            refresh()
            _schedule()

    def _drafts() -> None:
        if session.start_drafts():
            win.message_var.set("Transcribing the six recordings on this computer (about a minute)...")
            win.progress.configure(mode="indeterminate")
            win.progress.start(20)
            refresh()
            _schedule()

    def _approve() -> None:
        decisions = {w["voice_id"]: (w["text"].get("1.0", tk.END), True) for w in win.rows if w["listened"].get()}
        if not decisions:
            win.message_var.set(NOTHING_TICKED)
            return
        # Nothing below runs until the store is safely written, and every failure returns BEFORE load_rows(), so the
        # user's edited text and ticks stay on screen for a retry. Anything unexpected (reading the recording, say) is
        # shown too: an exception escaping a Tk callback is silent, and the button then appeared to do nothing.
        try:
            done = qt.approve(decisions)
        except su.SetupError as exc:
            win.message_var.set(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - report it in the dialog, never lose it in Tk's callback handler
            win.message_var.set(f"The approval could not be saved ({type(exc).__name__}: {exc}). Nothing was changed, "
                                "and your text and ticks are kept; click Approve again to retry.")
            return
        load_rows()
        refresh()
        win.message_var.set(f"Approved: {', '.join(done)}. These voices are ready to use.")
        if on_change is not None:
            on_change()

    def _play(path) -> None:
        if player is not None:
            try:
                player.play(path)
            except Exception as exc:  # noqa: BLE001 - a sound problem must not break the dialog
                win.message_var.set(f"The recording could not be played ({exc}).")

    def _stop() -> None:
        if player is not None:
            try:
                player.stop()
            except Exception:  # noqa: BLE001
                pass

    def _cancel() -> None:
        session.cancel()
        win.message_var.set("Cancelling...")
        _set(win.btn_cancel, False)

    def poll() -> None:
        state["polling"] = None
        finished = False
        for kind, payload in session.drain():
            if kind == "progress":
                win.message_var.set(payload.message)
                if payload.fraction is not None:
                    win.progress.configure(mode="determinate", value=int(payload.fraction * 1000))
            elif kind == "done":
                finished = True
                win.progress.stop()
                win.progress.configure(mode="determinate", value=1000 if payload.ok else 0)
                win.message_var.set(payload.message)
        if finished:
            load_rows()
            refresh()
            if on_change is not None:
                on_change()
            if state["closing"]:
                _destroy()
        elif session.running or not session.events.empty():
            _schedule()

    def _schedule() -> None:
        if state["polling"] is not None:
            return
        try:
            state["polling"] = win.after(POLL_MS, poll)
        except tk.TclError:
            state["polling"] = None

    def _close() -> None:
        if session.running:
            state["closing"] = True
            _cancel()
            _schedule()
            return
        _destroy()

    def _destroy() -> None:
        _stop()
        handle = state.get("polling")
        if handle is not None:
            try:
                win.after_cancel(handle)
            except tk.TclError:
                pass
            state["polling"] = None
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", _close)
    win.bind("<Escape>", lambda _event: _close())
    win.poll, win.refresh, win.close_request, win.load_rows = poll, refresh, _close, load_rows
    load_rows()
    refresh()
    return win


def run_dialog(parent: tk.Misc, **kwargs) -> None:
    """Show the dialog modally and return when it is closed."""
    win = build_dialog(parent, **kwargs)
    try:
        win.grab_set()
    except tk.TclError:
        pass
    win.wait_window()
