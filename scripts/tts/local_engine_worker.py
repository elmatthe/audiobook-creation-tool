"""local_engine_worker.py -- the child side of the macOS local-engine worker (v0.8.x P2, plan section 11.2.1, MAC-043).

    <python> -I -B <scripts>/shared/child_entry.py <scripts>/tts/local_engine_worker.py <engine>

Started only by :mod:`tts.local_engine_host`, as an ACT-authored class-A child of its owner
(:mod:`shared.child_ownership`): it leads its own process group, and ``child_entry.py`` has already started the thread
that ends that group when the owner's lifeline closes -- before this file, torch or the model is imported. Cancel does
not ask this process anything: the host sends SIGKILL to its group, because it holds no state worth saving.

**What runs here, and nothing else.** The model load and the per-chunk model call. Speech preparation, chunking, the
Cancel checks, PCM assembly, the one encode, publication and every report stay in the parent, in the same functions as
before. Each request carries text the parent has already prepared and chunked; the worker never reads a source file.

**Protocol.** One JSON request per line on standard input; one ``@@EVENT {json}`` line per event on a private copy of
the original standard output. File descriptor 1 itself is pointed at standard error before any library is imported, so
nothing a library prints (Python or native) can reach the protocol channel. Events: ``hello`` (started, versions),
``loaded`` (a model is ready, cold or warm), ``started`` (a chunk's model call begins), ``result`` (its PCM is written),
``error`` (a request failed; the worker keeps serving). The PCM of a ``result`` is a float32 ``.npy`` file at the path
the parent named (inside the parent's own work area); it is written whole and renamed into place before the event, so
the parent never reads a partial file. End of standard input ends the worker.

Engines: ``kokoro`` (P2). Chatterbox's adapter belongs to P3A and is not here.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

PROTOCOL_VERSION = 1
EVENT_PREFIX = "@@EVENT "

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_channel = None  # the protocol stream: a private duplicate of the original standard output
_channel_lock = threading.Lock()


def _take_protocol_channel() -> None:
    """Keep the original standard output for events only and send everything else written to fd 1 to standard error."""
    global _channel
    sys.stdout.flush()
    private = os.dup(1)
    os.set_inheritable(private, False)
    os.dup2(2, 1)
    _channel = os.fdopen(private, "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr


def emit(event: str, **fields) -> None:
    record = {"event": event, **fields}
    line = EVENT_PREFIX + json.dumps(record, separators=(",", ":"), default=str) + "\n"
    with _channel_lock:
        _channel.write(line)
        _channel.flush()


def _peak_footprint() -> int | None:
    """This process's lifetime peak physical footprint (macOS ``rusage_info_v4.ri_lifetime_max_phys_footprint``)."""
    if sys.platform != "darwin":
        return None
    try:
        import ctypes
        import struct

        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        buffer = ctypes.create_string_buffer(512)
        if libproc.proc_pid_rusage(os.getpid(), 4, buffer) != 0:  # RUSAGE_INFO_V4
            return None
        return int(struct.unpack_from("=Q", buffer.raw, 16 + 28 * 8)[0])
    except (OSError, AttributeError, ValueError):
        return None


def _memory() -> dict:
    from tts import worker_limits

    return {"footprint": worker_limits.own_private_bytes(), "peak_footprint": _peak_footprint()}


# --------------------------------------------------------------------------- engines
class KokoroAdapter:
    """Kokoro-82M through the same functions the in-process route uses: the verified local files only
    (``kokoro_synth._get_pipeline``: ``model_assets``, spaCy's pinned model, the eSpeak NG data path, the first-load
    retry), the device ``kokoro_synth`` chooses (CUDA, else the CPU in fp32), and the same pipeline call."""

    sample_rate = 24000

    def __init__(self) -> None:
        from tts import kokoro_synth

        self.ks = kokoro_synth

    def versions(self) -> dict:
        from importlib import metadata

        found = {}
        for name in ("torch", "kokoro", "misaki", "spacy", "en_core_web_sm", "numpy", "espeakng-loader",
                     "phonemizer-fork"):
            try:
                found[name] = metadata.version(name)
            except metadata.PackageNotFoundError:
                found[name] = None
        return found

    def load(self, request: dict) -> dict:
        lang_code = str(request["lang_code"])
        cached = lang_code in self.ks._PIPELINE_CACHE
        began = time.monotonic()
        pipeline = self.ks._get_pipeline(lang_code)
        info = {"lang_code": lang_code, "cached": cached, "load_s": round(time.monotonic() - began, 3)}
        from shared import espeak_data

        data = espeak_data.bundled_data_dir()
        # eSpeak NG's fixed 160-byte path buffer (MAC-035): the data path's length, and the short root if one was made.
        info["espeak"] = {"data_path_chars": len(str(data)) if data is not None else None,
                          "short_root": espeak_data._configured}
        model = getattr(pipeline, "model", None)
        try:
            import torch

            parameter = next(model.parameters()) if model is not None else None
            info.update(device=str(parameter.device) if parameter is not None else None,
                        dtype=str(parameter.dtype).replace("torch.", "") if parameter is not None else None,
                        threads=torch.get_num_threads())
        except Exception:  # noqa: BLE001 - informational only
            pass
        return info

    def synthesize(self, request: dict):
        """``(pcm, details)``: the chunk's PCM exactly as the in-process route builds it (every segment the pipeline
        yields with audio, concatenated in order), or an empty array when no segment had audio."""
        import numpy as np

        pipeline = self.ks._get_pipeline(self.ks._lang_code_for_voice(str(request["voice"])))
        seed = request.get("seed")
        if seed is not None:  # only a parity test sends one; production Kokoro requests carry none (unseeded as before)
            import torch

            torch.manual_seed(int(seed))
        arrays, phonemes = [], []
        for _graphemes, segment_phonemes, audio in pipeline(str(request["text"]), voice=str(request["voice"]),
                                                            speed=float(request["speed"]),
                                                            split_pattern=str(request["split_pattern"])):
            phonemes.append(segment_phonemes)
            if audio is not None:
                arrays.append(audio.numpy() if hasattr(audio, "numpy") else np.array(audio))
        pcm = np.concatenate(arrays) if arrays else np.zeros(0, dtype=np.float32)
        return pcm, {"segments": len(arrays), "phonemes": phonemes}


ADAPTERS = {"kokoro": KokoroAdapter}


def _classify(exc: BaseException) -> str:
    """``assets`` (an approved model file is missing or wrong: nothing downloaded), ``pipeline`` (the engine's packages
    or model would not load) or ``synthesis`` (the model call itself failed)."""
    if type(exc).__name__ == "AssetsUnavailable":
        return "assets"
    return "pipeline"


def _write_pcm(pcm, out: str) -> None:
    import numpy as np

    part = out + ".part"
    with open(part, "wb") as handle:
        np.save(handle, pcm, allow_pickle=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(part, out)


def serve(engine: str) -> int:
    adapter = ADAPTERS[engine]()
    emit("hello", protocol=PROTOCOL_VERSION, engine=engine, pid=os.getpid(), pgid=os.getpgrp(),
         python=sys.version.split()[0], versions=adapter.versions())
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            request = json.loads(raw)
            op, rid = request["op"], request.get("id")
        except (ValueError, KeyError, TypeError):
            emit("error", id=None, kind="protocol", message="an unreadable request")
            continue
        if op == "exit":
            return 0
        if op == "load":
            try:
                info = adapter.load(request)
            except Exception as exc:  # noqa: BLE001 - reported to the parent, which decides
                emit("error", id=rid, kind=_classify(exc), message=str(exc) or type(exc).__name__,
                     type=type(exc).__name__)
                continue
            emit("loaded", id=rid, **info, **_memory())
        elif op == "synth":
            emit("started", id=rid, chars=len(str(request.get("text", ""))))
            began = time.monotonic()
            try:
                pcm, details = adapter.synthesize(request)
            except Exception as exc:  # noqa: BLE001
                kind = "assets" if type(exc).__name__ == "AssetsUnavailable" else "synthesis"
                emit("error", id=rid, kind=kind, message=str(exc) or type(exc).__name__, type=type(exc).__name__)
                continue
            gen_s = time.monotonic() - began
            out = None
            if pcm.size:
                out = str(request["out"])
                try:
                    _write_pcm(pcm, out)
                except OSError as exc:
                    emit("error", id=rid, kind="synthesis", message=f"the audio could not be handed back: {exc}",
                         type=type(exc).__name__)
                    continue
            emit("result", id=rid, out=out, samples=int(pcm.size), dtype=str(pcm.dtype),
                 sample_rate=adapter.sample_rate, gen_s=round(gen_s, 4), **details, **_memory())
        else:
            emit("error", id=rid, kind="protocol", message=f"unknown request {op!r}")
    return 0


def main(argv: list[str]) -> int:
    _take_protocol_channel()
    if len(argv) != 1 or argv[0] not in ADAPTERS:
        emit("error", id=None, kind="protocol", message=f"usage: local_engine_worker.py <{'|'.join(ADAPTERS)}>")
        return 2
    return serve(argv[0])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
