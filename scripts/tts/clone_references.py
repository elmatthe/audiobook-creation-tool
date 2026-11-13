"""clone_references.py — the declarative authority for the 18 bundled clone reference recordings (v0.8.0).

Owner decision 2026-11-13 (``md-instructions/Decisions.md``): every cloned engine has its own six recordings, in its own
folder, named for it -- ``<reference folder>/<Engine>/<Engine> - <Voice>.wav`` (``voice_registry`` names the folder and
every file):

* **Qwen3** keeps the six original v0.7.x recordings byte for byte (renamed and moved only). Its reference texts stay in
  ``data/bundled_clone_transcripts.json`` exactly as they were, so this file holds no Qwen3 text.
* **Chatterbox** uses six new owner-supplied recordings. Chatterbox Turbo conditions on audio alone, so their
  owner-written transcripts are checked metadata here and are never given to the model.
* **OmniVoice** uses six new owner-curated recordings whole (no further cropping), with their owner-written transcripts as
  the clone prompt's reference text.

``data/clone_references.json`` lists all 18: the file, its SHA-256, its PCM format and exact frame count, and (Chatterbox
and OmniVoice) the approved text with its SHA-256. :func:`load` checks the WHOLE list against the registry's reference
tables and refuses all of it on any problem: a damaged list is never trusted in part. It reads no recording; each engine
also pins its own recordings' hashes in its own module, and the tests prove the three agree.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tts import voice_registry as vr

#: Engines whose reference texts live elsewhere (and are therefore ``null`` here).
TEXT_ELSEWHERE = frozenset({"qwen3"})
TOP_KEYS = frozenset({"schema_version", "note", "entries"})
ENTRY_KEYS = frozenset({"backend", "voice_id", "reference_id", "file", "wav_sha256", "sample_rate", "channels",
                        "sample_width_bytes", "frames", "text", "text_sha256"})
MAX_BYTES = 64 * 1024
_HEX64 = re.compile(r"[0-9a-f]{64}")


class ReferenceManifestError(ValueError):
    """The reference list is not exactly what was approved. The message says what."""


@dataclass(frozen=True)
class ReferenceAsset:
    backend: str
    voice_id: str
    reference_id: str
    file: str  # relative to voice_registry.REFERENCE_DIRECTORY, POSIX
    wav_sha256: str
    sample_rate: int
    channels: int
    sample_width_bytes: int
    frames: int
    text: Optional[str]
    text_sha256: Optional[str]

    @property
    def duration_s(self) -> float:
        return self.frames / self.sample_rate

    @property
    def parts(self) -> tuple[str, ...]:
        """Repository-relative path parts of the recording."""
        return (*vr.REFERENCE_DIRECTORY, *self.file.split("/"))


def manifest_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "clone_references.json"


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def transcript_problem(text: object) -> Optional[str]:
    """Why *text* is not a usable reference transcript, or ``None``. Nothing is ever rewritten to make it usable."""
    if not isinstance(text, str) or not text.strip():
        return "it is blank"
    if text != text.strip():
        return "it has leading or trailing spaces"
    if any(unicodedata.category(ch) == "Cc" for ch in text):
        return "it has control characters"
    return None


def _asset(raw: object) -> ReferenceAsset:
    if not isinstance(raw, dict) or set(raw) != ENTRY_KEYS:
        raise ReferenceManifestError("an entry has unexpected fields")
    ints = ("sample_rate", "channels", "sample_width_bytes", "frames")
    strs = ("backend", "voice_id", "reference_id", "file", "wav_sha256")
    if any(type(raw[k]) is not int for k in ints) or any(not isinstance(raw[k], str) for k in strs) or any(
            raw[k] is not None and not isinstance(raw[k], str) for k in ("text", "text_sha256")):
        raise ReferenceManifestError("an entry field has the wrong type")
    asset = ReferenceAsset(**raw)
    key = (asset.backend, asset.voice_id)
    where = f"{asset.backend}/{asset.voice_id}"
    if key not in vr.VOICE_REFERENCES:
        raise ReferenceManifestError(f"{where}: not a registered cloned voice")
    if asset.reference_id != vr.VOICE_REFERENCES[key]:
        raise ReferenceManifestError(f"{where}: the registry clones it from {vr.VOICE_REFERENCES[key]}")
    if asset.parts != vr.reference_recording_parts(*key):
        raise ReferenceManifestError(f"{where}: the file is not the registry's {vr.reference_recording_filename(*key)}")
    if not _HEX64.fullmatch(asset.wav_sha256):
        raise ReferenceManifestError(f"{where}: wav_sha256 is not a SHA-256")
    if asset.sample_rate <= 0 or asset.frames <= 0 or (asset.channels, asset.sample_width_bytes) != (1, 2):
        raise ReferenceManifestError(f"{where}: not the 16-bit mono PCM recording it was approved as")
    if asset.backend in TEXT_ELSEWHERE:
        if asset.text is not None or asset.text_sha256 is not None:
            raise ReferenceManifestError(f"{where}: its reference text belongs to its own transcript bundle")
        return asset
    problem = transcript_problem(asset.text)
    if problem:
        raise ReferenceManifestError(f"{where}: the transcript is unusable: {problem}")
    if asset.text_sha256 is None or asset.text_sha256 != text_sha256(asset.text):
        raise ReferenceManifestError(f"{where}: the transcript fails its checksum")
    return asset


def load(path: Optional[Path] = None) -> dict[tuple[str, str], ReferenceAsset]:
    """``(backend, voice_id) -> ReferenceAsset`` for all 18 cloned voices, after checking the whole list."""
    source = Path(path) if path is not None else manifest_path()
    try:
        if source.stat().st_size > MAX_BYTES:
            raise ReferenceManifestError("the reference list is too large")
        data = json.loads(source.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, ReferenceManifestError):
            raise
        raise ReferenceManifestError(f"the reference list shipped with the app could not be read ({exc})") from exc
    if not isinstance(data, dict) or set(data) != TOP_KEYS or data.get("schema_version") != 1:
        raise ReferenceManifestError("the reference list is not schema version 1")
    entries = data["entries"]
    if not isinstance(entries, list) or len(entries) != len(vr.VOICE_REFERENCES):
        raise ReferenceManifestError(f"the reference list must hold exactly {len(vr.VOICE_REFERENCES)} entries")
    assets: dict[tuple[str, str], ReferenceAsset] = {}
    for raw in entries:
        asset = _asset(raw)
        key = (asset.backend, asset.voice_id)
        if key in assets:
            raise ReferenceManifestError(f"two entries for {asset.backend}/{asset.voice_id}")
        assets[key] = asset
    if len({a.wav_sha256 for a in assets.values()}) != len(assets):
        raise ReferenceManifestError("two entries name the same recording bytes; every engine has its own recording")
    return assets
