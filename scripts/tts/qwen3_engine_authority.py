"""Spent v3 engine authority at the EXISTING installer's mutation boundaries.

No production caller. An injected observer is trusted code, never launcher JSON.
Missing, damaged and uncertain canonical environments are deliberately distinct.
"""
from __future__ import annotations

import contextlib
import contextvars
import ctypes
import hashlib
import os
import stat
from pathlib import Path

from shared import artifact_store as store
from shared import artifact_transfer as transfer
from shared import optional_setup_protocol as proto
from shared import venv_layout
from tts import qwen3_packages as packages
from tts import qwen3_runtime as rt
from tts import qwen3_setup as setup

_CURRENT = contextvars.ContextVar('qwen3_engine_execution', default=None)


def preflight(plan, *, cancelled=lambda: False):
    """Action and destructive eligibility before spending/acquisition, then again at mutation."""
    store.require(setup.InstallLock.held_by_this_thread(), 'engine preflight requires InstallLock')
    expected = plan.to_json().get('engine_identity')
    store.require(expected is not None and snapshot(cancelled=cancelled) == expected and expected['selected_canonical'],
                  'unverified/changed canonical engine identity')
    if plan.engine_action == 'install-missing':
        store.require(not expected['canonical_exists'] and not expected['record'],
                      'install-missing requires a genuinely missing canonical environment')
    elif plan.engine_action == 'rebuild-canonical':
        assessment = rt.nested_assessment()
        store.require(expected['canonical_exists'] and setup.safe_to_remove_environment(rt.nested_venv_dir())
                      and assessment.state != venv_layout.UNVERIFIED,
                      'rebuild requires proved damage and safe canonical identity')
    else:
        raise store.ArtifactError('model-only engine mutation is not authorized')


def snapshot(*, cancelled=lambda: False, budget=None):
    """Read-only canonical/parent identity, including interrupted-install recovery state.

    Stat inventory detects changes while packages are staged; no full environment
    package hash/receipt is demanded of an already healthy manual installation.
    """
    with transfer.metadata_budget(budget, cancelled=cancelled) as budget:
        return _snapshot(budget)


def _snapshot(budget):
    root, canonical, parent = rt.repo_root(), rt.nested_venv_dir(), rt.parent_venv_dir()
    store.require(not rt.environment_location_problem(canonical)
                  and venv_layout.unsafe_component(root, parent) is None,
                  'unverified canonical/parent environment')
    with contextlib.ExitStack() as held:
        # Pin existing ancestors even for absent state/canonical leaves. No mkdir.
        for target in (canonical, rt.state_path()):
            walked = root
            for part in target.parent.relative_to(root).parts:
                budget.check()
                walked /= part
                held.enter_context(store.boundary(root, walked))
                if not transfer.metadata_exists(walked):
                    break
                store.require(walked.is_dir(), 'unverified metadata ancestor')
            else:
                held.enter_context(store.boundary(root, target))
        held.enter_context(store.boundary(root, parent / 'pyvenv.cfg'))
        # Same parent-repair exclusion as parent_problem, without its unbounded sorted list.
        held.enter_context(store.boundary(root, root / 'probe'))
        root_before = transfer.metadata_identity(root)
        with os.scandir(parent.parent) as scan:
            for entry in scan:
                budget.check()
                budget.account(entry.name)
                store.require(not entry.name.startswith(parent.name + '.replaced'),
                              'unverified pending parent repair')
        result = _snapshot_pinned(root, canonical, parent, budget, held)
        store.require(transfer.metadata_identity(root) == root_before, 'repository changed during inventory')
        return result


def _snapshot_pinned(root, canonical, parent, budget, held):
    # The legacy reader intentionally tolerates invalid records. That fallback is
    # not proof of absence for a destructive/exclusive v3 engine operation.
    state = {}
    state_exists = transfer.metadata_exists(rt.state_path())
    state_identity = transfer.metadata_identity(rt.state_path()) if state_exists else None
    if state_exists:
        try:
            state = proto.strict_json(transfer.read_metadata(root, rt.state_path(), budget))
        except proto.ProtocolError as exc:
            raise store.ArtifactError('unverified engine state file: ' + str(exc)) from exc
        store.require('schema' not in state or state['schema'] == 1, 'unverified engine state schema')
    record = state.get(rt.NESTED_RECORD, {})
    store.require(type(record) is dict and (rt.NESTED_RECORD not in state or (
        type(record.get('path')) is str and venv_layout.same_path(record['path'], canonical)
        and record.get('stage') in (rt.STAGE_CREATING, rt.STAGE_CREATED, rt.STAGE_INSTALLED, rt.STAGE_REMOVING))),
        'unverified canonical environment record')
    identity = transfer.metadata_identity
    parent_info = parent.stat(follow_symlinks=False)
    cfg = parent / 'pyvenv.cfg'
    cfg_identity = identity(cfg)
    parent_cfg = hashlib.sha256(transfer.read_metadata(root, cfg, budget)).hexdigest()
    entries = []
    exists = transfer.metadata_exists(canonical)
    if exists:
        store.require(canonical.is_dir(), 'canonical environment is not a directory')
        pending = [canonical]
        budget.take('entries')  # The canonical '.' identity is an inventory entry too.
        root_row = ['.', identity(canonical)]
        budget.account(root_row)
        entries.append(root_row)
        while pending:
            budget.check()
            folder = pending.pop()
            held.enter_context(_inventory_directory(root, folder))
            with os.scandir(folder) as scan:
                for entry in scan:
                    budget.take('entries')
                    budget.account(entry.name)
                    path = folder / entry.name
                    store.require(not venv_layout.is_link(path), 'unverified linked environment entry')
                    info = path.stat(follow_symlinks=False)
                    store.require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode),
                                  'unverified environment entry type')
                    row = [str(path.relative_to(canonical)), identity(path)]
                    budget.account(row)
                    entries.append(row)
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(path)
        for name, expected in entries:
            budget.check()
            store.require(identity(canonical / name) == expected, 'environment changed during inventory')
    parent_after = parent.stat(follow_symlinks=False)
    store.require(identity(cfg) == cfg_identity and transfer.metadata_exists(canonical) == exists
                  and (parent_after.st_dev, parent_after.st_ino) == (parent_info.st_dev, parent_info.st_ino)
                  and transfer.metadata_exists(rt.state_path()) == state_exists
                  and (not state_exists or identity(rt.state_path()) == state_identity),
                  'environment metadata changed during inventory')
    result = {'parent': [parent_info.st_dev, parent_info.st_ino],
            'parent_cfg': parent_cfg,
            'canonical_exists': exists, 'entries': sorted(entries),
            'record': record, 'selected_canonical': rt.is_nested(),
            'path': str(canonical)}
    budget.account({key: value for key, value in result.items() if key != 'entries'})
    return result


@contextlib.contextmanager
def _inventory_directory(root, folder):
    """Reuse removal's stronger pins; do not reopen an ancestor denying DELETE sharing.

    removal() already holds the root ancestry and canonical DELETE|LIST handle
    throughout these synchronous snapshots. The traversal retains each newly
    opened parent before visiting children. No destructive pin is released or
    relaxed to make inventory possible, and ordinary callers use store.boundary.
    """
    authority = current()
    captured = getattr(authority, '_removal_handles', None)
    canonical = rt.nested_venv_dir()
    if not captured or canonical not in captured:
        with store.boundary(root, folder / 'probe'):
            yield
        return
    store.require(folder.is_relative_to(canonical) and not venv_layout.is_link(folder),
                  'unsafe pinned inventory directory')
    if folder in captured:
        yield  # Existing DELETE|LIST handle denies write/delete sharing.
        return
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    handle = create(str(folder), 1, 1, None, 3, 0x02200000, None)
    store.require(handle != ctypes.c_void_p(-1).value, 'cannot pin inventory directory')
    try:
        store.require(not venv_layout.is_link(folder) and folder.resolve() == folder,
                      'inventory directory changed')
        yield
    finally:
        close(handle)


@contextlib.contextmanager
def execution(planner, plan, operation, package_set):
    """Mint only after spent terms and sealed package proof, scoped to one held lock."""
    store.require(_CURRENT.get() is None and setup.InstallLock.held_by_this_thread(),
                  'engine execution requires one held InstallLock')
    record = packages.checked(package_set, operation)
    store.require(operation.consent.terms == store.canonical(plan.terms)
                  and record['store'].catalog.terms == plan.terms
                  and plan.engine_action != 'none', 'exact spent engine authority required')
    authority = _Execution(planner, plan, operation, package_set)
    token = _CURRENT.set(authority)
    try:
        authority.before('entry', rebuild=plan.engine_action == 'rebuild-canonical')
        yield authority
    finally:
        authority.active = False
        authority.held.close()
        _CURRENT.reset(token)


def current():
    result = _CURRENT.get()
    if result is not None:
        store.require(type(result) is _Execution and result.active
                      and setup.InstallLock.held_by_this_thread(), 'inactive engine authority')
    return result


class _Execution:
    def __init__(self, planner, plan, operation, package_set):
        self.planner, self.plan, self.operation, self.packages = planner, plan, operation, package_set
        self.phase, self.active, self.created = 'approved', True, None
        self.held = contextlib.ExitStack()
        self._removal_handles = None

    def before(self, action, *, rebuild=None):
        store.require(current() is self, 'unspent/forged engine authority')
        setup._check_cancel(self.planner_cancelled)
        packages.checked(self.packages, self.operation, cancelled=self.planner_cancelled)
        canonical = rt.nested_venv_dir()
        store.require(not rt.environment_location_problem(canonical) and not setup.parent_problem(),
                      'environment location changed at mutation')
        approved = self.plan.to_json()['engine_identity']
        parent = rt.parent_venv_dir()
        info = parent.stat(follow_symlinks=False)
        store.require([info.st_dev, info.st_ino] == approved['parent'] and hashlib.sha256(
            (parent / 'pyvenv.cfg').read_bytes()).hexdigest() == approved['parent_cfg'],
            'parent environment identity changed at mutation')
        store.require(self.planner.disk_free(rt.repo_root()) >=
                      rt.environment_installed_bytes() + self.plan.terms['disk']['temporary_headroom_bytes'],
                      'insufficient remaining engine/temp headroom')
        if action in ('entry', 'remove') or (action == 'create' and self.phase == 'approved'):
            expected = self.plan.to_json().get('engine_identity')
            store.require(expected is not None and snapshot(cancelled=self.planner_cancelled) == expected,
                          'environment identity changed; reconfirm')
            observation = self.planner.observer(self.plan.selected, locked=True, cancelled=self.planner_cancelled)
            required = {'install-missing': proto.MISSING, 'rebuild-canonical': proto.DAMAGED}[self.plan.engine_action]
            store.require(observation.engine == required and not observation.busy,
                          'engine readiness/action changed; reconfirm')
            store.require(expected['selected_canonical'], 'legacy engine cannot be mutated')
            if self.plan.engine_action == 'install-missing':
                store.require(not os.path.lexists(canonical) and not expected['record'],
                              'install-missing requires a genuinely missing canonical environment')
            else:
                store.require(os.path.lexists(canonical) and setup.safe_to_remove_environment(canonical),
                              'rebuild-canonical requires safe_to_remove_environment')
        if action == 'entry':
            store.require(rebuild is (self.plan.engine_action == 'rebuild-canonical'), 'engine action mismatch')
            packages.pip_command(venv_layout.interpreter(canonical), self.packages, self.operation,
                                 cancelled=self.planner_cancelled)
        elif action == 'remove':
            store.require(self.plan.engine_action == 'rebuild-canonical' and self.phase == 'approved',
                          'canonical deletion is not authorized')
            self.phase = 'removing'
        elif action == 'removed':
            store.require(self.phase == 'removing' and not os.path.lexists(canonical), 'canonical removal incomplete')
            self.phase = 'removed'
        elif action == 'create':
            store.require(self.phase in ('approved', 'removed') and not os.path.lexists(canonical),
                          'canonical creation is not authorized')
            self.phase = 'creating'
        elif action == 'created':
            store.require(self.phase == 'creating' and rt.nested_assessment(canonical).identity_ok,
                          'created environment identity unproved')
            self.created = self._created_identity()
            self.phase = 'created'
        elif action in ('pip', 'record'):
            store.require(self.phase == ('created' if action == 'pip' else 'pip')
                          and self.created == self._created_identity()
                          and rt.nested_assessment(canonical).identity_ok,
                          'environment identity changed before package/state mutation')
            self.phase = action
        else:
            raise store.ArtifactError('unknown engine mutation boundary')

    @property
    def planner_cancelled(self):
        return packages._LIVE[self.packages]['cancelled']

    def _created_identity(self):
        folder = rt.nested_venv_dir()
        info = folder.stat(follow_symlinks=False)
        return [info.st_dev, info.st_ino, (folder / 'pyvenv.cfg').read_bytes(),
                venv_layout.base_identity(folder), rt.environment_record(folder)]

    def claim_creation(self):
        """Atomic missing -> owned empty directory; venv must never adopt a raced folder."""
        self.before('create')
        folder = rt.nested_venv_dir()
        store.mkdirs(rt.repo_root(), folder.parent)
        self.held.enter_context(_create_directory(rt.repo_root(), folder))

    @contextlib.contextmanager
    def removal(self):
        """Capture the exact approved tree BEFORE deletion; delete only captured handles.

        Directory pins alone do not prevent insertion, and path-based rmtree can
        follow a child directory swapped after enumeration on Windows. Hold every
        approved entry, reject reparse points, then dispose bottom-up by handle.
        Insertions are never traversed/deleted; a nonempty directory fails closed.
        The original installer's state/recovery ordering remains unchanged.
        """
        from ctypes import wintypes
        folder = rt.nested_venv_dir()
        with store.boundary(rt.repo_root(), folder):
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            create = kernel.CreateFileW
            create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                               wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            create.restype = wintypes.HANDLE
            # LIST_DIRECTORY | DELETE, share READ: no rename/reparse/write sharing.
            close = kernel.CloseHandle
            close.argtypes = [wintypes.HANDLE]
            handles = {}
            try:
                handle = create(str(folder), 0x00010001, 1, None, 3, 0x02200000, None)
                store.require(handle != ctypes.c_void_p(-1).value, 'cannot protect canonical removal')
                handles[folder] = handle
                self._removal_handles = handles
                self.before('remove')  # snapshot + fresh state AFTER handle capture
                expected = self.plan.to_json()['engine_identity']
                for relative, _ in sorted(expected['entries'], key=lambda e: len(Path(e[0]).parts)):
                    setup._check_cancel(self.planner_cancelled)
                    if relative == '.':
                        continue
                    path = folder / relative
                    store.require(not venv_layout.is_link(path), 'linked removal entry')
                    child = create(str(path), 0x00010081, 1, None, 3, 0x02200000, None)
                    store.require(child != ctypes.c_void_p(-1).value, 'cannot protect removal entry')
                    handles[path] = child
                    store.require(not venv_layout.is_link(path), 'late reparse removal entry')
                store.require(snapshot(cancelled=self.planner_cancelled) == expected,
                              'environment changed while capturing removal handles')
                def remove():
                    # The installer has just recorded STAGE_REMOVING itself.
                    observed = snapshot(cancelled=self.planner_cancelled)
                    observed['record'] = expected['record']
                    store.require(observed == expected, 'environment changed at destructive boundary')
                    class Disposition(ctypes.Structure):
                        _fields_ = [('DeleteFile', wintypes.BOOLEAN)]
                    dispose = kernel.SetFileInformationByHandle
                    dispose.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
                    dispose.restype = wintypes.BOOL
                    import sys
                    for path in sorted(handles, key=lambda p: len(p.parts), reverse=True):
                        setup._check_cancel(self.planner_cancelled)
                        # Participate in the raw tripwire before EACH native deletion.
                        sys.audit('os.rmdir' if path.is_dir() else 'os.remove', str(path), -1)
                        info = Disposition(True)
                        store.require(dispose(handles[path], 4, ctypes.byref(info), ctypes.sizeof(info)),
                                      'canonical handle deletion refused; incomplete removal retained')
                        close(handles.pop(path))
                yield remove
            finally:
                for handle in reversed(list(handles.values())):
                    close(handle)
                self._removal_handles = None


@contextlib.contextmanager
def _create_directory(root, folder):
    """FILE_CREATE returns the already pinned NEW directory: no mkdir/open race."""
    from ctypes import wintypes
    import sys
    class UnicodeString(ctypes.Structure):
        _fields_ = [('length', wintypes.USHORT), ('maximum', wintypes.USHORT), ('buffer', wintypes.LPWSTR)]
    class Attributes(ctypes.Structure):
        _fields_ = [('length', wintypes.ULONG), ('root', wintypes.HANDLE),
                    ('name', ctypes.POINTER(UnicodeString)), ('attributes', wintypes.ULONG),
                    ('security', ctypes.c_void_p), ('qos', ctypes.c_void_p)]
    class Status(ctypes.Structure):
        _fields_ = [('status', ctypes.c_void_p), ('information', ctypes.c_size_t)]
    with store.boundary(root, folder) as parent:
        name = ctypes.create_unicode_buffer(folder.name)
        size = len(folder.name.encode('utf-16-le'))
        text = UnicodeString(size, size + 2, ctypes.cast(name, wintypes.LPWSTR))
        attrs = Attributes(ctypes.sizeof(Attributes), parent, ctypes.pointer(text), 0x40, None, None)
        create = ctypes.WinDLL('ntdll').NtCreateFile
        create.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, ctypes.POINTER(Attributes),
                           ctypes.POINTER(Status), ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG,
                           wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG]
        create.restype = wintypes.LONG
        handle = wintypes.HANDLE()
        sys.audit('os.mkdir', str(folder), 0o777, -1)
        result = create(ctypes.byref(handle), 0x00100081, ctypes.byref(attrs), ctypes.byref(Status()),
                        None, 0x80, 1, 2, 0x00200021, None, 0)
        store.require(result >= 0, f'canonical exclusive directory creation refused ({result & 0xffffffff:08x})')
        close = ctypes.WinDLL('kernel32').CloseHandle
        close.argtypes = [wintypes.HANDLE]
        try:
            store.require(folder.is_dir() and not venv_layout.is_link(folder), 'unsafe created directory')
            yield
        finally:
            close(handle)
