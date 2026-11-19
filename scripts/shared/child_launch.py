"""child_launch.py -- the launch gate of a contained third-party program (macOS; v0.8.x P5-I-R3).

    <python> -I -S child_launch.py <status-fd> <go-fd> <permit> -- <argv...>   (started by shared.child_ownership)

Why it exists. ``subprocess.Popen`` creates a process and executes its program in one call, so a Cancel can neither wait
for it (C1's 0.5 s) nor let it run unordered (an FFmpeg started after the Cancel latch). The owner therefore creates this
gate first, outside any Cancel ordering, inside the ACT guardian's process group and with the caller's stdio. The gate
executes the real program only:

1. after the owner writes ``G`` to the go pipe (inside the run's counted start), and
2. through ``<permit>`` -- a symbolic link to the program that the owner creates for this one start and **removes before
   the counted start ends**. The kernel resolves that name inside ``execve``; once the owner's ``unlink`` has returned,
   no lookup of it can succeed, so a gate that is late, stopped, or whose acknowledgement was lost gets ``ENOENT`` and
   executes nothing. Revocation does not depend on this process cooperating, on any acknowledgement, or on a signal.

It executes nothing but ``<permit>``: no ``PATH`` search, no fallback. Protocol on the status pipe: ``P<pid>\\n`` first;
``E<errno>\\n`` if ``execve`` fails (exit 126 when the permit was revoked, 127 otherwise); nothing more on success (the
pipe is close-on-exec). Exit 125: no go (end-of-file or anything but ``G``); the go byte is read only once
``poll`` says it is there, so the owner can still take back a ``G`` this gate has not read. Standard library only; writes nothing to
stdio; keeps every descriptor the caller gave the program.
"""
import errno
import os
import select
import signal
import sys


def main() -> None:
    try:
        status, go, permit = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
        argv = sys.argv[sys.argv.index("--", 4) + 1:]
    except (IndexError, ValueError):
        os._exit(124)
    try:
        os.write(status, b"P%d\n" % os.getpid())
    except OSError:
        os._exit(124)
    # Wait in poll(), which consumes nothing, and only then read the byte (P5-I-R3 remediation 1): a gate stopped while
    # waiting -- or starved -- never holds its G, so the owner can take an unread G back out of the pipe on revocation
    # (a gate blocked inside read() would have the byte copied to it by the kernel even while stopped).
    poller = select.poll()
    poller.register(go, select.POLLIN | select.POLLHUP | select.POLLERR)
    while True:
        try:
            poller.poll()
            byte = os.read(go, 1)  # never blocks: data is there, or the owner closed its end (end-of-file)
            break
        except InterruptedError:
            continue
        except OSError:
            byte = b""
            break
    if byte != b"G" or not argv:
        os._exit(125)
    try:
        os.close(go)
        os.set_inheritable(status, False)  # closes at a successful exec: the owner's evidence of it
        # What Popen's restore_signals gave the program, which this interpreter changed for itself.
        for name in ("SIGPIPE", "SIGXFSZ"):
            sig = getattr(signal, name, None)
            if sig is not None:
                signal.signal(sig, signal.SIG_DFL)
        os.execve(permit, argv, os.environ)
    except OSError as exc:
        code = exc.errno or 0
        try:
            os.write(status, b"E%d\n" % code)
        finally:
            os._exit(126 if code in (errno.ENOENT, errno.EACCES, errno.ENOTDIR) else 127)
    os._exit(127)


if __name__ == "__main__":
    main()
