"""Controlled native presentation/confirmation. No acquisition or app wiring.

Delivery is acknowledged on the Tk thread after an actual Expose and idle paint,
not when posting work. Original retention and strict readback are separate common
lifecycle transitions. Neither is consent or evidence of human comprehension.
"""
from __future__ import annotations

import json
import contextlib
import os
import sys
from pathlib import Path
import threading
import time

from shared import optional_setup_display_controller_v3 as display
from shared import optional_setup_readonly_context_v3 as origin
from shared import optional_setup_planning_bridge_v3 as bridge


class TkDisplayController(display.DisplayLifecycle):
    @classmethod
    def create(cls, run, view):
        if (type(run) is not origin.ReadOnlyPlanningRun or type(view) is not TkPlanningHarness
                or origin._ISSUED.get(id(run.context)) is not run.context or view.run is not run):
            raise display.ControllerError('issued-native-harness-required')
        return cls._bind(run=run, planning=run.planning, session=run.session,
                         display_adapter=view._delivered)

    def _context_is_trusted(self):
        return origin._ISSUED.get(id(self._context)) is self._context


class TkPlanningHarness:
    """One owned Tk pump. All four components remain data, never executable UI.

    Caller supplies only a separately issued read-only run. A final deliberate
    action composes a qualification document only, with no execution or retry.
    """
    def __init__(self, run):
        if (threading.current_thread() is not threading.main_thread()
                or type(run) is not origin.ReadOnlyPlanningRun
                or origin._ISSUED.get(id(run.context)) is not run.context):
            raise display.ControllerError('issued-native-harness-required')
        self._initialize(run, synthetic=False)

    @classmethod
    def for_test(cls, run):
        """Explicit disposable qualification; never grants native-origin authority."""
        if (threading.current_thread() is not threading.main_thread()
                or type(run) is not bridge.PlanningRun
                or bridge._ISSUED.get(id(run.context)) is not run.context):
            raise display.ControllerError('issued-disposable-harness-required')
        self = cls.__new__(cls)
        self._initialize(run, synthetic=True)
        return self

    def _initialize(self, run, *, synthetic):
        if any(name.upper() in ('TCL_LIBRARY', 'TK_LIBRARY', 'TCLLIBPATH', 'TKPATH') for name in os.environ):
            raise display.ControllerError('tk-environment-steering')
        self._tk_pins = contextlib.ExitStack()
        try:
            base = self._tk_pins.enter_context(origin.qualify_tk_runtime())
            import tkinter as tk
            from tkinter import ttk
            import _tkinter
            if (not sys.flags.ignore_environment
                    or Path(tk.__file__) != base / 'Lib/tkinter/__init__.py'
                    or Path(ttk.__file__) != base / 'Lib/tkinter/ttk.py'
                    or Path(_tkinter.__file__) != base / 'DLLs/_tkinter.pyd'):
                raise display.ControllerError('tk-code-origin')
            self.run, self.thread = run, threading.get_ident()
            self.lifecycle = (display.DisposableDisplayController.for_test(run=run,
                planning=run.planning, session=run.session, display_adapter=self._delivered)
                if synthetic else TkDisplayController.create(run, self))
            self.root = tk.Tk()
            if (Path(str(self.root.tk.call('info', 'library'))) != base / 'tcl/tcl8.6'
                    or Path(str(self.root.tk.getvar('tk_library'))) != base / 'tcl/tk8.6'):
                raise display.ControllerError('tk-script-origin')
            self.root.tk.call('set', 'auto_path', (str(base / 'tcl/tcl8.6'), str(base / 'tcl')))
            allowed = {base / 'DLLs/_tkinter.pyd', *list((base / 'DLLs').glob('*.dll'))}
            system = origin.system_directory()
            for path in origin.native_modules():
                # The host also contains approved CPython/pytest libraries; only
                # Tk-specific native images belong to this adapter boundary.
                if ('tcl' in path.name.lower() or 'tk' in path.name.lower()) and path not in allowed \
                        and not path.is_relative_to(system):
                    raise display.ControllerError('tk-native-origin')
        except BaseException:
            if hasattr(self, 'lifecycle'):
                self.lifecycle.invalidate('presentation-interrupted')
            if hasattr(self, 'root') and self.root.winfo_exists():
                self.root.destroy()
            self._tk_pins.close()
            raise
        self.root.title('ACT — ' + ('SYNTHETIC qualification' if synthetic else
                                  'Read-only optional component proposal'))
        self.root.geometry('1000x740')
        self.root.minsize(640, 440)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.bind('<Escape>', lambda event: self.close())
        self._closed = self._exposed = self._completion_posted = False
        self._generation = 0
        self._ready_generation = None
        self._payload = self._expected = None
        self.ack_thread = None
        self.ack_exposed = self.ack_mapped = False
        ttk.Label(self.root, text=('SYNTHETIC fixture — ' if synthetic else '') +
                  'Read-only planning demonstration — installation disabled',
                  font=('Segoe UI', 14, 'bold'), padding=12).pack(fill='x')
        ttk.Label(self.root, text='Early Continue prepares the base application only. '
                  'Selection and display are not consent. The final action creates a qualification '
                  'confirmation only; no downloads, installation or repairs run.', padding=(12, 0, 12, 8),
                  wraplength=900).pack(fill='x')
        self.overview = tk.StringVar(value='Waiting for the contained planning worker…')
        ttk.Label(self.root, textvariable=self.overview, padding=12,
                  wraplength=900, justify='left').pack(fill='x')
        ttk.Label(self.root, text='Complete disclosure, exact identities and full history '
                  '(Tab to focus; arrows/Page Up/Page Down to read; Ctrl+C to copy):',
                  padding=(12, 0)).pack(fill='x')
        panel = ttk.Frame(self.root, padding=12)
        panel.pack(fill='both', expand=True)
        self.details = tk.Text(panel, wrap='word', font=('Consolas', 11), takefocus=True,
                               state='disabled', background='white', foreground='black')
        scroll = ttk.Scrollbar(panel, command=self.details.yview)
        self.details.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.details.pack(fill='both', expand=True)
        self.details.bind('<Expose>', self._on_expose)
        self.root.bind('<Alt-d>', lambda event: self.details.focus_set())
        self.status = tk.StringVar(value='Waiting for complete disclosure. No confirmation issued.')
        ttk.Label(self.root, textvariable=self.status, padding=12, wraplength=900).pack(fill='x')
        buttons = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        buttons.pack(fill='x')
        self.buttons = {}
        install = ttk.Button(buttons, text='Install Selected Components', command=self._install,
                             takefocus=True, default='disabled', state='disabled')
        install.pack(side='left', padx=4)
        # Return works only after deliberately focusing this button. No root
        # default binding can carry an earlier Continue/Enter into confirmation.
        install.bind('<Return>', lambda event: self._install())
        self.buttons['install'] = install
        for label in ('Skip', 'Cancel'):
            button = ttk.Button(buttons, text=label, command=self.close, takefocus=True)
            button.pack(side='right', padx=4)
            self.buttons[label.lower()] = button
        self.buttons['skip'].focus_set()

    def _on_expose(self, event):
        if event.widget is self.details:
            self._exposed = True

    def start(self):
        if threading.get_ident() != self.thread or self.run._started:
            raise display.ControllerError('single-ui-start-required')
        self.run.start()
        self.root.after(20, self._pump)

    def _pump(self):
        if threading.get_ident() != self.thread:
            self.lifecycle.invalidate('presentation-interrupted')
            raise display.ControllerError('ui-thread-required')
        if self._closed:
            return
        try:
            state = self.lifecycle.state
            if state == 'request-issued' and self.run.result() is not None:
                self.lifecycle.admit_candidate()
                self._payload = self.lifecycle.prepare_presentation()
                self._expected = self._payload.raw_disclosure.decode('utf-8')
                self.details.configure(state='normal')
                self.details.insert('1.0', self._expected)
                self.details.configure(state='disabled')
                document = json.loads(self._payload.document)
                operations = ', '.join(f'{name}: {action}' for name, action in document['operations'].items())
                self.overview.set('Proposed effects: ' + operations + '. Repairs/rebuilds, when present, '
                    'are proposed mutations. No action will run. Exact source, network/reuse, disk and '
                    'temporary-headroom terms, estimates and all history follow below. Unknown costs '
                    'remain unknown. Blocked reasons: ' + ('; '.join(document['reasons']) or 'none'))
                self._presentation_started = time.monotonic()
                self.details.focus_set()
                # A fresh expose of the populated widget must precede delivery.
                self._exposed = False
            if self.lifecycle.state == 'presentation-pending':
                if time.monotonic() - self._presentation_started > 10:
                    self.lifecycle.invalidate('retention-timeout')
                elif self._exposed and self.details.winfo_ismapped() and not self._completion_posted:
                    self._completion_posted = True
                    generation, payload = self._generation, self._payload
                    self.root.after_idle(lambda: self._complete(generation, payload))
            if self.lifecycle.state == 'original-retained':
                sample = self.lifecycle._sample()
                with self.lifecycle._lock:
                    self.lifecycle._validate(sample)
            if self.lifecycle.state == 'invalidated':
                self.buttons['install'].state(['disabled'])
                self.status.set('Proposal invalidated: ' + str(self.lifecycle.error_code) +
                                '. Nothing will install. A new explicit planning action is required.')
                return
            if self.lifecycle.state in display._FINAL:
                self.buttons['install'].state(['disabled'])
                return
        except display.ControllerError as exc:
            self.buttons['install'].state(['disabled'])
            self.lifecycle.invalidate('presentation-interrupted')
            self.status.set('Proposal refused: ' + exc.code + '. Nothing will install.')
            return
        except Exception:
            self.buttons['install'].state(['disabled'])
            self.lifecycle.invalidate('presentation-interrupted')
            self.status.set('Presentation failed. Nothing will install.')
            return
        self.root.after(20, self._pump)

    def _delivered(self, payload):
        return (threading.get_ident() == self.thread and not self._closed
                and payload is self._payload and self._exposed
                and self.details.winfo_ismapped() and self.root.winfo_ismapped()
                and self.details.cget('state') == 'disabled'
                and self._expected == payload.raw_disclosure.decode('utf-8')
                and self.details.get('1.0', 'end-1c') == self._expected
                and self._completion_posted)

    def _complete(self, generation, payload):
        if threading.get_ident() != self.thread:
            self.lifecycle.invalidate('presentation-interrupted')
            return
        if self.lifecycle.state in display._FINAL:
            return
        if self._closed or generation != self._generation or payload is not self._payload:
            self.lifecycle.invalidate('presentation-interrupted')
            if not self._closed:
                self.buttons['install'].state(['disabled'])
            return
        try:
            self.lifecycle.acknowledge_display(payload)
            self.ack_thread = threading.get_ident()
            self.ack_exposed, self.ack_mapped = self._exposed, bool(self.details.winfo_ismapped())
            self.lifecycle.retain_original()
            self.lifecycle.readback()
            self._ready_generation = (generation, id(payload))
            if self.lifecycle.confirmation_eligible():
                doc = json.loads(payload.document)
                repair = (payload.to_json()['engine_action'] == 'rebuild-canonical'
                          or any(r['scope'] == 'repair' for r in doc['components']))
                if repair:
                    self.buttons['install'].configure(text='Install Selected Components — '
                        'Repair/Rebuild Disclosed Components')
                self.buttons['install'].state(['!disabled'])
            self.status.set('Complete disclosure delivered on the Tk thread, original retained, '
                            'independent readback matched. A separate final action is required. '
                            'Qualification only; installation disabled.')
        except display.ControllerError:
            self.lifecycle.invalidate('presentation-interrupted')
            self.buttons['install'].state(['disabled'])

    def _install(self):
        if threading.get_ident() != self.thread:
            self.lifecycle.invalidate('presentation-interrupted')
            raise display.ControllerError('ui-thread-required')
        if self._closed or self.lifecycle.state in display._FINAL:
            return
        self.buttons['install'].state(['disabled'])
        try:
            if (self.run is not self.lifecycle._run
                    or self._ready_generation != (self._generation, id(self._payload))
                    or not self._delivered(self._payload)):
                self.lifecycle.invalidate('presentation-interrupted')
                raise display.ControllerError('live-presentation-required')
            self.lifecycle.confirm()
            self.status.set('One exact qualification confirmation validated. No consent spent; '
                            'no installation or repair executed. This intention is complete.')
        except display.ControllerError as exc:
            self.status.set('Confirmation refused: ' + exc.code + '. No retry for this intention; '
                            'publication may be incomplete if uncertain. Nothing will install.')

    def close(self):
        if threading.get_ident() != self.thread:
            self.lifecycle.invalidate('presentation-interrupted')
            raise display.ControllerError('ui-thread-required')
        if self._closed:
            return
        self._closed = True
        self._generation += 1
        self.lifecycle.cancel()
        try:
            self.root.destroy()
        finally:
            self._tk_pins.close()
