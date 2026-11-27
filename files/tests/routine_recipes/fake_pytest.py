"""A synthetic stand-in for pytest in the gate's own tests (recipe "fake-pytest").

argv is <junit path> <mode> [extra]; output goes to both streams, as pytest's does.
"""
import ctypes, json, os, pathlib, sys, time

junit, mode = pathlib.Path(sys.argv[1]), sys.argv[2]
extra = sys.argv[3] if len(sys.argv) > 3 else None
token = os.environ.get("ACT_GATE_TOKEN", "")
probe_path = os.environ.get("ACT_GATE_PROBE")
error_mode = hex(ctypes.WinDLL("kernel32").GetErrorMode()) if sys.platform == "win32" else None
def row(sink, **fields):
    sink.write(json.dumps(fields) + "\n")


def record(tests, failed=0, skipped=0, exit_status=0, finish=True, drop_first=False):
    """A session record: this many tests, the last ones failed or skipped."""
    with open(probe_path, "x", encoding="utf-8") as sink:
        row(sink, e="session-start", token=token, pid=os.getpid(), ppid=os.getppid(), mode=error_mode)
        ids = [f"synthetic_test.py::test_{index}" for index in range(tests)]
        row(sink, e="initial", ids=ids)  # M1: the initial inventory first, as gate_session_probe.py writes it
        row(sink, e="collected", ids=ids)
        for index, nodeid in enumerate(ids):
            if drop_first and index == 0:
                continue
            if index >= tests - skipped:
                row(sink, e="r", id=nodeid, w="setup", o="skipped", d=0, reason="synthetic skip reason")
            else:
                row(sink, e="r", id=nodeid, w="setup", o="passed", d=0)
                row(sink, e="r", id=nodeid, w="call", o="failed" if index >= tests - skipped - failed else "passed", d=0)
            row(sink, e="r", id=nodeid, w="teardown", o="passed", d=0)
        if finish:
            row(sink, e="session-finish", exit=exit_status, mode=error_mode)


def report(tests, failures=0, errors=0, skipped=0, suite=None, listed=None):
    cases = []
    for index in range(tests if listed is None else listed):
        body = ""
        if index >= tests - skipped:
            body = '<skipped message="synthetic skip reason"/>'
        elif index >= tests - skipped - failures:
            body = '<failure message="boom"/>'
        cases.append(f'<testcase classname="synthetic_test" name="test_{index}">{body}</testcase>')
    junit.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite '
        f'name="{token if suite is None else suite}" tests="{tests}" failures="{failures}" errors="{errors}" '
        f'skipped="{skipped}">{"".join(cases)}</testsuite></testsuites>', encoding="utf-8")


def passed():
    report(3, skipped=1)
    record(3, skipped=1)
    print("SKIPPED [1] synthetic_test.py:4: synthetic skip reason")
    print("2 passed, 1 skipped in 0.01s")
    sys.exit(0)


print("synthetic session starts", flush=True)
print("synthetic stderr line", file=sys.stderr, flush=True)
if mode == "pass":
    passed()
elif mode == "fail":
    print("Traceback (most recent call last):")
    print('  File "synthetic_test.py", line 7, in test_boom')
    print("E   AssertionError: synthetic boom")
    print("FAILED synthetic_test.py::test_boom - AssertionError: synthetic boom")
    report(3, failures=1)
    record(3, failed=1, exit_status=1)
    print("1 failed, 2 passed in 0.01s")
    sys.exit(1)
elif mode == "empty":
    report(0)
    record(0, exit_status=5)
    print("no tests ran in 0.01s")
    sys.exit(5)
elif mode == "collection-error":
    print("ERROR collecting synthetic_test.py")
    report(0, errors=1, listed=0)
    record(0, exit_status=2)
    print("1 error in 0.01s")
    sys.exit(2)
elif mode == "exit0-no-junit":
    record(3)
    print("3 passed in 0.01s")
    sys.exit(0)
elif mode == "exit0-truncated-junit":
    junit.write_text('<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="3"', encoding="utf-8")
    record(3)
    print("3 passed in 0.01s")
    sys.exit(0)
elif mode == "exit0-zero-tests":
    report(0)
    record(0)
    print("no tests ran in 0.01s")
    sys.exit(0)
elif mode == "exit0-junit-failures":
    report(3, failures=1)
    record(3)
    print("3 passed in 0.01s")
    sys.exit(0)
elif mode == "exit0-no-record":
    report(3)
    print("3 passed in 0.01s")
    sys.exit(0)
elif mode == "exit0-unfinished-record":
    report(3)
    record(3, finish=False)
    sys.exit(0)
elif mode == "exit0-masked-session":
    report(3)
    record(3, exit_status=1)
    sys.exit(0)
elif mode == "exit0-stale-report":
    report(3, suite="an-earlier-run-pytest")
    record(3)
    sys.exit(0)
elif mode == "exit0-count-mismatch":
    report(3, listed=2)
    record(3)
    sys.exit(0)
elif mode == "exit0-collected-not-run":
    report(3)
    record(3, drop_first=True)
    sys.exit(0)
elif mode == "wait":
    print("first streamed line", flush=True)
    sys.stdout.write("..partial-progress")  # no newline: still has to reach the log
    sys.stdout.flush()
    go = pathlib.Path(extra)
    deadline = time.monotonic() + 60
    while not go.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    print()
    passed()
elif mode == "forever":
    deadline = time.monotonic() + 60  # bounded, so a lost child can never outlive the test session by much
    while time.monotonic() < deadline:
        print("still running", flush=True)
        time.sleep(0.05)
    sys.exit(0)
elif mode == "touch":
    pathlib.Path(extra).write_text("changed while the gate ran\n", encoding="utf-8")
    passed()
else:
    sys.exit(f"unknown mode {mode}")
