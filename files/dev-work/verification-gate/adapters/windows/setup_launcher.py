"""The REAL first-run setup window, from a disposable copy of the application, with the observation channel beside it. Test-only.

Runs ``bootstrap.run_with_gui()`` itself, which is what ``Setup_and_Run`` runs when there is no environment yet. It is production's
window, worker thread, messages and exit code. It differs from a person's first run in exactly these places, each named in the
journey's evidence:

  * the application is a copy made for this scenario (``app_root``). ``bootstrap.py`` takes every folder it owns from where it is, so
    the copy is the only installation it can create, repair or write a log into. It refuses to start unless that is so.
  * opening a folder in Explorer is recorded instead of performed (the "Open log folder" button), so no window is left on the owner's
    desktop. Whether the window asked, and for which folder, is what the journey checks.
  * starting the application once setup has finished is recorded instead of performed, so a journey can never leave a second,
    unowned window behind. No journey here reaches it: they end in a refusal or a cancel.

Nothing else is replaced. In particular ``run_setup`` is the real one: a journey gets a failed setup by giving the real check a real
reason to refuse (a folder whose path is too long for Windows), never by scripting an outcome.

Usage: python setup_launcher.py <config.json>
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]


def main() -> int:
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    app_root = Path(config["app_root"])
    sys.path.insert(0, str(app_root / "scripts"))
    sys.path.insert(0, str(HERE))
    record = Path(config["record"])

    def note(kind: str, **facts) -> None:
        with open(record, "a", encoding="utf-8") as sink:
            sink.write(json.dumps({"kind": kind, "at": time.monotonic(), **facts}) + "\n")

    from shared import bootstrap

    if Path(bootstrap.REPO_ROOT).resolve() != app_root.resolve() or app_root.resolve() == REPO_ROOT.resolve():
        raise SystemExit(f"refused: setup would run on {bootstrap.REPO_ROOT}, not the disposable copy {app_root}")
    note("started", app_root=str(bootstrap.REPO_ROOT), venv=str(bootstrap.VENV_DIR), logs=str(bootstrap.LOGS_DIR),
         path_length=len(str(bootstrap.REPO_ROOT)), long_paths=bootstrap.windows_long_paths_enabled())

    bootstrap._open_folder = lambda path: note("open-folder", path=str(path))
    os.startfile = lambda *args, **kwargs: note("startfile", args=[str(item) for item in args])
    bootstrap.launch_gui = lambda log: note("launch-gui") or True

    import tkinter as tk

    from channel import Channel

    real_tk = tk.Tk

    class ObservedTk(real_tk):
        """The window ``run_with_gui`` makes, with the read-only channel attached the moment it exists."""

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._acceptance_channel = Channel(self, channel_file=config["channel_file"], resolve=lambda scope: self)

    tk.Tk = ObservedTk
    code = bootstrap.run_with_gui()
    note("exit", code=code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
