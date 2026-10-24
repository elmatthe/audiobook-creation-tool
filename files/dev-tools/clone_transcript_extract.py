"""ACT v0.7.0 -- deterministic, no-echo extraction of the six owner-approved Qwen3 clone transcripts (developer only).

Plan Revision 2 §5.3 ("Extraction checkpoint -- no-echo procedure"). Prepared and tested at P03A against synthetic
fixtures only; the owner-gated P03B runs it unchanged. Never shipped, never imported by the app, never a user
requirement.

    python -I files/dev-tools/clone_transcript_extract.py --repo-root <root> --manifest <repo-relative manifest>

What it does, in order:
  1. Finds the private store ONLY through the named preservation manifest (``preservation-<tag>.json``): the one
     ``files/runtime-data`` entry's preserved copy, then ``qwen3/transcripts.json`` inside it. The manifest's tag, state
     and repository must agree with its file name and this checkout. Links/junctions and paths outside the repository
     are refused.
  2. Fingerprints the store (size, mtime, SHA-256), reads it once read-only, and parses it, rejecting duplicate keys.
  3. Requires exactly the six registered reference IDs; each entry must have ``approved`` literally ``true``, the
     registered WAV hash, non-blank text within the production limit, and a matching ``text_sha256`` where present.
     Male-4 must start with "Hello Arthur.". The six recordings on disk must match their fixed hashes.
  4. Writes ONLY the six exact texts (no strip, no normalisation) plus hash-bound metadata to a NEW gitignored private
     review file (exclusive create; no overwrite, link or escape), restricts it to the current user, reads it back,
     and re-fingerprints the store, which must be unchanged.

Everything printed, or saved outside the private file, is metadata: IDs, booleans, lengths, SHA-256 digests and
repo-relative paths. Refusal messages are fixed strings written here, never store content; any other exception is
reported by its type name only. Transcript text never travels through arguments, stdout, stderr or logs, and nobody
-- an AI agent included -- should open the store or the review file to "check" the result.

``--mode review-pending``: every check still fails closed EXCEPT the Male-4 prefix, which is recorded as
OWNER_CORRECTION_REQUIRED. That artifact is a distinct, explicitly UNAPPROVED / NOT FOR SYNTHESIS file holding the
six original texts verbatim (nothing prepended), and the run exits 4 (REVIEW_PENDING), never 0.

Exit codes: 0 PASS, 2 refused, 3 unexpected error (details withheld), 4 REVIEW_PENDING.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

KIND = "act070-private-clone-transcript-review"
SCHEMA = 1
MAX_TRANSCRIPT_CHARS = 2000  # scripts/tts/qwen3_runtime.py MAX_TRANSCRIPT_CHARS
MAX_STORE_BYTES = 1 << 20  # six short transcripts; anything larger is not the store this reads
MALE4_PREFIX = "Hello Arthur."  # plan Revision 2 §5.3 step 3
MANIFEST_NAME = re.compile(r"preservation-(?P<tag>\d{8}-\d{6}-[0-9a-f]{8})\.json")
RUNTIME_DATA_ORIGINAL = "files/runtime-data"
STORE_SUBPATH = ("qwen3", "transcripts.json")  # scripts/tts/qwen3_runtime.py local_transcripts_path()
REFS_REL = "files/Cloned-Voice-Uploads"  # scripts/tts/voice_registry.py REFERENCE_DIRECTORY
REVIEW_BASE_REL = "files/dev-work/act070-remediation/private-transcript-review"
METADATA_BASE_REL = "files/dev-work/act070-remediation/transcript-extraction/metadata"
ARTIFACT_NAME = "six-clone-transcripts-PRIVATE-REVIEW.json"
MODE_FINAL, MODE_REVIEW_PENDING = "final", "review-pending"
PENDING_KIND = "act070-private-clone-transcript-review-PENDING"
PENDING_ARTIFACT_NAME = "six-clone-transcripts-REVIEW-PENDING-UNAPPROVED.json"
CORRECTION_REQUIRED, REVIEW_REQUIRED = "OWNER_CORRECTION_REQUIRED", "OWNER_REVIEW_REQUIRED"
EXIT_PASS, EXIT_REFUSED, EXIT_UNEXPECTED, EXIT_REVIEW_PENDING = 0, 2, 3, 4
# Fields the v0.6.7 importer (files/dev-tools/qwen3_transcript_review.py) writes. Only text and digests are copied;
# approval history (approved_by/approved_on) and anything unknown stay behind in the private store.
KNOWN_FIELDS = frozenset({"text", "approved", "wav_sha256", "text_sha256", "approved_by", "approved_on"})

#: (reference_id, voice_id, recording basename, expected WAV SHA-256) -- plan Revision 2 Appendix A. Pinned here on
#: purpose (this tool imports nothing from the app); files/tests/test_clone_transcript_extract.py proves it equals
#: voice_registry, qwen3_runtime and chatterbox_synth.
REGISTRY: tuple[tuple[str, str, str, str], ...] = (
    ("Female-1", "qwen3-female-1", "Chatterbox - Female 1.wav",
     "b740b9ed352e6a32d93f4e523b27c55a717d1818b137a3af7bc3585a838655e4"),
    ("Female-2", "qwen3-female-2", "Chatterbox - Female 2.wav",
     "428d3869b6bc7a26125063dfdaa8da05f8dab015427197f62e84a59f44bdb205"),
    ("Male-1", "qwen3-male-1", "Chatterbox - Male 1.wav",
     "45fbfba0815b76b88d00b47a3f0ac3e747c1269a17c5a2f7a75c1bbb8f9c0d58"),
    ("Male-2", "qwen3-male-2", "Chatterbox - Male 2.wav",
     "592139a28e82aaf5c8a2b584eddd41540acbf35db91bf053ed76a8a959f0b355"),
    ("Male-3", "qwen3-male-3", "Chatterbox - Male 3.wav",
     "4ab6bd671add539afb4e551683047a04cb4ce3a95b0e7584bd5c2801dd44ee80"),
    ("Male-4", "qwen3-male-4", "Chatterbox - Male 4.wav",
     "47eff938180617c015959cc56c3744fad8812f021c81930bec055ad324312cad"),
)


class ExtractError(Exception):
    """A refusal. Its message is always a fixed string written here -- never store content."""


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_link(path: Path) -> bool:
    """A symlink, junction or other reparse point. A missing path is not a link."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    if hasattr(os.path, "isjunction") and os.path.isjunction(path):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _inside(root: Path, target: Path) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(root), os.path.normcase(target)]) == os.path.normcase(root)
    except ValueError:  # different drives
        return False


def _check_chain(root: Path, target: Path, what: str) -> None:
    """``target`` must lie inside ``root`` both lexically and after resolution, with no link in between."""
    if not _inside(root, target):
        raise ExtractError(f"{what}: path is outside the repository")
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if _is_link(current):
            raise ExtractError(f"{what}: a link or junction is in the path")
    if target.exists() and not _inside(root, Path(os.path.realpath(target))):
        raise ExtractError(f"{what}: path resolves outside the repository")


def _resolve_in_root(root: Path, raw: object, what: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ExtractError(f"{what}: missing or not a string in the manifest")
    candidate = Path(raw)
    candidate = candidate if candidate.is_absolute() else root / candidate
    return Path(os.path.normpath(candidate))


def _reject_duplicates(pairs: list) -> dict:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ExtractError("transcript store: duplicate key")
    return dict(pairs)


def _fingerprint(path: Path) -> dict:
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode):
        raise ExtractError("transcript store: not a regular file")
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha256_file(path)}


def _git_ignored(root: Path, target: Path) -> bool:
    rel = target.relative_to(root).as_posix()
    try:
        done = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", "--", rel],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


# --------------------------------------------------------------------------- #
# The extraction
# --------------------------------------------------------------------------- #
def locate_store(root: Path, manifest_rel: str, report: dict) -> tuple[Path, Path]:
    """The private store and its preserved runtime-data directory, found through the manifest -- never guessed."""
    manifest = Path(os.path.normpath(root / manifest_rel))
    _check_chain(root, manifest, "manifest")
    named = MANIFEST_NAME.fullmatch(manifest.name)
    if named is None:
        raise ExtractError("manifest: file name is not preservation-<tag>.json")
    tag = named.group("tag")
    if not manifest.is_file():
        raise ExtractError("manifest: not found")
    manifest_bytes = manifest.read_bytes()
    report["manifest"] = {"path": _rel(root, manifest), "sha256": sha256_bytes(manifest_bytes)}
    try:
        data = json.loads(manifest_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise ExtractError("manifest: not valid JSON") from None
    if not isinstance(data, dict):
        raise ExtractError("manifest: unexpected shape")
    if data.get("Tag") != tag or data.get("State") != "Preserved":
        raise ExtractError("manifest: tag or state does not match the recorded preservation")
    repo = data.get("Repository")
    if not isinstance(repo, str) or os.path.normcase(os.path.realpath(repo)) != os.path.normcase(str(root)):
        raise ExtractError("manifest: repository does not match this checkout")
    report["manifest"].update({"tag": tag, "state": "Preserved"})
    directories = data.get("Directories")
    if not isinstance(directories, list):
        raise ExtractError("manifest: Directories missing")
    wanted = Path(os.path.normpath(root / RUNTIME_DATA_ORIGINAL))
    matches = [d for d in directories if isinstance(d, dict)
               and os.path.normcase(str(_resolve_in_root(root, d.get("Original"), "manifest Original")))
               == os.path.normcase(str(wanted))]
    if len(matches) != 1:
        raise ExtractError("manifest: expected exactly one files/runtime-data preservation entry")
    preserved = _resolve_in_root(root, matches[0].get("Preserved"), "manifest Preserved")
    if tag not in preserved.name:
        raise ExtractError("manifest: preserved directory name does not carry the tag")
    _check_chain(root, preserved, "preserved runtime-data")
    if not preserved.is_dir():
        raise ExtractError("preserved runtime-data: not a directory")
    store = preserved.joinpath(*STORE_SUBPATH)
    _check_chain(root, store, "transcript store")
    if not store.is_file():
        raise ExtractError("transcript store: not found in the preserved runtime-data")
    report["source_store"] = {"path": _rel(root, store)}
    return store, preserved


def validate_recordings(root: Path, registry, report: dict) -> bool:
    ok_all = True
    refs = Path(os.path.normpath(root / REFS_REL))
    _check_chain(root, refs, "reference directory")
    rows = []
    for ref_id, voice_id, basename, expected in registry:
        wav = refs / basename
        _check_chain(root, wav, f"{ref_id} recording")
        present = wav.is_file()
        actual = sha256_file(wav) if present else None
        matches = actual == expected
        ok_all &= matches
        rows.append({"reference_id": ref_id, "voice_id": voice_id, "path": _rel(root, wav),
                     "expected_sha256": expected, "actual_sha256": actual, "matches": matches})
    report["recordings"] = rows
    return ok_all


def validate_store(data: object, registry, report: dict,
                   mode: str = MODE_FINAL) -> list[tuple[str, str, str, str]]:
    """``[(reference_id, voice_id, wav_sha256, text)]`` in registry order, or ExtractError. Reports booleans only.

    In review-pending mode a failed Male-4 prefix check alone does not refuse; it is flagged for owner correction.
    """
    if not isinstance(data, dict):
        raise ExtractError("transcript store: top level is not an object")
    expected_ids = [row[0] for row in registry]
    missing = [ref for ref in expected_ids if ref not in data]
    unexpected = sum(1 for key in data if key not in expected_ids)
    report["store_shape"] = {"entry_count": len(data), "missing_reference_ids": missing,
                             "unexpected_key_count": unexpected}
    if missing or unexpected or len(data) != len(expected_ids):
        raise ExtractError("transcript store: does not contain exactly the six expected reference IDs")

    entries, failures = [], []
    rows = []
    for ref_id, voice_id, _basename, expected_wav in registry:
        entry = data[ref_id]
        row = {"reference_id": ref_id, "voice_id": voice_id}
        rows.append(row)
        if not isinstance(entry, dict):
            row["entry_is_object"] = False
            failures.append(ref_id)
            continue
        row["entry_is_object"] = True
        text = entry.get("text")
        row["approved_is_literal_true"] = entry.get("approved") is True
        row["wav_sha256_expected"] = expected_wav
        row["entry_wav_sha256_matches"] = entry.get("wav_sha256") == expected_wav
        row["text_is_string"] = isinstance(text, str)
        if isinstance(text, str):
            row["text_length"] = len(text)
            row["text_nonblank"] = bool(text.strip())
            row["text_within_limit"] = len(text) <= MAX_TRANSCRIPT_CHARS
            row["text_has_outer_whitespace"] = text != text.strip()
            row["text_sha256"] = sha256_bytes(text.encode("utf-8"))
            if "text_sha256" not in entry:
                row["stored_text_digest"] = "absent"
            else:
                row["stored_text_digest"] = "matches" if entry["text_sha256"] == row["text_sha256"] else "MISMATCH"
        row["fields_not_copied"] = sum(1 for key in entry if key not in ("text", "wav_sha256", "text_sha256",
                                                                          "approved"))
        row["unknown_field_count"] = sum(1 for key in entry if key not in KNOWN_FIELDS)
        good = (row["approved_is_literal_true"] and row["entry_wav_sha256_matches"] and row["text_is_string"]
                and row.get("text_nonblank") and row.get("text_within_limit")
                and row.get("stored_text_digest") in ("absent", "matches"))
        if mode == MODE_REVIEW_PENDING:
            row["review_status"] = REVIEW_REQUIRED
        if ref_id == "Male-4":
            row["male4_starts_with_hello_arthur"] = isinstance(text, str) and text.startswith(MALE4_PREFIX)
            report["male4_prefix_ok"] = row["male4_starts_with_hello_arthur"]
            if mode == MODE_REVIEW_PENDING:
                if not row["male4_starts_with_hello_arthur"]:
                    row["review_status"] = CORRECTION_REQUIRED
            else:
                good = good and row["male4_starts_with_hello_arthur"]
        if good:
            entries.append((ref_id, voice_id, expected_wav, text))
        else:
            failures.append(ref_id)
    report["entries"] = rows
    if mode == MODE_REVIEW_PENDING:
        report["owner_correction_required"] = [r["reference_id"] for r in rows
                                               if r.get("review_status") == CORRECTION_REQUIRED]
    if failures:
        raise ExtractError("transcript store: entries failed validation: " + ", ".join(failures))
    return entries


def _safe_new_dir(root: Path, base_rel: str, stamp: str, what: str, forbidden: list[Path]) -> Path:
    base = Path(os.path.normpath(root / base_rel))
    _check_chain(root, base, what)
    for bad in forbidden:
        if _inside(bad, base):
            raise ExtractError(f"{what}: destination is inside a protected directory")
    base.mkdir(parents=True, exist_ok=True)
    _check_chain(root, base, what)  # re-check: nothing planted while creating it
    run_dir = base / f"run-{stamp}"
    try:
        run_dir.mkdir(exist_ok=False)
    except FileExistsError:
        raise ExtractError(f"{what}: this run's folder already exists; nothing is ever overwritten") from None
    _check_chain(root, run_dir, what)
    return run_dir


def _exclusive_write(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    if os.name == "posix":
        os.chmod(path, 0o600)


# Windows: replace the inherited DACL with one protected Allow FullControl entry for the current user, then read it
# back. The target path travels in an environment variable (a path, never text); the output is SIDs and flags.
# .NET calls only: Get-Acl's module fails to autoload when PowerShell 7's PSModulePath leaks into Windows PowerShell.
_OWNER_ONLY_PS = r"""
$ErrorActionPreference = 'Stop'
$p = $env:CTE_PRIVATE_TARGET
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = New-Object System.Security.AccessControl.FileSecurity
$acl.SetAccessRuleProtection($true, $false)
$acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'Allow')))
[System.IO.File]::SetAccessControl($p, $acl)
$a = [System.IO.File]::GetAccessControl($p)
$r = @($a.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
$who = ($r | ForEach-Object { $_.IdentityReference.Value }) -join ','
$what = ($r | ForEach-Object { '' + $_.AccessControlType + ':' + $_.FileSystemRights }) -join ','
'{0}|{1}|{2}|{3}|{4}' -f $a.AreAccessRulesProtected, $r.Count, $sid.Value, $who, $what
"""


def _restrict_owner_only(path: Path) -> dict:
    """Owner-only access where supported. Windows: protected DACL, one ACE; POSIX: mode 0600. Fails closed."""
    if os.name == "posix":
        os.chmod(path, 0o600)
        if stat.S_IMODE(os.lstat(path).st_mode) != 0o600:
            raise ExtractError("review artifact: could not restrict access to the owner")
        return {"method": "posix-0600", "owner_only": True}
    if os.name != "nt":
        return {"method": "unsupported", "owner_only": False}
    shell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    env = dict(os.environ, CTE_PRIVATE_TARGET=str(path))
    try:
        done = subprocess.run([str(shell), "-NoProfile", "-NonInteractive", "-Command", _OWNER_ONLY_PS], env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        raise ExtractError("review artifact: could not restrict access to the owner") from None
    fields = done.stdout.strip().splitlines()[-1].split("|") if done.stdout.strip() else []
    ok = (done.returncode == 0 and len(fields) == 5 and fields[0] == "True" and fields[1] == "1"
          and fields[3] == fields[2] and fields[4] == "Allow:FullControl")
    if not ok:
        raise ExtractError("review artifact: could not restrict access to the owner")
    return {"method": "windows-protected-dacl", "owner_only": True, "ace_count": 1, "owner_sid": fields[2]}


def _document(mode: str, tag: str, store_sha256: str, entries, report: dict) -> dict:
    if mode == MODE_REVIEW_PENDING:
        status = {row["reference_id"]: row["review_status"] for row in report["entries"]}
        return {
            "kind": PENDING_KIND,
            "schema": SCHEMA,
            "status": "REVIEW-PENDING",
            "approval": "UNAPPROVED - NOT FOR SYNTHESIS",
            "notice": ("PRIVATE owner review only. UNAPPROVED - NOT FOR SYNTHESIS OR PUBLICATION. The six ORIGINAL "
                       "Qwen3 clone transcripts, copied verbatim from the preserved store. Entries marked "
                       "OWNER_CORRECTION_REQUIRED fail a plan check and must be corrected by the owner. After any "
                       "edit the original_text_* fields are stale by design; the corrected file needs fresh "
                       "validation, new digests and explicit owner approval before any use. Do not share, commit "
                       "or paste into any AI."),
            "manifest_tag": tag,
            "source_store_sha256": store_sha256,
            "owner_correction_required": report["owner_correction_required"],
            "entries": [{"reference_id": ref_id, "voice_id": voice_id, "wav_sha256": wav,
                         "review_status": status[ref_id],
                         "original_text_sha256": sha256_bytes(text.encode("utf-8")),
                         "original_text_length": len(text), "text": text}
                        for ref_id, voice_id, wav, text in entries],
        }
    return {
        "kind": KIND,
        "schema": SCHEMA,
        "notice": ("PRIVATE owner review only. Six owner-approved Qwen3 clone transcripts, copied verbatim from "
                   "the preserved store. Not a publishable bundle. Do not share, commit or paste into any AI."),
        "manifest_tag": tag,
        "source_store_sha256": store_sha256,
        "entries": [{"reference_id": ref_id, "voice_id": voice_id, "wav_sha256": wav,
                     "text_sha256": sha256_bytes(text.encode("utf-8")), "text_length": len(text), "text": text}
                    for ref_id, voice_id, wav, text in entries],
    }


def run(root: Path, manifest_rel: str, registry, report: dict, stamp: str, _after_read=None,
        mode: str = MODE_FINAL) -> None:
    pending = mode == MODE_REVIEW_PENDING
    store, preserved = locate_store(root, manifest_rel, report)
    recordings_ok = validate_recordings(root, registry, report)

    before = _fingerprint(store)
    if before["size"] > MAX_STORE_BYTES:
        raise ExtractError("transcript store: larger than any six-entry store")
    with open(store, "rb") as handle:  # the one authorised read; read-only
        raw = handle.read()
    report["source_store"]["fingerprint_before"] = before
    if sha256_bytes(raw) != before["sha256"]:
        raise ExtractError("transcript store: changed while being read")
    if _after_read is not None:
        _after_read(store)
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except ExtractError:
        raise
    except (UnicodeDecodeError, ValueError):
        raise ExtractError("transcript store: not valid UTF-8 JSON") from None
    entries = validate_store(data, registry, report, mode)
    if not recordings_ok:
        raise ExtractError("reference recordings: one or more do not match their registered hash")

    dir_stamp = f"{stamp}-review-pending" if pending else stamp
    artifact_dir_rel = f"{REVIEW_BASE_REL}/run-{dir_stamp}"
    artifact_path = Path(os.path.normpath(root / artifact_dir_rel / (PENDING_ARTIFACT_NAME if pending
                                                                     else ARTIFACT_NAME)))
    if not _git_ignored(root, artifact_path):
        raise ExtractError("review destination: not gitignored")
    forbidden = [preserved, Path(os.path.normpath(root / RUNTIME_DATA_ORIGINAL))]
    run_dir = _safe_new_dir(root, REVIEW_BASE_REL, dir_stamp, "review destination", forbidden)

    document = _document(mode, report["manifest"]["tag"], before["sha256"], entries, report)
    payload = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _exclusive_write(artifact_path, payload)
    try:
        access = _restrict_owner_only(artifact_path)
        written = artifact_path.read_bytes()
        reread = json.loads(written.decode("utf-8"))
        if written != payload or [e["text"] for e in reread["entries"]] != [e[3] for e in entries]:
            raise ExtractError("review artifact: read-back does not match")
        after = _fingerprint(store)
        report["source_store"]["fingerprint_after"] = after
        report["source_store"]["unchanged"] = after == before
        if after != before:
            raise ExtractError("transcript store: changed during extraction")
    except BaseException:
        os.unlink(artifact_path)
        os.rmdir(run_dir)
        report["artifact"] = None
        raise
    report["artifact"] = {"path": _rel(root, artifact_path), "sha256": sha256_bytes(written),
                          "bytes": len(written), "entry_count": len(entries),
                          "gitignored": _git_ignored(root, artifact_path), "access": access}
    if pending:
        report["artifact"].update({"kind": PENDING_KIND, "status": "REVIEW-PENDING", "approved_for_synthesis": False})


def _write_metadata(root: Path, report: dict, stamp: str) -> None:
    """Best effort: the metadata report (no transcript text) beside the tool's evidence, never in the private folder."""
    try:
        base = Path(os.path.normpath(root / METADATA_BASE_REL))
        _check_chain(root, base, "metadata destination")
        target = base / f"extraction-{stamp}.json"
        if not _git_ignored(root, target):
            report["metadata_file"] = None
            return
        base.mkdir(parents=True, exist_ok=True)
        _check_chain(root, base, "metadata destination")
        report["metadata_file"] = _rel(root, target)
        _exclusive_write(target, (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    except Exception as exc:  # metadata is a convenience; the result stands without it
        report["metadata_file"] = None
        report["metadata_file_error"] = type(exc).__name__


def _utc_stamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def main(argv: list[str] | None = None, *, registry=REGISTRY, _after_read=None, _stamp=None) -> int:
    parser = argparse.ArgumentParser(description="No-echo extraction of the six approved clone transcripts "
                                                 "(developer only; metadata-only output).")
    parser.add_argument("--repo-root", required=True, help="repository root (paths only; no text arguments)")
    parser.add_argument("--manifest", required=True,
                        help="the preservation manifest preservation-<tag>.json, relative to the root")
    parser.add_argument("--mode", choices=(MODE_FINAL, MODE_REVIEW_PENDING), default=MODE_FINAL,
                        help="final (default): every check must pass. review-pending: a Male-4 prefix failure is "
                             "flagged for owner correction in an UNAPPROVED private artifact; never PASS")
    args = parser.parse_args(argv)

    stamp = _stamp or _utc_stamp()
    report: dict = {"tool": "clone_transcript_extract", "utc": stamp, "result": "FAIL", "failure": None,
                    "tool_sha256": sha256_file(Path(__file__)), "mode": args.mode}
    code = EXIT_REFUSED
    root = None
    try:
        root = Path(os.path.realpath(args.repo_root))
        if not root.is_dir():
            raise ExtractError("repository root: not a directory")
        run(root, args.manifest, registry, report, stamp, _after_read, args.mode)
        if args.mode == MODE_REVIEW_PENDING:
            report["result"], code = "REVIEW_PENDING", EXIT_REVIEW_PENDING
        else:
            report["result"], code = "PASS", EXIT_PASS
    except ExtractError as exc:
        report["failure"] = str(exc)
    except Exception as exc:  # never let a traceback (which could quote data) reach the console
        report["failure"] = f"unexpected {type(exc).__name__} (details withheld)"
        code = EXIT_UNEXPECTED
    if root is not None and root.is_dir():
        _write_metadata(root, report, stamp)
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
