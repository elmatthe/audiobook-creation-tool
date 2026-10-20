"""Helpers for the calm-narration experiment that must run inside ``.venv-qwen3`` (v0.6.7). Dev-only.

    <.venv-qwen3 python> qwen3_calm_venv_tools.py selfcheck <model_dir>
    <.venv-qwen3 python> qwen3_calm_venv_tools.py asr <whisper_dir> <out.json> <wav> [<wav> ...]

``selfcheck`` imports the pinned ``qwen_tts`` and proves, WITHOUT loading any model or making any audio, how the library merges
sampling arguments with the Base model's ``generation_config.json``: that no argument means the file's values, that an explicit
``temperature=0.9`` is byte-for-byte the same merge, and that ``temperature=0.8`` changes that one value and nothing else (in
particular not ``subtalker_temperature``). ``asr`` reads generated audio back with the local whisper-small.en for a
completeness check. Neither touches the application, a reference recording or a transcript.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path


def selfcheck(model_dir: str) -> dict:
    import importlib.metadata as md

    from qwen_tts import Qwen3TTSModel

    config = json.loads((Path(model_dir) / "generation_config.json").read_text(encoding="utf-8"))
    merge = Qwen3TTSModel._merge_generate_kwargs
    names = set(inspect.signature(merge).parameters)
    clone_source = inspect.getsource(Qwen3TTSModel.generate_voice_clone)
    instance = object.__new__(Qwen3TTSModel)  # the merge reads only generate_defaults: no weights are needed
    instance.generate_defaults = config
    default = instance._merge_generate_kwargs()
    explicit = instance._merge_generate_kwargs(temperature=0.9)
    lower = instance._merge_generate_kwargs(temperature=0.8)
    changed = sorted(k for k in set(default) | set(lower) if default.get(k) != lower.get(k))
    return {
        "qwen_tts": md.version("qwen-tts"),
        "sampling_arguments_accepted": sorted(n for n in names if n not in ("self", "kwargs")),
        "generate_voice_clone_forwards_kwargs": "self._merge_generate_kwargs(**kwargs)" in clone_source,
        "effective_default": default,
        "explicit_0.9_equals_default": explicit == default,
        "temperature_0.8_changes_only": changed,
        "subtalker_temperature_at_0.8": lower.get("subtalker_temperature"),
    }


def asr(whisper_dir: str, out_json: str, wavs: list[str]) -> None:
    import librosa
    import soundfile as sf
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    processor = WhisperProcessor.from_pretrained(whisper_dir, local_files_only=True)
    model = WhisperForConditionalGeneration.from_pretrained(whisper_dir, local_files_only=True).eval()
    results = {}
    for wav in wavs:
        audio, rate = sf.read(wav, dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        audio = librosa.resample(audio, orig_sr=rate, target_sr=16000)
        pieces = []
        # Whisper takes 30 s at a time: read long audio in 28 s windows (the experiment clips are minutes long).
        step = 28 * 16000
        for start in range(0, max(len(audio), 1), step):
            features = processor(audio[start:start + step], sampling_rate=16000, return_tensors="pt")
            with torch.no_grad():
                ids = model.generate(features.input_features, max_new_tokens=220)
            pieces.append(processor.batch_decode(ids, skip_special_tokens=True)[0].strip())
        results[wav] = " ".join(p for p in pieces if p)
    Path(out_json).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "selfcheck":
        print(json.dumps(selfcheck(argv[2]), indent=1))
        return 0
    if len(argv) >= 5 and argv[1] == "asr":
        asr(argv[2], argv[3], argv[4:])
        return 0
    sys.stderr.write(__doc__)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
