"""Development-only Qwen3 clone worker for the calm-narration experiment (v0.6.7). Runs ONLY inside ``.venv-qwen3``.

The production worker (``scripts/tts/qwen3_worker.py``) passes no sampling argument, so a clone is generated with the Base model's
own ``generation_config.json`` (temperature 0.9, top_p 1.0, top_k 50, repetition_penalty 1.05, and the same for the sub-talker).
This wrapper changes exactly one thing for one run: it forwards an explicit ``temperature`` to ``generate_voice_clone``. It does
that by loading and running the UNCHANGED production worker, so the job format, the offline model load, the per-chunk seeds,
the reference/transcript conditioning, the events and the chunk files are all production's own.

    <.venv-qwen3 python> qwen3_calm_worker.py <job.json>        with ACT_QWEN3_EXPERIMENT='{"temperature": 0.8}'

With no override in the environment this is exactly ``qwen3_worker.main`` (nothing is imported or patched). The override is
refused for anything but a clone ``synth`` job (a preset voice such as Aiden or Ryan is never altered), accepts only
``temperature``, and only inside ``TEMPERATURE_RANGE``. ``subtalker_temperature`` and every other control are deliberately not
overridable here: the first experiment varies one thing.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

ENV_VAR = "ACT_QWEN3_EXPERIMENT"
TEMPERATURE_RANGE = (0.1, 1.5)
ALLOWED = ("temperature",)
PRODUCTION_WORKER = Path(__file__).resolve().parents[2] / "scripts" / "tts" / "qwen3_worker.py"


class ExperimentError(ValueError):
    pass


def parse_override(raw) -> dict:
    """The experiment override from its JSON text, or ``{}``. Anything outside the allowed set is an error."""
    if raw is None or not str(raw).strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ExperimentError(f"{ENV_VAR} is not valid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise ExperimentError(f"{ENV_VAR} must be a JSON object")
    extra = sorted(set(data) - set(ALLOWED))
    if extra:
        raise ExperimentError(f"only {list(ALLOWED)} may be overridden in this experiment, not {extra}")
    low, high = TEMPERATURE_RANGE
    out = {}
    for name, value in data.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise ExperimentError(f"{name} must be a number from {low} to {high}, not {value!r}")
        out[name] = float(value)
    return out


def install_override(model_class, override: dict) -> None:
    """Make ``model_class.generate_voice_clone`` forward ``override``; refuse a call that already sets the same argument."""
    if not override:
        return
    original = model_class.generate_voice_clone

    def generate_voice_clone(self, *args, **kwargs):
        clash = sorted(set(override) & set(kwargs))
        if clash:
            raise ExperimentError(f"the production call already sets {clash}; refusing to override it silently")
        return original(self, *args, **kwargs, **override)

    model_class.generate_voice_clone = generate_voice_clone


def load_production_worker():
    spec = importlib.util.spec_from_file_location("act_qwen3_production_worker", PRODUCTION_WORKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _model_class():
    from qwen_tts import Qwen3TTSModel

    return Qwen3TTSModel


def main(argv: list[str], environ=None, *, worker=None, model_class=None) -> int:
    environ = os.environ if environ is None else environ
    worker = worker or load_production_worker()
    try:
        override = parse_override(environ.get(ENV_VAR))
    except ExperimentError as exc:
        worker.emit({"event": "failed", "stage": "job", "message": str(exc)})
        return worker.EXIT_FAILED
    if not override:
        return worker.main(argv)  # exactly production: no patch, no import of the model library
    try:
        job = json.loads(Path(argv[1]).read_text(encoding="utf-8")) if len(argv) == 2 else {}
    except (OSError, ValueError):
        job = {}
    if job.get("kind") != "synth" or job.get("mode") != "clone":
        worker.emit({"event": "failed", "stage": "job",
                     "message": "an experiment override applies to clone synthesis only; a preset voice is never altered"})
        return worker.EXIT_FAILED
    try:
        install_override(model_class or _model_class(), override)
    except Exception as exc:  # noqa: BLE001 - the parent must always get a terminal event
        worker.emit({"event": "failed", "stage": "import", "message": f"{type(exc).__name__}: {exc}"})
        return worker.EXIT_FAILED
    return worker.main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
