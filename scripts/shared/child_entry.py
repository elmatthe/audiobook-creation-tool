"""child_entry.py -- the first statements of every ACT-authored Python child on macOS (class A, v0.8.x P1A).

    <python> [interpreter options] child_entry.py -m <module> [args...]
    <python> [interpreter options] child_entry.py -c <code> [args...]
    <python> [interpreter options] child_entry.py <script.py> [args...]

Started by :mod:`shared.child_ownership` with the read end of its owner's lifeline in ``ACT_LIFELINE_FD``. Before
anything else is imported (pip, torch, a probe's own imports), a daemon thread blocks reading that pipe. The owner
never writes to it and is the only process that holds the write end, so the read returns end-of-file exactly when the
owner has gone -- however it went: a normal exit, SIGKILL, a crash, Force Quit or a closed Terminal window. The thread
then ends this child's whole process group (the child leads its own group, so pip's build backends and every other
grandchild go with it). No code has to run in the owner for this to happen, which is why it holds where ``atexit``
cannot.

Standard library only, and deliberately tiny: it must run on the app's base Python and inside every environment, and
it runs before the program it starts. Never imported by the app; Windows never uses it (Job Objects).
"""
import os
import sys

# Run as a script, Python put this file's own folder (scripts/shared) first on sys.path. Nothing may be imported from
# there by the program this starts, so it is removed before any other import (``-I`` already leaves it out).
if sys.path and os.path.abspath(sys.path[0] or os.curdir) == os.path.dirname(os.path.abspath(__file__)):
    del sys.path[0]

LIFELINE_ENV = "ACT_LIFELINE_FD"


def _start_lifeline() -> None:
    raw = os.environ.pop(LIFELINE_ENV, None)  # popped: no grandchild is told about a descriptor it does not hold
    if raw is None:
        return
    try:
        fd = int(raw)
        os.set_inheritable(fd, False)  # a grandchild never holds it; only this process watches it
    except (ValueError, OSError):
        return

    import signal
    import threading

    def watch() -> None:
        while True:
            try:
                if not os.read(fd, 1):
                    break  # end of file: the owner is gone
            except InterruptedError:
                continue
            except OSError:
                break
        # Only a process that leads its own group may end that group; the owner starts every class-A child so, and
        # anything else ends only itself rather than risk signalling its owner's group.
        try:
            if os.getpgrp() == os.getpid():
                os.killpg(os.getpid(), signal.SIGKILL)
        finally:
            os.kill(os.getpid(), signal.SIGKILL)

    threading.Thread(target=watch, name="act-lifeline", daemon=True).start()


def _main() -> None:
    _start_lifeline()
    args = sys.argv[1:]
    if not args:
        raise SystemExit("child_entry: nothing to run")
    import runpy

    # What `python -m`, `python -c` and `python script.py` themselves put first on sys.path, unless -P/-I said not to.
    if not getattr(sys.flags, "safe_path", False):
        if args[0] == "-m":
            sys.path.insert(0, os.getcwd())
        elif args[0] == "-c":
            sys.path.insert(0, "")
        else:
            sys.path.insert(0, os.path.dirname(os.path.abspath(args[0])))
    if args[0] == "-m" and len(args) >= 2:
        sys.argv = [args[1], *args[2:]]
        runpy.run_module(args[1], run_name="__main__", alter_sys=True)
    elif args[0] == "-c" and len(args) >= 2:
        sys.argv = ["-c", *args[2:]]
        code = compile(args[1], "<string>", "exec")
        namespace = {"__name__": "__main__", "__builtins__": __builtins__}
        exec(code, namespace)  # noqa: S102 - the same code `python -c` would run
    else:
        sys.argv = list(args)
        runpy.run_path(args[0], run_name="__main__")


if __name__ == "__main__":
    _main()
