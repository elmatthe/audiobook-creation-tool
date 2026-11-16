"""Test-only (v0.8.x P2): the REAL local-engine worker (``tts/local_engine_worker.py``: its protocol, its private
protocol channel, its error handling) serving a stand-in engine instead of a model.

    <python> -I -B local_engine_stub.py kokoro          (started by a WorkerHost whose argv names this file)

The host starts it exactly as it starts the real worker -- through its owner, so ``child_entry.py`` runs first and the
lifeline thread is watching before this file is read. Behaviour comes from ``ACT_STUB_BEHAVIOUR`` (JSON):

* ``mode``: ``ok`` (a sine whose length follows the text), ``float64``, ``nan``, ``wrong-rate``, ``short-file``,
  ``crash`` (exits 3 in the middle of a chunk, after a last word on stderr), ``hang`` (never answers),
  ``ignore-term`` (ignores SIGTERM and blocks inside a native call, ``select``, until killed), ``noise`` (prints
  library-like lines to fd 1 and Python's stdout before answering), ``assets`` (load refused as a missing model);
* ``seconds``: how long each chunk's "inference" takes (a native ``select`` wait, so no Python check can interrupt it);
* ``record``: a file each request is appended to (JSON), so a test can prove what was and was not asked.
Never shipped.
"""

from __future__ import annotations

import json
import os
import select
import signal
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from tts import local_engine_worker as worker  # noqa: E402

BEHAVIOUR = json.loads(os.environ.get("ACT_STUB_BEHAVIOUR", "{}"))
MODE = BEHAVIOUR.get("mode", "ok")


def _record(request: dict) -> None:
    path = BEHAVIOUR.get("record")
    if path:
        with open(path, "a", encoding="utf-8") as sink:
            sink.write(json.dumps({"pid": os.getpid(), **request}) + "\n")


def _native_wait(seconds: float) -> None:
    """Block inside a C call for ``seconds`` (forever when negative): what a torch operation looks like to Python."""
    read, _write = os.pipe()
    select.select([read], [], [], None if seconds < 0 else seconds)


class StubAdapter:
    sample_rate = 24000

    def versions(self) -> dict:
        return {"stub": "1"}

    def load(self, request: dict) -> dict:
        _record({"op": "load", **request})
        if MODE == "assets":
            from tts.model_assets import AssetsUnavailable

            raise AssetsUnavailable("Kokoro's model file kokoro-v1_0.pth is missing. Nothing was downloaded.")
        return {"lang_code": request.get("lang_code"), "cached": False, "load_s": 0.01, "device": "cpu",
                "dtype": "float32", "threads": 1}

    def synthesize(self, request: dict):
        import numpy as np

        _record({"op": "synth", **{k: v for k, v in request.items() if k != "out"}})
        if MODE == "ignore-term":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            print("stub: ignoring SIGTERM, blocked in a native call", file=sys.stderr, flush=True)
            _native_wait(-1)
        if MODE == "hang":
            _native_wait(-1)
        if MODE == "crash":
            print("stub: the engine's last words before it fell over", file=sys.stderr, flush=True)
            os._exit(3)
        if MODE == "noise":
            os.write(1, b"native library chatter on fd 1\n")
            print("python library chatter on stdout")
        seconds = float(BEHAVIOUR.get("seconds", 0.0))
        if seconds:
            _native_wait(seconds)
        text = str(request["text"])
        length = 240 * max(1, len(text))
        pcm = (0.25 * np.sin(2 * np.pi * 220 * np.arange(length) / 24000)).astype(np.float32)
        if MODE == "float64":
            pcm = pcm.astype(np.float64)
        elif MODE == "nan":
            pcm[len(pcm) // 2] = np.nan
        elif MODE == "wrong-rate":
            self.sample_rate = 22050
        return pcm, {"segments": 1, "phonemes": [text[::-1]]}


def _short_file_write(pcm, out: str) -> None:
    import numpy as np

    with open(out, "wb") as handle:
        np.save(handle, pcm[: len(pcm) // 2], allow_pickle=False)


worker.ADAPTERS["kokoro"] = StubAdapter
if MODE == "short-file":
    worker._write_pcm = _short_file_write

if __name__ == "__main__":
    sys.exit(worker.main(sys.argv[1:]))
