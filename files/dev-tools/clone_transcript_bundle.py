"""ACT v0.7.0 -- deterministic generation of the shipped clone-transcript bundle from the owner-approved review file.

Plan Revision 2 §5.3 step 5 / P03C. Developer only: never shipped, never imported by the app, never a user requirement.

    python -I files/dev-tools/clone_transcript_bundle.py --repo-root <root> --artifact <repo-relative review file>
        --approved-sha256 <the SHA-256 the owner approved> [--bundle-revision 1] [--check]

It reads ONE private review file (the review-pending or final format written by clone_transcript_extract.py) exactly
once and refuses it unless its SHA-256 is the one the owner approved. It then checks the envelope and each entry
against the exact expected field sets (an unrelated or missing field is refused, never dropped silently), the six
registered reference IDs in registry order with their voice IDs and WAV hashes, each text (string, non-blank, within
the production limit, no outer whitespace, no control characters; Male-4 starts with "Hello Arthur.") and the six
recordings on disk. Only then does it write ``scripts/tts/data/bundled_clone_transcripts.json`` with exactly
``schema_version``, ``bundle_revision`` and six ``entries`` of ``reference_id``, ``voice_id``, ``wav_sha256``, ``text``
and ``text_sha256`` -- nothing from the review envelope, no approval record, path, name or timestamp. The texts are
copied byte for byte from the approved file (no strip, no normalisation); nobody types them.

Output is deterministic (UTF-8, no BOM, LF, two-space indent, fixed key order), written by exclusive create (an
existing bundle is never overwritten) and read back. ``--check`` writes nothing: it proves the committed bundle is
byte-identical to what the approved file generates.

Everything printed is metadata (IDs, lengths, booleans, SHA-256 digests, repo-relative paths). Refusals are fixed
strings written here; any other exception is reported by type name only.

Exit codes: 0 PASS, 2 refused, 3 unexpected error (details withheld).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import clone_transcript_extract as cte  # noqa: E402

BUNDLE_REL = "scripts/tts/data/bundled_clone_transcripts.json"
SCHEMA_VERSION = 1
MAX_ARTIFACT_BYTES = 1 << 16  # six short transcripts plus their envelope
EXIT_PASS, EXIT_REFUSED, EXIT_UNEXPECTED = 0, 2, 3
_HEX64 = re.compile(r"[0-9a-f]{64}")

#: The two review formats clone_transcript_extract.py writes: kind -> (envelope keys, entry keys), in written order.
FORMATS = {
    cte.PENDING_KIND: (("kind", "schema", "status", "approval", "notice", "manifest_tag", "source_store_sha256",
                        "owner_correction_required", "entries"),
                       ("reference_id", "voice_id", "wav_sha256", "review_status", "original_text_sha256",
                        "original_text_length", "text")),
    cte.KIND: (("kind", "schema", "notice", "manifest_tag", "source_store_sha256", "entries"),
               ("reference_id", "voice_id", "wav_sha256", "text_sha256", "text_length", "text")),
}


class BundleError(Exception):
    """A refusal. Its message is always a fixed string written here -- never transcript content."""


def _reject_duplicates(pairs: list) -> dict:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise BundleError("artifact: duplicate key")
    return dict(pairs)


def read_approved(root: Path, artifact_rel: str, approved_sha256: str, report: dict) -> bytes:
    """The approved file's bytes, read once -- or a refusal if it is not exactly the approved file."""
    if not isinstance(approved_sha256, str) or not _HEX64.fullmatch(approved_sha256):
        raise BundleError("approved hash: not 64 lowercase hexadecimal characters")
    artifact = Path(os.path.normpath(root / artifact_rel))
    cte._check_chain(root, artifact, "artifact")
    try:
        st = os.lstat(artifact)
    except FileNotFoundError:
        raise BundleError("artifact: not found") from None
    if not stat.S_ISREG(st.st_mode):
        raise BundleError("artifact: not a regular file")
    if st.st_size > MAX_ARTIFACT_BYTES:
        raise BundleError("artifact: larger than a six-transcript review file can be")
    if not cte._git_ignored(root, artifact):
        raise BundleError("artifact: not git-ignored, so it is not the private review file")
    with open(artifact, "rb") as handle:  # the one read
        raw = handle.read()
    actual = cte.sha256_bytes(raw)
    report["artifact"] = {"path": cte._rel(root, artifact), "bytes": len(raw), "sha256": actual,
                          "approved_sha256": approved_sha256, "matches_approved": actual == approved_sha256}
    if actual != approved_sha256:
        raise BundleError("artifact: SHA-256 is not the approved hash")
    return raw


def _text_problem(text: object) -> str | None:
    if not isinstance(text, str):
        return "not a string"
    if not text.strip():
        return "blank"
    if len(text) > cte.MAX_TRANSCRIPT_CHARS:
        return "longer than the production limit"
    if text != text.strip():
        return "leading or trailing whitespace"
    if any(unicodedata.category(ch) == "Cc" for ch in text):
        return "control characters"
    return None


def curated_entries(raw: bytes, registry, report: dict) -> list[tuple[str, str, str, str]]:
    """``[(reference_id, voice_id, wav_sha256, text)]`` in registry order from the approved bytes, or a refusal."""
    if raw.startswith(b"\xef\xbb\xbf"):
        raise BundleError("artifact: carries a UTF-8 byte-order mark")
    try:
        doc = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except BundleError:
        raise
    except (UnicodeDecodeError, ValueError):
        raise BundleError("artifact: not valid UTF-8 JSON") from None
    if not isinstance(doc, dict) or doc.get("kind") not in FORMATS:
        raise BundleError("artifact: not a clone transcript review file")
    top_keys, entry_keys = FORMATS[doc["kind"]]
    if sorted(doc) != sorted(top_keys):
        raise BundleError("artifact: envelope fields are not exactly the expected set")
    if doc.get("schema") != cte.SCHEMA:
        raise BundleError("artifact: unknown schema")
    entries = doc["entries"]
    if not isinstance(entries, list) or len(entries) != len(registry):
        raise BundleError("artifact: does not hold exactly six entries")
    if [e.get("reference_id") if isinstance(e, dict) else None for e in entries] != [r[0] for r in registry]:
        raise BundleError("artifact: entries are not exactly the six registered IDs in registry order")
    out, rows = [], []
    for (ref_id, voice_id, _basename, wav), entry in zip(registry, entries):
        if sorted(entry) != sorted(entry_keys):
            raise BundleError(f"artifact: {ref_id} fields are not exactly the expected set")
        if entry["voice_id"] != voice_id or entry["wav_sha256"] != wav:
            raise BundleError(f"artifact: {ref_id} voice ID or recording hash does not match the registry")
        text = entry["text"]
        problem = _text_problem(text)
        if problem:
            raise BundleError(f"artifact: {ref_id} text is {problem}")
        text_sha = cte.sha256_bytes(text.encode("utf-8"))
        if "text_sha256" in entry_keys and (entry["text_sha256"] != text_sha or entry["text_length"] != len(text)):
            raise BundleError(f"artifact: {ref_id} text does not match its recorded digest")
        row = {"reference_id": ref_id, "voice_id": voice_id, "wav_sha256": wav, "text_length": len(text),
               "text_sha256": text_sha}
        if ref_id == "Male-4":
            row["starts_with_hello_arthur"] = text.startswith(cte.MALE4_PREFIX)
            if not row["starts_with_hello_arthur"]:
                raise BundleError("artifact: Male-4 does not start with the required prefix")
        rows.append(row)
        out.append((ref_id, voice_id, wav, text))
    report["kind"] = doc["kind"]
    report["entries"] = rows
    return out


def render(entries, bundle_revision: int) -> bytes:
    """The bundle's exact bytes: the five published fields per entry, fixed order, UTF-8, LF, final newline."""
    doc = {"schema_version": SCHEMA_VERSION, "bundle_revision": bundle_revision,
           "entries": [{"reference_id": ref_id, "voice_id": voice_id, "wav_sha256": wav, "text": text,
                        "text_sha256": cte.sha256_bytes(text.encode("utf-8"))}
                       for ref_id, voice_id, wav, text in entries]}
    return (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def run(root: Path, artifact_rel: str, approved_sha256: str, registry, report: dict, *, bundle_revision: int = 1,
        check: bool = False) -> None:
    if type(bundle_revision) is not int or bundle_revision < 1:
        raise BundleError("bundle revision: must be a positive integer")
    raw = read_approved(root, artifact_rel, approved_sha256, report)
    entries = curated_entries(raw, registry, report)
    if not cte.validate_recordings(root, registry, report):
        raise BundleError("recordings: a reference recording is missing or does not match its registered hash")
    payload = render(entries, bundle_revision)
    bundle = Path(os.path.normpath(root / BUNDLE_REL))
    cte._check_chain(root, bundle, "bundle")
    if cte._git_ignored(root, bundle):
        raise BundleError("bundle: destination is git-ignored, so it would not ship")
    if check:
        if not bundle.is_file() or bundle.read_bytes() != payload:
            raise BundleError("bundle: the committed file is not byte-identical to what the approved file generates")
    else:
        bundle.parent.mkdir(parents=True, exist_ok=True)
        cte._check_chain(root, bundle, "bundle")
        try:
            with open(bundle, "xb") as handle:  # exclusive create: an existing bundle is never overwritten
                handle.write(payload)
        except FileExistsError:
            raise BundleError("bundle: already exists; it is never overwritten") from None
        if bundle.read_bytes() != payload:
            raise BundleError("bundle: read-back does not match what was written")
    report["bundle"] = {"path": BUNDLE_REL, "bytes": len(payload), "sha256": cte.sha256_bytes(payload),
                        "bundle_revision": bundle_revision, "written": not check}


def main(argv: list[str] | None = None, *, registry=cte.REGISTRY) -> int:
    parser = argparse.ArgumentParser(description="Generate the shipped clone-transcript bundle from the owner-approved "
                                                 "review file (developer only; metadata-only output).")
    parser.add_argument("--repo-root", required=True, help="repository root")
    parser.add_argument("--artifact", required=True, help="the approved private review file, relative to the root")
    parser.add_argument("--approved-sha256", required=True, help="the SHA-256 the owner approved for that file")
    parser.add_argument("--bundle-revision", type=int, default=1)
    parser.add_argument("--check", action="store_true", help="write nothing; prove the bundle matches")
    args = parser.parse_args(argv)

    report: dict = {"tool": "clone_transcript_bundle", "result": "FAIL", "failure": None,
                    "tool_sha256": cte.sha256_file(Path(__file__)), "mode": "check" if args.check else "write"}
    code = EXIT_REFUSED
    try:
        root = Path(os.path.realpath(args.repo_root))
        if not root.is_dir():
            raise BundleError("repository root: not a directory")
        run(root, args.artifact, args.approved_sha256, registry, report, bundle_revision=args.bundle_revision,
            check=args.check)
        report["result"], code = "PASS", EXIT_PASS
    except (BundleError, cte.ExtractError) as exc:
        report["failure"] = str(exc)
    except Exception as exc:  # never let a traceback (which could quote data) reach the console
        report["failure"] = f"unexpected {type(exc).__name__} (details withheld)"
        code = EXIT_UNEXPECTED
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
