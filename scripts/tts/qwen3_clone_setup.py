"""qwen3_clone_setup.py — setting the six cloned Qwen3 voices up: their reference transcripts, made and confirmed in the app.

A Qwen3 clone is conditioned on its reference recording AND the exact words spoken in it, and the application will only use
a transcript that the person at this computer has approved for exactly that recording (``qwen3_runtime.load_transcript``:
``approved`` must be the literal ``true`` and ``wav_sha256`` the registered recording's hash). The transcripts are short
excerpts of the narrators' books, so they are never shipped (owner ruling Q5): each installation makes its own, here:

1. **Install the speech recognizer** -- the pinned Whisper small.en (``qwen3_models.json``, "transcriber"), downloaded only
   when the user asks, with its size shown first, verified file by file like the voice models.
2. **Create drafts** -- the recognizer transcribes the six bundled recordings ON THIS COMPUTER inside ``.venv-qwen3``
   (nothing is sent anywhere). Each draft is saved with ``approved: false``; an approval already given is never replaced.
3. **Confirm** -- the user plays each recording, corrects the text if needed, ticks "I listened" and approves. Only that
   writes ``approved: true``, bound to the recording's SHA-256, with who approved it and when.

Everything is stored in the same local, untracked file the app reads (``files/runtime-data/qwen3/transcripts.json``, or the
``ACT_QWEN3_TRANSCRIPTS`` override), which ``files/runtime-data/`` keeps out of git and out of every release archive.
No Tk here: ``qwen3_clone_setup_ui`` is the window.
"""
from __future__ import annotations

import datetime
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from tts import qwen3_runtime as rt
from tts import qwen3_setup as su

DRAFT_SOURCE = "Whisper small.en draft, made on this computer"
APPROVED_BY = "the user, in the app (listened to the recording)"
STATE_APPROVED, STATE_DRAFT, STATE_MISSING, STATE_STALE = "approved", "draft", "missing", "stale"


@dataclass(frozen=True)
class Row:
    voice_id: str
    label: str
    reference: Path
    state: str  # approved | draft | missing | stale (recorded for a different recording)
    text: str


def clone_voices() -> list:
    """The six clones, each through the runtime's own lookup (the one every availability check uses)."""
    return [rt.get_voice(v.voice_id) for v in rt.QWEN3_VOICES if v.kind == rt.KIND_CLONE]


def store_path() -> Path:
    """Where transcripts are written: the same file the loader reads (the override, if one is set, else the local file)."""
    return rt.transcript_search_paths()[0]


def read_store(path: Optional[Path] = None) -> dict:
    path = Path(path or store_path())
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise su.SetupError(f"The transcripts file could not be read ({exc}); it was not changed.") from exc
    if not isinstance(data, dict):
        raise su.SetupError("The transcripts file is not in the expected shape; it was not changed.")
    return data


#: Shown when the transcripts file cannot be written. The store is replaced atomically, so the file on disk is still the
#: previous one; the dialog keeps the user's text and ticks for a retry.
SAVE_FAILED = ("The approval could not be saved: the transcripts file {name} could not be written ({reason}). Nothing was "
               "changed, and your text and ticks are kept. Check that the app's folder is not read-only, open in another "
               "program or out of disk space, then click Approve again.")


def write_store(data: dict, path: Optional[Path] = None) -> None:
    """Replace the store atomically. Any filesystem failure becomes a :class:`qwen3_setup.SetupError` (audit ACT67-AUD-007):
    it used to escape as a raw OSError into the Tk callback, and the user saw nothing at all."""
    path = Path(path or store_path())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rt.atomic_write_json(path, data)
    except (OSError, rt.Qwen3Unavailable) as exc:
        reason = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
        raise su.SetupError(SAVE_FAILED.format(name=path.name, reason=reason)) from exc


def rows(path: Optional[Path] = None) -> list[Row]:
    """The six clones and where each one's transcript stands. Never raises for a bad file: it reads as missing."""
    try:
        data = read_store(path)
    except su.SetupError:
        data = {}
    out = []
    for voice in clone_voices():
        entry = data.get(voice.reference_name)
        text = entry.get("text") if isinstance(entry, dict) and isinstance(entry.get("text"), str) else ""
        if not isinstance(entry, dict) or not text.strip():
            state = STATE_MISSING
        elif entry.get("wav_sha256") != voice.reference_sha256:
            state = STATE_STALE
        elif entry.get("approved") is True:
            state = STATE_APPROVED
        else:
            state = STATE_DRAFT
        out.append(Row(voice.voice_id, voice.label, rt.reference_path(voice), state, text))
    return out


def normalize(text: str) -> str:
    return " ".join(str(text).split())


# --------------------------------------------------------------------------- #
# Step 1: the speech recognizer
# --------------------------------------------------------------------------- #
def recognizer_size() -> int:
    return rt.model_spec(rt.TRANSCRIBER).total_bytes


def install_recognizer(*, progress=su._noop_progress, cancel_check=None, opener=None, seed_dirs=(),
                       disk_free: Callable[[Path], int] = su.free_bytes) -> su.SetupResult:
    """Download and verify the pinned speech recognizer (only when the user has asked and confirmed)."""
    try:
        su.refuse_if_unsupported()
        if rt.transcriber_status()[0]:
            return su.SetupResult(True, "The speech recognizer is already installed.")
        needed = recognizer_size() + su.DISK_MARGIN_BYTES
        if disk_free(rt.repo_root()) < needed:
            return su.SetupResult(False, f"Not enough free disk space: the speech recognizer needs about "
                                         f"{rt.format_bytes(needed)}. Nothing was downloaded.")
        with su.InstallLock():
            su.install_model(rt.TRANSCRIBER, progress=progress, cancel_check=cancel_check, opener=opener,
                             seed_dirs=seed_dirs)
        return su.SetupResult(True, "The speech recognizer is installed. Now press \"Create drafts\".")
    except su.SetupCancelled:
        return su.SetupResult(False, "Cancelled. What was downloaded is kept; press the button again to continue.",
                              cancelled=True)
    except (su.SetupError, rt.Qwen3Unavailable) as exc:
        return su.SetupResult(False, str(exc))
    except OSError as exc:
        return su.SetupResult(False, f"The download stopped because of a file or disk problem: {exc}")


# --------------------------------------------------------------------------- #
# Step 2: drafts
# --------------------------------------------------------------------------- #
def drafting_problem() -> Optional[str]:
    """Why drafts cannot be made right now, or ``None``."""
    if not rt.platform_supported():
        return rt.platform_reason()
    ok, reason = rt.environment_status()
    if not ok:
        return f"The Qwen3 voice engine is needed first: {reason}"
    ok, reason = rt.transcriber_status()
    if not ok:
        return reason
    return None


def create_drafts(*, progress=su._noop_progress, cancel_check=None, run_worker=None,
                  jobs_root: Optional[Path] = None, path: Optional[Path] = None) -> su.SetupResult:
    """Transcribe the six recordings locally and save each result as an UNAPPROVED draft.

    An entry that is already approved for the current recording is left exactly as it is. A recording whose bytes are not
    the registered ones is skipped (and said so), never transcribed under the old approval.
    """
    from shared.cancellation import ConversionCancelled
    from tts import qwen3_synth

    problem = drafting_problem()
    if problem:
        return su.SetupResult(False, problem)
    run_worker = run_worker or qwen3_synth.run_worker
    current = {r.voice_id: r for r in rows(path)}
    todo = [v for v in clone_voices() if current[v.voice_id].state != STATE_APPROVED]
    if not todo:
        return su.SetupResult(True, "All six cloned voices already have an approved transcript.")
    skipped = [v.label for v in todo if not rt.reference_status(v)[0]]
    todo = [v for v in todo if v.label not in skipped]
    if not todo:
        return su.SetupResult(False, "None of the reference recordings is the one the app expects: " + ", ".join(skipped))
    job_dir = qwen3_synth.new_job_dir(jobs_root)
    try:
        items = []
        for voice in todo:  # the worker reads a verified copy, never the repository path (the snapshot rule)
            copy = job_dir / f"{voice.reference_name}.wav"
            shutil.copyfile(rt.reference_path(voice), copy)
            if rt.sha256_file(copy) != voice.reference_sha256:
                raise su.SetupError(f"{voice.label}: the reference recording changed while it was being read.")
            items.append({"name": voice.reference_name, "wav": str(copy)})
        out_file = job_dir / "transcripts.json"
        job = {"schema": 1, "kind": "transcribe", "model_dir": str(rt.model_spec(rt.TRANSCRIBER).directory),
               "device": "auto", "items": items, "out_file": str(out_file), "cancel_file": str(job_dir / "cancel")}
        progress(su.Progress("drafts", "Loading the speech recognizer and transcribing the six recordings...", 0, 0))
        with rt.inference_lease():
            run = run_worker(job, job_dir, python=rt.venv_python(), script=rt.worker_script(),
                             env=rt.worker_environment(), cancel_check=cancel_check, log=lambda line: None)
        if run.terminal.get("event") != "done":
            message = run.terminal.get("message") or "the speech recognizer did not finish"
            return su.SetupResult(False, f"The drafts could not be made: {message}")
        heard = json.loads(out_file.read_text(encoding="utf-8"))
        data = read_store(path)
        today = datetime.date.today().isoformat()
        made = []
        for voice in todo:
            text = normalize(heard.get(voice.reference_name, ""))
            if not text:
                continue
            existing = data.get(voice.reference_name)
            if isinstance(existing, dict) and existing.get("approved") is True \
                    and existing.get("wav_sha256") == voice.reference_sha256:
                continue  # approved meanwhile: never replaced by a draft
            data[voice.reference_name] = {"text": text, "approved": False, "wav_sha256": voice.reference_sha256,
                                          "source": DRAFT_SOURCE, "drafted_on": today}
            made.append(voice.label)
        write_store(data, path)
        message = f"Drafts made for {len(made)} voice(s). Listen to each recording, correct the text if needed, tick " \
                  "\"I listened\" and approve."
        if skipped:
            message += " Skipped (the recording is not the expected one): " + ", ".join(skipped) + "."
        return su.SetupResult(True, message)
    except ConversionCancelled:
        return su.SetupResult(False, "Cancelled. No draft was saved.", cancelled=True)
    except (su.SetupError, rt.Qwen3Unavailable, qwen3_synth.Qwen3Failed) as exc:
        return su.SetupResult(False, f"The drafts could not be made: {exc}")
    except OSError as exc:
        return su.SetupResult(False, f"The drafts could not be made because of a file problem: {exc}")
    finally:
        qwen3_synth.remove_job_dir(job_dir)


# --------------------------------------------------------------------------- #
# Step 3: the user's confirmation
# --------------------------------------------------------------------------- #
def approve(decisions: dict, *, path: Optional[Path] = None, today: Optional[str] = None) -> list[str]:
    """Record the user's approval: ``decisions`` maps a clone's voice id to ``(text, listened)``.

    Each approval must say the user listened, carry 1-2000 characters of text, and be for the recording that is on disk now
    (its SHA-256 is checked again). Anything else raises :class:`qwen3_setup.SetupError` and nothing is written. Returns the
    labels approved.
    """
    by_id = {v.voice_id: v for v in clone_voices()}
    data = read_store(path)
    stamp = today or datetime.date.today().isoformat()
    approved = []
    for voice_id, (text, listened) in decisions.items():
        voice = by_id.get(voice_id)
        if voice is None:
            raise su.SetupError(f"{voice_id!r} is not one of the six cloned voices.")
        if listened is not True:
            raise su.SetupError(f"{voice.label}: tick \"I listened\" after listening to the whole recording first.")
        clean = normalize(text)
        if not clean or len(clean) > rt.MAX_TRANSCRIPT_CHARS:
            raise su.SetupError(f"{voice.label}: the transcript must be 1-{rt.MAX_TRANSCRIPT_CHARS} characters.")
        ok, reason = rt.reference_status(voice)
        if not ok:
            raise su.SetupError(reason)
        data[voice.reference_name] = {"text": clean, "approved": True, "wav_sha256": voice.reference_sha256,
                                      "text_sha256": rt.transcript_sha256(clean), "approved_by": APPROVED_BY,
                                      "approved_on": stamp}
        approved.append(voice.label)
    if approved:
        write_store(data, path)
    return approved
