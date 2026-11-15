"""child_guardian.py -- the ACT guardian: ends its own process group when its owner is gone (macOS; v0.8.x P1A).

    <python> -I child_guardian.py        (started by shared.child_ownership, never by hand)

Third-party executables an owner runs (``codesign``, FFmpeg, ...) cannot run ACT's lifeline thread, so the owner starts
each of them inside this guardian's process group (``Popen(process_group=<guardian pid>)``: the child joins the group
before it executes, so there is no moment in which it is outside a contained group). The guardian holds the read end of
the owner's lifeline. When the read returns end-of-file -- the owner exited, was SIGKILLed, crashed, was force-quit or
lost its Terminal window -- it ignores SIGTERM for itself, sends SIGTERM to its group, waits at most one second and
then sends SIGKILL to the group, which ends the guardian last.

It writes ``ready`` to standard output once it holds the descriptor, so the owner never relies on a guardian that did
not start. Standard library only; it signals nothing but the group it leads.
"""
import os
import signal
import sys
import time

LIFELINE_ENV = "ACT_LIFELINE_FD"
#: How long the group has to end after SIGTERM before SIGKILL.
TERM_GRACE_S = 1.0


def main() -> int:
    try:
        fd = int(os.environ.pop(LIFELINE_ENV))
        os.set_inheritable(fd, False)
    except (KeyError, ValueError, OSError):
        return 2
    group = os.getpgrp()
    if group != os.getpid():
        return 3  # never signal a group it does not lead
    # Ctrl+C or a closed window reaches the Terminal's foreground group; this group is not it, but stay certain.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    try:
        sys.stdout.write("ready\n")
        sys.stdout.flush()
        sys.stdout.close()
    except OSError:
        pass
    while True:
        try:
            if not os.read(fd, 1):
                break
        except InterruptedError:
            continue
        except OSError:
            break
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    try:
        os.killpg(group, signal.SIGTERM)
    except OSError:
        pass
    time.sleep(TERM_GRACE_S)
    os.killpg(group, signal.SIGKILL)  # ends the guardian too
    return 0


if __name__ == "__main__":
    sys.exit(main())
