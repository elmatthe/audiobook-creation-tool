"""child_guardian.py -- the ACT guardian: ends its own process group when its owner is gone (macOS; v0.8.x P1A).

    <python> -I child_guardian.py        (started by shared.child_ownership, never by hand)

Third-party executables an owner runs (``codesign``, FFmpeg, ...) cannot run ACT's lifeline thread, so the owner starts
each of them inside this guardian's process group (``Popen(process_group=<guardian pid>)``: the child joins the group
before it executes, so there is no moment in which it is outside a contained group). The guardian holds the read end of
the owner's lifeline. When the read returns end-of-file -- the owner exited, was SIGKILLed, crashed, was force-quit or
lost its Terminal window -- it ignores SIGTERM for itself, sends SIGTERM to its group, waits at most one second and
then sends SIGKILL to the group, which ends the guardian last.

v0.8.x P5-I-R3, three additions:

* **A second trigger.** The owner is this process's parent; a kqueue ``NOTE_EXIT`` watch on it fires when the owner
  dies even if the lifeline's write end is still open somewhere (a child of the owner caught between ``fork`` and
  ``exec`` holds a copy until it executes, and one stopped there holds it indefinitely).
* **Launch permits** (``ACT_PERMIT_ROOT``). Before signalling anything it removes the owner's permit folder, so a launch
  gate that was told to start but has not yet looked its program up can never start it after the owner's death.
* **Class-A leaders** (ACT's own Python children, each leading its own session, which this group cannot reach). The
  owner registers each one's pid and kernel start time on this process's stdin (``A <pid> <sec> <usec>``; ``a <pid>``
  when it has been reaped). On the owner's death each registered leader still carrying its recorded start time is sent
  SIGKILL with its group: a leader stopped before its own lifeline thread could run, or stopped at any point, cannot end
  itself, and SIGKILL ends a stopped process.

It writes ``ready`` to standard output once it holds the descriptor, so the owner never relies on a guardian that did
not start. Standard library only; it signals nothing but its own group and the leaders its owner registered.
"""
import os
import select
import shutil
import signal
import struct
import sys
import time

LIFELINE_ENV = "ACT_LIFELINE_FD"
PERMIT_ENV = "ACT_PERMIT_ROOT"
OWNER_ENV = "ACT_OWNER_PID"
SWEEP_TOKEN_ENV = "ACT_SWEEP_TOKEN"
CHILD_TOKEN_ENV = "ACT_CHILD_TOKEN"
#: How long the sweep keeps looking for token holders (a holder may fork while it is being ended).
SWEEP_BOUND_S = 1.0
#: How long the group has to end after SIGTERM before SIGKILL.
TERM_GRACE_S = 1.0


def _start_time(pid):
    """``sysctl kern.proc.pid`` -> ``p_starttime`` as ``(sec, usec)``, or None (the same reader as child_ownership)."""
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        mib = (ctypes.c_int * 4)(1, 14, 1, int(pid))
        size = ctypes.c_size_t(0)
        if libc.sysctl(mib, 4, None, ctypes.byref(size), None, 0) != 0 or size.value <= 36:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if libc.sysctl(mib, 4, buffer, ctypes.byref(size), None, 0) != 0 or size.value <= 36:
            return None
        seconds, micros = struct.unpack_from("=qi", buffer.raw, 0)
        return (int(seconds), int(micros))
    except (OSError, AttributeError, ValueError):
        return None


def _parse(line, leaders):
    """One registry line: ``A <pid> <sec> <usec>`` (a leader), ``a <pid>`` (no longer one), ``Q`` (the owner's orderly end:
    act now, P5-I-R3 remediation 4). True for ``Q``."""
    parts = line.split()
    if parts == ["Q"]:
        return True
    try:
        if len(parts) == 4 and parts[0] == "A":
            leaders[int(parts[1])] = (int(parts[2]), int(parts[3]))
        elif len(parts) == 2 and parts[0] == "a":
            leaders.pop(int(parts[1]), None)
    except ValueError:
        pass
    return False


def _end_leaders(leaders):
    """SIGKILL each registered leader's group (the leader included: it leads it), its identity read again right before
    the one signal (P5-I-R3 remediation 7: never a second, unchecked signal to the bare pid after the first)."""
    for pid, start in list(leaders.items()):
        if pid > 1 and _start_time(pid) == start:  # still the process the owner recorded
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass


def _libc():
    import ctypes

    return ctypes, ctypes.CDLL(None, use_errno=True)


def _all_pids():
    """Every process id on the system (``proc_listallpids``), or [] where it cannot be had."""
    try:
        ctypes, libc = _libc()
        count = libc.proc_listallpids(None, 0)
        if count <= 0:
            return []
        buffer = (ctypes.c_int * (count + 64))()
        count = libc.proc_listallpids(buffer, ctypes.sizeof(buffer))
        return [buffer[i] for i in range(max(0, count)) if buffer[i] > 1]
    except (OSError, AttributeError, ValueError):
        return []


def _environment(pid):
    """The environment entries *pid* was started with (``KERN_PROCARGS2``; only this account's processes answer), as a
    list of ``b"NAME=value"`` -- never its arguments (remediation 3, finding 1: a marker in an argument, or inside
    another variable's value, is not the marker). [] when it cannot be read -- and for Apple platform binaries (e.g.
    ``/bin/sleep``), whose environment macOS leaves out of this record: such a process is not recognised by it. The
    kernel's own ``apple`` strings (``executable_path=...``, ``pfz=...``) may follow the environment unseparated; they
    never equal an ACT tag, which is only ever looked up as one whole entry."""
    try:
        ctypes, libc = _libc()
        mib = (ctypes.c_int * 3)(1, 49, int(pid))  # CTL_KERN, KERN_PROCARGS2
        size = ctypes.c_size_t(0)
        if libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0 or size.value <= 4:
            return []
        buffer = ctypes.create_string_buffer(size.value)
        if libc.sysctl(mib, 3, buffer, ctypes.byref(size), None, 0) != 0:
            return []
        data = buffer.raw[:size.value]
    except (OSError, AttributeError, ValueError):
        return []
    # Layout: int argc; the executable path, NUL-terminated and NUL-padded; argc arguments; the environment entries
    # (each NUL-terminated); then an empty string or the end.
    argc = struct.unpack_from("=i", data, 0)[0]
    rest = data[4:]
    end = rest.find(b"\0")
    if argc < 0 or end < 0:
        return []
    # The executable path is NUL-padded to an 8-byte boundary (measured on macOS 27: the arguments begin at
    # roundup(len(path) + 1, 8)). Skipping exactly that keeps an empty first argument (P5-I-R3 remediation 4); padding
    # that is not all NUL falls back to skipping every NUL, as before.
    start = (end + 1 + 7) // 8 * 8
    if start <= len(rest) and not rest[end:start].strip(b"\0"):
        rest = rest[start:]
    else:
        rest = rest[end:].lstrip(b"\0")
    strings = rest.split(b"\0")
    entries = []
    for item in strings[argc:]:
        if not item:
            break
        entries.append(item)
    return entries


def _sweep(token):
    """SIGKILL every process (and the group it leads) that carries this owner's child token -- an ACT Python child of
    the dead owner or one of its descendants, registered or not, stopped or not, wherever its group or session is
    (P5-I-R3 remediation 2). Each one's start time is read before the token is looked for and again right before the
    signal: a process that ended and handed its id on in between is not signalled. Repeated until none is found or
    :data:`SWEEP_BOUND_S` passes (a holder may fork while it is being ended)."""
    if not token:
        return 0
    needle = ("%s_%s=1" % (CHILD_TOKEN_ENV, token)).encode("ascii")
    me = os.getpid()
    ended = 0
    until = time.monotonic() + SWEEP_BOUND_S
    while True:
        found = 0
        for pid in _all_pids():
            if pid == me:
                continue
            before = _start_time(pid)
            if before is None or needle not in _environment(pid):  # an exact entry of the environment
                continue
            found += 1
            if _start_time(pid) != before:
                continue
            for kill in (os.killpg, os.kill):  # the group it leads (if it leads one), then the process itself
                try:
                    if kill is os.killpg and os.getpgid(pid) != pid:
                        continue
                    if _start_time(pid) == before:
                        kill(pid, signal.SIGKILL)
                        ended += 1
                except OSError:
                    pass
        if not found or time.monotonic() >= until:
            return ended
        time.sleep(0.02)


def _drain(registry, pending, leaders):
    """Read every registry line already written (non-blocking) before acting: an owner that unregistered a leader it
    reaped (``a <pid>``) just before it closed its lifeline is heard first."""
    if registry < 0:
        return pending
    try:
        os.set_blocking(registry, False)
    except OSError:
        return pending
    while True:
        try:
            block = os.read(registry, 4096)
        except (BlockingIOError, InterruptedError):
            break
        except OSError:
            break
        if not block:
            break
        pending += block
        *lines, pending = pending.split(b"\n")
        for line in lines:
            _parse(line.decode("ascii", "replace"), leaders)
    return pending


def main() -> int:
    try:
        fd = int(os.environ.pop(LIFELINE_ENV))
        os.set_inheritable(fd, False)
    except (KeyError, ValueError, OSError):
        return 2
    permits = os.environ.pop(PERMIT_ENV, "")
    token = os.environ.pop(SWEEP_TOKEN_ENV, "")
    try:
        owner = int(os.environ.pop(OWNER_ENV, "0"))
    except ValueError:
        owner = 0
    group = os.getpgrp()
    if group != os.getpid():
        return 3  # never signal a group it does not lead
    # Ctrl+C or a closed window reaches the Terminal's foreground group; this group is not it, but stay certain.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    kq = None
    if owner > 1 and hasattr(select, "kqueue"):
        try:
            kq = select.kqueue()
            kq.control([select.kevent(owner, select.KQ_FILTER_PROC, select.KQ_EV_ADD, select.KQ_NOTE_EXIT)], 0, 0)
        except OSError:
            kq = None  # the owner is already gone (ESRCH): the parent check below sees it
    try:
        sys.stdout.write("ready\n")
        sys.stdout.flush()
        sys.stdout.close()
    except OSError:
        pass
    leaders = {}
    registry = sys.stdin.fileno() if sys.stdin is not None else -1
    pending = b""
    # poll(), not select() (P5-I-R3 remediation 2, finding 10): any descriptor number -- an owner with more than 1024
    # files open hands this process a lifeline above FD_SETSIZE.
    poller = select.poll()
    for each in [fd] + ([registry] if registry >= 0 else []) + ([kq.fileno()] if kq is not None else []):
        poller.register(each, select.POLLIN | select.POLLHUP | select.POLLERR)
    while True:
        if owner > 1 and os.getppid() != owner:
            break  # the owner is no longer this process's parent: it has died
        try:
            ready = [each for each, _event in poller.poll(500)]
        except InterruptedError:
            continue
        except (OSError, ValueError):
            break
        if kq is not None and kq.fileno() in ready:
            break  # NOTE_EXIT: the owner has died
        if fd in ready:
            try:
                if not os.read(fd, 1):
                    break
            except InterruptedError:
                pass
            except OSError:
                break
        if registry in ready:
            try:
                block = os.read(registry, 4096)
            except OSError:
                block = b""
            if not block:
                poller.unregister(registry)  # the owner closed it (or is gone): the other triggers remain
                registry = -1
            else:
                pending += block
                *lines, pending = pending.split(b"\n")
                quit_now = False
                for line in lines:
                    quit_now = _parse(line.decode("ascii", "replace"), leaders) or quit_now
                if quit_now:
                    break  # the owner's orderly end (its lifeline may still be held by a child between fork and exec)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    began = time.monotonic()
    pending = _drain(registry, pending, leaders)
    _end_leaders(leaders)
    _sweep(token)
    try:
        os.killpg(group, signal.SIGTERM)
    except OSError:
        pass
    if permits:  # after the first signals, so a slow file system never delays them
        shutil.rmtree(permits, ignore_errors=True)  # no launch can look its program up any more
    time.sleep(max(0.0, TERM_GRACE_S - (time.monotonic() - began)))
    _end_leaders(leaders)
    _sweep(token)
    os.killpg(group, signal.SIGKILL)  # ends the guardian too
    return 0


if __name__ == "__main__":
    sys.exit(main())
