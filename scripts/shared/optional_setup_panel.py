"""optional_setup_panel.py — the review → install → result panel for the optional voices.

v0.7.0 release. One Tk frame, used by the first-run wizard (``shared.bootstrap``, after the app's environment is built)
and by the TTS panel's *Install & Continue*. It drives ``shared.optional_setup_client`` and never blocks the Tk thread:
each worker run happens on a background thread that only posts to a queue, and the frame drains that queue with
``after``.

Owner Option B (2026-10-27): choosing components is not consent; the read-only plan is shown in full first; the one
affirmative action is the **Install Selected Components** button (no keyboard default), pressed once; Skip and Cancel
never download anything, keep what already works, and are never retried automatically. A retry is a new plan and a new
confirmation.

``on_done(outcome)`` is called exactly once with one of:

* ``{"state": "installed", "verified": [...]}`` -- everything chosen is installed and proved working;
* ``{"state": "ready"}`` -- nothing needed installing;
* ``{"state": "skipped"}``, ``{"state": "cancelled"}`` or ``{"state": "failed", "message": ...}`` -- the caller carries
  on with what already works (``verified`` lists any component proved working anyway).
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable, Iterable, Optional

from shared import optional_setup_client as client
from shared import optional_setup_protocol as proto

POLL_MS = 120


class OptionalSetupPanel(ttk.Frame):
    def __init__(self, master, repo_root: Path, components: Iterable[str], *, on_done: Callable[[dict], None],
                 intro: str = "", run_plan=client.plan, run_install=client.install):
        super().__init__(master, padding=4)
        self.repo_root = Path(repo_root)
        self.components = proto.canonical_selection(components)
        self.on_done = on_done
        self.intro = intro
        self._run_plan, self._run_install = run_plan, run_install
        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._cancel = threading.Event()
        self._plan: Optional[dict] = None
        self._notes: list[str] = []
        self._busy = False
        self._finished = False
        self._confirmed = False
        self.state = "idle"

        self.heading = ttk.Label(self, text="", font=("Segoe UI", 12, "bold"))
        self.heading.pack(anchor="w", pady=(0, 6))
        self.status = ttk.Label(self, text="", justify="left")
        self.status.pack(anchor="w", fill="x")
        self.bar = ttk.Progressbar(self, mode="indeterminate", maximum=1000)
        self.bar.pack(fill="x", pady=(8, 8))
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.text = tk.Text(body, height=14, wrap="word", state="disabled", relief="flat",
                            font=("Segoe UI", 9))
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.buttons = ttk.Frame(self)
        self.buttons.pack(fill="x", pady=(10, 0))
        self.bind("<Configure>", self._wrap)
        self.after(POLL_MS, self._poll)

    # ------------------------------------------------------------------ helpers
    def _wrap(self, _event=None) -> None:
        width = max(300, self.winfo_width() - 24)
        self.status.configure(wraplength=width)

    def _set_text(self, text: str) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", text)
        self.text.configure(state="disabled")

    def _append(self, line: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", line + "\n")
        self.text.see("end")
        self.text.configure(state="disabled")

    def _set_buttons(self, *specs: tuple[str, Callable[[], None]]) -> dict:
        for child in self.buttons.winfo_children():
            child.destroy()
        made = {}
        for label, command in reversed(specs):
            button = ttk.Button(self.buttons, text=label, command=command)
            button.pack(side="right", padx=(8, 0))
            made[label] = button
        return made

    def _thread(self, target, *args) -> None:
        self._busy = True
        threading.Thread(target=target, args=args, daemon=True).start()

    def _finish(self, outcome: dict) -> None:
        if self._finished:
            return
        self._finished = True
        self.on_done(outcome)

    # ------------------------------------------------------------------ 1. plan
    def start(self) -> None:
        """Check this computer for the chosen components (read-only)."""
        if self._busy or self._finished:
            return
        self.state = "checking"
        self._cancel.clear()
        self._confirmed = False
        self.heading.configure(text="Checking what is already installed")
        self.status.configure(text=(self.intro + "\n\n" if self.intro else "") +
                              "Looking for voices and files already on this computer. Nothing is downloaded.")
        self._set_text("")
        self.bar.configure(mode="indeterminate")
        self.bar.start(12)
        self._set_buttons(("Cancel", self._cancel_checking))
        self._thread(self._plan_worker)

    def _plan_worker(self) -> None:
        try:
            first = self._run_plan(self.repo_root, self.components, cancelled=self._cancel.is_set)
            notes: list[str] = []
            result = first
            plan = first.get("plan")
            if first.get("state") == proto.SUCCEEDED and plan is not None and client.blocked(plan):
                notes = [f"{label}: cannot be installed now ({why})." for label, why in client.blocked(plan)]
                keep = client.acquirable(plan) + client.ready(plan)
                result = self._run_plan(self.repo_root, keep, cancelled=self._cancel.is_set) if keep else \
                    {"state": proto.SUCCEEDED, "plan": None}
            self._queue.put(("planned", result, notes))
        except client.SetupUnavailable as exc:
            self._queue.put(("unavailable", str(exc)))
        except Exception as exc:  # noqa: BLE001 - shown, never a crash of the window
            self._queue.put(("unavailable", f"{type(exc).__name__}: {exc}"))

    def _cancel_checking(self) -> None:
        self._cancel.set()
        self.status.configure(text="Stopping the check...")

    # ------------------------------------------------------------------ 2. review
    def _show_plan(self, result: dict, notes: list[str]) -> None:
        self.bar.stop()
        self.bar.configure(mode="determinate", value=0)
        if self._cancel.is_set() or result.get("state") == proto.CANCELLED_STATE:
            self._finish({"state": "cancelled"})
            return
        plan = result.get("plan")
        if result.get("state") != proto.SUCCEEDED or (plan is None and not notes):
            self._show_failure(client.result_text(result), retry=True)
            return
        self._plan, self._notes = plan, notes
        extra = ("\n".join(notes) + "\n\n") if notes else ""
        if plan is None or not client.needs_install(plan):
            self.state = "ready"
            self.heading.configure(text="Nothing needs to be installed" if not notes else
                                   "Some choices cannot be installed now")
            ready = [proto.LABELS[c] for c in (client.ready(plan) if plan else ())]
            self.status.configure(text=("Already installed and working: " + ", ".join(ready) + ".") if ready else
                                  "Nothing you chose can be installed on this computer right now.")
            self._set_text(extra + (client.disclosure(plan) if plan else ""))
            self._set_buttons(("Continue", lambda: self._finish(
                {"state": "ready" if not notes else "failed", "message": " ".join(notes),
                 "verified": list(client.ready(plan) if plan else ())})))
            return
        self.state = "review"
        self.heading.configure(text="Review what will be installed")
        self.status.configure(text="Nothing has been downloaded yet. Read the list below, then choose Install "
                                   "Selected Components, or Skip to continue without them.")
        self._set_text(extra + client.disclosure(plan))
        made = self._set_buttons(("Skip", lambda: self._finish({"state": "skipped"})),
                                 ("Install Selected Components", self._confirm))
        made["Install Selected Components"].configure(default="normal")  # never the Enter-key default

    # ------------------------------------------------------------------ 3. install
    def _confirm(self) -> None:
        """The person's live click: the only place a consent is created. A second click does nothing."""
        if self._confirmed or self._busy or self._plan is None or self.state != "review":
            return
        self._confirmed = True
        try:
            consent = client.consent_for(self._plan)
        except proto.ProtocolError as exc:
            self._show_failure(f"These choices cannot be installed now: {exc}", retry=True)
            return
        self.state = "installing"
        self._cancel.clear()
        self.heading.configure(text="Installing")
        self.status.configure(text="Starting...")
        self._set_text("")
        self.bar.configure(mode="indeterminate")
        self.bar.start(12)
        self._set_buttons(("Cancel", self._cancel_install))
        self._thread(self._install_worker, self._plan, consent)

    def _install_worker(self, plan: dict, consent: proto.Consent) -> None:
        try:
            result = self._run_install(self.repo_root, plan, consent, cancelled=self._cancel.is_set,
                                       on_event=lambda event: self._queue.put(("event", event)))
            self._queue.put(("installed", result))
        except client.SetupUnavailable as exc:
            self._queue.put(("unavailable", str(exc)))
        except Exception as exc:  # noqa: BLE001
            self._queue.put(("unavailable", f"{type(exc).__name__}: {exc}"))

    def _cancel_install(self) -> None:
        self._cancel.set()
        self.status.configure(text="Cancelling... (anything already working is kept)")

    def _show_event(self, event: dict) -> None:
        line, fraction = client.progress_text(event)
        if not line:
            return
        self.status.configure(text=line)
        if fraction is None:
            if str(self.bar.cget("mode")) != "indeterminate":
                self.bar.configure(mode="indeterminate")
                self.bar.start(12)
        else:
            if str(self.bar.cget("mode")) != "determinate":
                self.bar.stop()
                self.bar.configure(mode="determinate")
            self.bar.configure(value=int(fraction * 1000))
        payload = event.get("payload") or {}
        if event.get("kind") == "progress" and payload.get("total") and fraction is not None and fraction < 1:
            return  # byte updates stay in the status line; the log keeps the steps
        self._append(line)

    def _show_result(self, result: dict) -> None:
        self.bar.stop()
        state = result.get("state")
        if state == proto.SUCCEEDED:
            self.state = "done"
            self.bar.configure(mode="determinate", value=1000)
            self.heading.configure(text="Installed")
            self.status.configure(text=client.result_text(result))
            self._set_buttons(("Continue", lambda: self._finish(
                {"state": "installed", "verified": list(result.get("verified", ()))})))
            return
        if state == proto.CANCELLED_STATE:
            self._finish({"state": "cancelled", "verified": list(result.get("verified", ()))})
            return
        self._show_failure(client.result_text(result), retry=True, verified=list(result.get("verified", ())))

    def _show_failure(self, message: str, *, retry: bool, verified=()) -> None:
        self.state = "failed"
        self.bar.stop()
        self.bar.configure(mode="determinate", value=0)
        self.heading.configure(text="The voices could not be installed")
        self.status.configure(text=message + "\n\nAnything that already worked is unchanged. You can try again "
                                             "(a new check is made first), or continue without these voices.")
        specs = [("Continue without them", lambda: self._finish(
            {"state": "failed", "message": message, "verified": list(verified)}))]
        if retry:
            specs.append(("Try again", self._retry))
        self._set_buttons(*specs)

    def _retry(self) -> None:
        if self._busy or self._finished:
            return
        self._plan = None
        self.start()

    # ------------------------------------------------------------------ queue
    def _poll(self) -> None:
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == "event":
                    self._show_event(item[1])
                    continue
                self._busy = False
                if kind == "planned":
                    self._show_plan(item[1], item[2])
                elif kind == "installed":
                    self._show_result(item[1])
                elif kind == "unavailable":
                    self._show_failure("Optional voice setup could not start: " + item[1], retry=True)
        except queue.Empty:
            pass
        if not self._finished:
            try:
                self.after(POLL_MS, self._poll)
            except tk.TclError:  # the window was closed
                self._cancel.set()

    def close_requested(self) -> bool:
        """The window is closing: cancel anything running. Returns True if it may close now."""
        self._cancel.set()
        return not self._busy
