---
name: audio-processing
description: "Use this skill when the task involves manipulating audio files, extracting or writing metadata tags, building audio data pipelines, or converting between audio formats. Trigger for: trimming/merging/normalizing audio, reading/writing ID3/FLAC/Vorbis tags, batch transcoding, waveform analysis, silence detection, audio fingerprinting, or any pipeline that ingests or produces .mp3, .flac, .wav, .ogg, .aac, .m4a, or similar media files."
---

# Audio Processing

## Library Selection

| Task | Library |
|---|---|
| Format conversion, trim, merge, fade | `pydub` (wraps ffmpeg) |
| Read/write ID3, FLAC, Ogg tags | `mutagen` |
| Low-level PCM / NumPy array access | `soundfile` (libsndfile) |
| Spectral analysis, MFCCs, onset detection | `librosa` |
| Raw ffmpeg/ffprobe subprocess calls | `subprocess` + `shlex` |

`pydub` requires `ffmpeg` and `ffprobe` on PATH. Verify before use:
```python
import shutil
assert shutil.which("ffmpeg"),  "ffmpeg not found — install via system package manager"
assert shutil.which("ffprobe"), "ffprobe not found"
```

## Safe File Handling

Always work on a copy; never overwrite the original in-place unless explicitly requested.

```python
import shutil, tempfile, os
from pathlib import Path

def safe_process(src: str | Path, fn, suffix=".mp3") -> Path:
    src = Path(src)
    tmp = Path(tempfile.mktemp(suffix=suffix))
    shutil.copy2(src, tmp)
    try:
        result = fn(tmp)
        return result
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
```

## Format Conversion

```python
from pydub import AudioSegment

def convert(src: str, dst: str, bitrate="192k", sample_rate=44100) -> None:
    fmt = Path(dst).suffix.lstrip(".")
    audio = AudioSegment.from_file(src)
    audio = audio.set_frame_rate(sample_rate)
    audio.export(dst, format=fmt, bitrate=bitrate)
```

Supported export formats: `mp3`, `wav`, `ogg`, `flac`, `aac`, `m4a`.
For `aac`/`m4a` output, pass `codec="aac"` in `export()`.

## Trim and Splice

```python
from pydub import AudioSegment

def trim(src: str, start_ms: int, end_ms: int, dst: str) -> None:
    audio = AudioSegment.from_file(src)
    clip = audio[start_ms:end_ms]
    clip.export(dst, format=Path(dst).suffix.lstrip("."))

def concat(files: list[str], dst: str) -> None:
    combined = sum((AudioSegment.from_file(f) for f in files), AudioSegment.empty())
    combined.export(dst, format=Path(dst).suffix.lstrip("."))
```

## Normalization and Gain

```python
from pydub import AudioSegment
from pydub.effects import normalize

def normalize_audio(src: str, dst: str, target_dBFS=-14.0) -> None:
    audio = AudioSegment.from_file(src)
    delta = target_dBFS - audio.dBFS
    adjusted = audio.apply_gain(delta)
    adjusted.export(dst, format=Path(dst).suffix.lstrip("."))
```

`-14 dBFS` is the streaming standard (Spotify/Apple Music). Use `-23 LUFS` target for broadcast.

## Silence Detection

```python
from pydub.silence import detect_silence

def find_silence(src: str, min_silence_ms=500, silence_thresh_dBFS=-40) -> list[tuple]:
    audio = AudioSegment.from_file(src)
    return detect_silence(audio, min_silence_len=min_silence_ms,
                          silence_thresh=silence_thresh_dBFS)
```

Returns list of `[start_ms, end_ms]` pairs. Adjust `silence_thresh_dBFS` for noisy recordings.

## Metadata — Read and Write

### Read tags (any format)
```python
from mutagen import File as MutagenFile

def read_tags(path: str) -> dict:
    f = MutagenFile(path, easy=True)
    if f is None:
        raise ValueError(f"Unrecognized audio format: {path}")
    return dict(f.tags or {})
```

### Write tags (format-agnostic via EasyID3/EasyMP4/etc.)
```python
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC

def write_mp3_tags(path: str, tags: dict) -> None:
    audio = EasyID3(path)
    for key, val in tags.items():
        audio[key] = [val] if isinstance(val, str) else val
    audio.save()

def write_flac_tags(path: str, tags: dict) -> None:
    audio = FLAC(path)
    for key, val in tags.items():
        audio[key] = [val] if isinstance(val, str) else val
    audio.save()
```

Common EasyID3 keys: `title`, `artist`, `album`, `albumartist`, `date`, `genre`, `tracknumber`, `discnumber`.

### Embed cover art (MP3)
```python
from mutagen.id3 import ID3, APIC, error as ID3Error

def embed_cover(mp3_path: str, image_path: str) -> None:
    try:
        tags = ID3(mp3_path)
    except ID3Error:
        tags = ID3()
    with open(image_path, "rb") as img:
        data = img.read()
    mime = "image/jpeg" if image_path.lower().endswith((".jpg",".jpeg")) else "image/png"
    tags["APIC"] = APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data)
    tags.save(mp3_path)
```

## Batch Pipeline

```python
from pathlib import Path
from pydub import AudioSegment

def batch_convert(src_dir: str, dst_dir: str, out_fmt="mp3", bitrate="192k") -> list[Path]:
    src_dir, dst_dir = Path(src_dir), Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for src in src_dir.glob("*"):
        if src.suffix.lower() not in {".wav",".flac",".ogg",".aac",".m4a",".mp3"}:
            continue
        dst = dst_dir / src.with_suffix(f".{out_fmt}").name
        AudioSegment.from_file(src).export(dst, format=out_fmt, bitrate=bitrate)
        outputs.append(dst)
    return outputs
```

## ffprobe — Extract Audio Metadata

```python
import subprocess, json, shlex

def probe(path: str) -> dict:
    cmd = (f'ffprobe -v quiet -print_format json -show_streams -show_format '
           f'"{path}"')
    result = subprocess.run(shlex.split(cmd), capture_output=True, text=True, check=True)
    return json.loads(result.stdout)

# Usage
info = probe("track.flac")
duration_s = float(info["format"]["duration"])
sample_rate = int(info["streams"][0]["sample_rate"])
```

Never interpolate untrusted filenames directly into shell strings — use `shlex.quote(path)` or pass as a list to `subprocess.run()`.

## Waveform / Spectral Analysis (librosa)

```python
import librosa
import numpy as np

def analyze(path: str) -> dict:
    y, sr = librosa.load(path, sr=None, mono=True)
    return {
        "duration_s":    librosa.get_duration(y=y, sr=sr),
        "sample_rate":   sr,
        "rms_dBFS":      float(20 * np.log10(np.sqrt(np.mean(y**2)) + 1e-9)),
        "tempo_bpm":     float(librosa.beat.beat_track(y=y, sr=sr)[0]),
        "mfcc_mean":     librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13).mean(axis=1).tolist(),
    }
```

`librosa.load` resamples to 22 050 Hz by default — pass `sr=None` to preserve original sample rate.

## Verification Checklist

- [ ] `ffmpeg`/`ffprobe` confirmed on PATH before running pydub
- [ ] Original file copied before any destructive operation
- [ ] Output file extension matches the target format string passed to `export()`
- [ ] Tag keys validated against format-specific allowed keys (EasyID3 vs VorbisComment)
- [ ] Batch pipeline skips non-audio files (suffix whitelist)
- [ ] `subprocess` calls use list form or `shlex.quote()` — no bare f-string shell interpolation
- [ ] Large files streamed where possible (`read_only` / generator patterns)

## Common Pitfalls

| Pitfall | Fix |
|---|---|
| `CouldntDecodeError` on import | File extension wrong or codec missing — run `ffprobe` first to confirm format |
| Tags silently dropped after `export()` | pydub export does not copy tags — re-apply with mutagen after export |
| Clipping after gain boost | Check `audio.max_dBFS` before applying gain; cap at 0 dBFS |
| Wrong sample rate after concat | Normalize all segments to same `frame_rate` before `sum()` |
| `UnicodeDecodeError` in mutagen | Open with `encoding="utf-8"` or catch and fall back to `latin-1` |
| Shell injection via filename | Always use `shlex.quote()` or subprocess list form |
| `librosa.load` resamples silently | Pass `sr=None` to preserve native sample rate |
