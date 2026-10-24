"""v0.7.0 P03C — the deterministic bundle generator (``files/dev-tools/clone_transcript_bundle.py``).

Synthetic fixtures only. Every case builds a throwaway git repository under ``tmp_path`` with six synthetic recordings and
a synthetic private review file (both formats clone_transcript_extract.py writes) whose texts each carry a unique secret
marker; nothing here reads the owner's real review file. Each run is checked for its exit code, exactly what was (not)
written, and that no text reaches stdout or stderr.
"""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
import unicodedata
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_TOOLS = REPO_ROOT / "files" / "dev-tools"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(DEV_TOOLS))

import clone_transcript_bundle as ctb  # noqa: E402
import clone_transcript_extract as cte  # noqa: E402

IDS = [row[0] for row in cte.REGISTRY]
ARTIFACT_REL = f"{cte.REVIEW_BASE_REL}/run-20990101T000000000000Z-review-pending/{cte.PENDING_ARTIFACT_NAME}"
DRIVER = ("import sys, json; sys.path.insert(0, sys.argv[1]); import clone_transcript_bundle as m; "
          "reg = tuple(tuple(r) for r in json.load(open(sys.argv[2], encoding='utf-8'))); "
          "sys.exit(m.main(sys.argv[3:], registry=reg))")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Fake:
    """A synthetic repository with six recordings and a valid review-pending artifact."""

    def __init__(self, base: Path):
        self.root = base / "repo"
        self.root.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "--template=", str(self.root)], check=True)
        (self.root / ".gitignore").write_text("files/dev-work/\n", encoding="utf-8")
        refs = self.root / cte.REFS_REL
        refs.mkdir(parents=True)
        self.registry = []
        for ref_id, voice_id, basename, _real_hash in cte.REGISTRY:
            data = f"RIFF-synthetic-{ref_id}-{uuid.uuid4().hex}".encode()
            (refs / basename).write_bytes(data)
            self.registry.append([ref_id, voice_id, basename, sha(data)])
        self.regfile = base / "registry.json"
        self.regfile.write_text(json.dumps(self.registry), encoding="utf-8")
        self.secrets: list[str] = []
        self.texts: dict[str, str] = {}
        for ref_id in IDS:
            mark = "ZSECRET" + uuid.uuid4().hex
            self.secrets.append(mark)
            prefix = cte.MALE4_PREFIX + " " if ref_id == "Male-4" else ""
            self.texts[ref_id] = f"{prefix}The {mark} lantern stayed lit  until morning."
        # Non-ASCII, decomposed and a curly quote: copied byte for byte, never normalised.
        self.texts["Female-2"] = "Café “noir” " + self.texts["Female-2"]
        self.artifact = self.root / ARTIFACT_REL
        self.doc = self.pending_doc()
        self.argv_extra: list[str] = []

    def wav(self, ref_id: str) -> str:
        return next(r[3] for r in self.registry if r[0] == ref_id)

    def voice(self, ref_id: str) -> str:
        return next(r[1] for r in self.registry if r[0] == ref_id)

    def pending_doc(self) -> dict:
        return {"kind": cte.PENDING_KIND, "schema": cte.SCHEMA, "status": "REVIEW-PENDING",
                "approval": "UNAPPROVED - NOT FOR SYNTHESIS", "notice": "synthetic", "manifest_tag": "x",
                "source_store_sha256": "0" * 64, "owner_correction_required": [],
                "entries": [{"reference_id": r, "voice_id": self.voice(r), "wav_sha256": self.wav(r),
                             "review_status": cte.REVIEW_REQUIRED, "original_text_sha256": "1" * 64,
                             "original_text_length": 1, "text": self.texts[r]} for r in IDS]}

    def final_doc(self) -> dict:
        return {"kind": cte.KIND, "schema": cte.SCHEMA, "notice": "synthetic", "manifest_tag": "x",
                "source_store_sha256": "0" * 64,
                "entries": [{"reference_id": r, "voice_id": self.voice(r), "wav_sha256": self.wav(r),
                             "text_sha256": sha(self.texts[r].encode("utf-8")), "text_length": len(self.texts[r]),
                             "text": self.texts[r]} for r in IDS]}

    def write(self, raw: bytes | None = None) -> str:
        """Write the artifact; return its SHA-256 (what the owner would approve)."""
        payload = raw if raw is not None else json.dumps(self.doc, indent=2, ensure_ascii=False).encode("utf-8")
        self.artifact.parent.mkdir(parents=True, exist_ok=True)
        self.artifact.write_bytes(payload)
        return sha(payload)

    @property
    def bundle(self) -> Path:
        return self.root / ctb.BUNDLE_REL

    def run(self, approved: str, *, artifact: str = ARTIFACT_REL, extra: tuple[str, ...] = ()) -> "Outcome":
        before = self.artifact.read_bytes() if self.artifact.is_file() else None
        done = subprocess.run([sys.executable, "-I", "-c", DRIVER, str(DEV_TOOLS), str(self.regfile),
                               "--repo-root", str(self.root), "--artifact", artifact, "--approved-sha256", approved,
                               *extra], capture_output=True, text=True, encoding="utf-8")
        after = self.artifact.read_bytes() if self.artifact.is_file() else None
        return Outcome(self, done.returncode, done.stdout, done.stderr, before == after)


class Outcome:
    def __init__(self, fake: Fake, code: int, out: str, err: str, source_same: bool):
        self.fake, self.code, self.out, self.err, self.source_same = fake, code, out, err, source_same
        self.report = json.loads(out) if out.strip().startswith("{") else None
        haystack = out + err
        self.leaks = [s for s in fake.secrets if s in haystack] + [t for t in fake.texts.values() if t in haystack]


def _has_key(obj, key: str) -> bool:
    if isinstance(obj, dict):
        return key in obj or any(_has_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_key(v, key) for v in obj)
    return False


def assert_clean(o: Outcome) -> None:
    assert o.source_same, "the approved file changed"
    assert o.leaks == [], "a fixture text reached stdout/stderr"
    assert not _has_key(o.report, "text"), "the console report carries a text field"


def assert_refused(o: Outcome, failure_contains: str, *, bundle_before: bytes | None = None) -> None:
    assert o.code == ctb.EXIT_REFUSED, (o.code, o.report and o.report.get("failure"), o.err[-400:])
    assert o.report is not None and o.report["result"] == "FAIL"
    assert failure_contains in (o.report["failure"] or ""), o.report["failure"]
    if bundle_before is None:
        assert not o.fake.bundle.exists(), "a refused run wrote a bundle"
    else:
        assert o.fake.bundle.read_bytes() == bundle_before, "a refused run changed the existing bundle"
    assert_clean(o)


@pytest.fixture
def fake(tmp_path):
    return Fake(tmp_path)


# --------------------------------------------------------------------------- #
# The approved file becomes exactly the five-field bundle
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fmt", ["pending", "final"])
def test_the_approved_file_becomes_exactly_the_published_bundle(fake, fmt):
    fake.doc = fake.pending_doc() if fmt == "pending" else fake.final_doc()
    approved = fake.write()
    o = fake.run(approved)
    assert o.code == ctb.EXIT_PASS, (o.report and o.report["failure"], o.err[-400:])
    assert_clean(o)
    raw = fake.bundle.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"}\n")
    doc = json.loads(raw.decode("utf-8"))
    assert list(doc) == ["schema_version", "bundle_revision", "entries"]
    assert doc["schema_version"] == 1 and doc["bundle_revision"] == 1
    assert [e["reference_id"] for e in doc["entries"]] == IDS
    for entry in doc["entries"]:
        ref = entry["reference_id"]
        assert list(entry) == ["reference_id", "voice_id", "wav_sha256", "text", "text_sha256"]
        assert entry["voice_id"] == fake.voice(ref) and entry["wav_sha256"] == fake.wav(ref)
        assert entry["text"] == fake.texts[ref]  # byte for byte: inner double space, NFD and curly quotes kept
        assert entry["text_sha256"] == sha(fake.texts[ref].encode("utf-8"))
    assert unicodedata.is_normalized("NFD", doc["entries"][1]["text"][:5])
    for leaked in ("REVIEW-PENDING", "UNAPPROVED", "synthetic", "manifest_tag", "source_store", "review_status",
                   "original_text", "approved", "notice"):
        assert leaked not in raw.decode("utf-8")
    assert o.report["artifact"]["sha256"] == approved and o.report["bundle"]["sha256"] == sha(raw)
    assert o.report["kind"] == fake.doc["kind"]


def test_generation_is_deterministic_and_check_mode_proves_it_without_writing(fake, tmp_path):
    approved = fake.write()
    assert fake.run(approved).code == ctb.EXIT_PASS
    first = fake.bundle.read_bytes()
    other = Fake(tmp_path / "again")
    other.registry, other.texts = fake.registry, fake.texts  # same inputs, a second repository
    other.regfile.write_text(json.dumps(other.registry), encoding="utf-8")
    for ref_id, _v, basename, _h in cte.REGISTRY:
        (other.root / cte.REFS_REL / basename).write_bytes((fake.root / cte.REFS_REL / basename).read_bytes())
    other.doc = other.pending_doc()
    assert other.write() == approved and other.run(approved).code == ctb.EXIT_PASS
    assert other.bundle.read_bytes() == first

    mtime = fake.bundle.stat().st_mtime_ns
    o = fake.run(approved, extra=("--check",))
    assert o.code == ctb.EXIT_PASS and o.report["bundle"]["written"] is False
    assert fake.bundle.read_bytes() == first and fake.bundle.stat().st_mtime_ns == mtime
    assert_clean(o)


def test_check_mode_refuses_a_bundle_that_differs_or_is_missing(fake):
    approved = fake.write()
    assert_refused(fake.run(approved, extra=("--check",)), "not byte-identical")
    assert fake.run(approved).code == ctb.EXIT_PASS
    tampered = fake.bundle.read_bytes().replace(b"lantern", b"lanterN", 1)
    fake.bundle.write_bytes(tampered)
    assert_refused(fake.run(approved, extra=("--check",)), "not byte-identical", bundle_before=tampered)


def test_an_existing_bundle_is_never_overwritten(fake):
    approved = fake.write()
    fake.bundle.parent.mkdir(parents=True)
    fake.bundle.write_bytes(b"previous bundle")
    assert_refused(fake.run(approved), "never overwritten", bundle_before=b"previous bundle")


def test_a_bundle_revision_is_recorded_and_must_be_positive(fake):
    approved = fake.write()
    assert_refused(fake.run(approved, extra=("--bundle-revision", "0")), "positive integer")
    assert fake.run(approved, extra=("--bundle-revision", "3")).code == ctb.EXIT_PASS
    assert json.loads(fake.bundle.read_text(encoding="utf-8"))["bundle_revision"] == 3


# --------------------------------------------------------------------------- #
# Only the approved file, unchanged
# --------------------------------------------------------------------------- #
def test_any_hash_but_the_approved_one_is_refused(fake):
    approved = fake.write()
    assert_refused(fake.run("0" * 64), "not the approved hash")
    assert_refused(fake.run(approved.upper()), "64 lowercase")
    assert_refused(fake.run(approved[:-1]), "64 lowercase")
    fake.texts["Male-1"] += " One more word."  # an edit after approval changes the hash
    fake.doc = fake.pending_doc()
    fake.write()
    o = fake.run(approved)
    assert_refused(o, "not the approved hash")
    assert o.report["artifact"]["matches_approved"] is False


def test_a_missing_tracked_or_oversized_artifact_is_refused(fake):
    assert_refused(fake.run("0" * 64), "not found")
    approved = fake.write()
    tracked = "scripts/review.json"  # outside the ignored private folder
    (fake.root / tracked).parent.mkdir(parents=True, exist_ok=True)
    (fake.root / tracked).write_bytes(fake.artifact.read_bytes())
    assert_refused(fake.run(approved, artifact=tracked), "not git-ignored")
    assert_refused(fake.run(approved, artifact="../outside.json"), "outside the repository")
    big = fake.write(b" " * (ctb.MAX_ARTIFACT_BYTES + 1))
    assert_refused(fake.run(big), "larger than")
    fake.artifact.unlink()
    fake.artifact.mkdir()
    assert_refused(fake.run(approved), "not a regular file")


# --------------------------------------------------------------------------- #
# Unrelated or missing fields are refused, never dropped
# --------------------------------------------------------------------------- #
def _mutated(fake, mutate) -> str:
    doc = json.loads(json.dumps(fake.doc))
    mutate(doc)
    fake.doc = doc
    return fake.write()


@pytest.mark.parametrize("mutate,why", [
    (lambda d: d.update(approved_by="the owner"), "envelope fields"),
    (lambda d: d.pop("notice"), "envelope fields"),
    (lambda d: d.update(kind="something-else"), "not a clone transcript review file"),
    (lambda d: d.update(schema=2), "unknown schema"),
    (lambda d: d["entries"][2].update(approved=True), "Male-1 fields"),
    (lambda d: d["entries"][0].update(approved_on="2099-01-01"), "Female-1 fields"),
    (lambda d: d["entries"][3].pop("review_status"), "Male-2 fields"),
    (lambda d: d["entries"].pop(), "exactly six entries"),
    (lambda d: d["entries"].append(dict(d["entries"][0])), "exactly six entries"),
    (lambda d: d["entries"].reverse(), "registry order"),
    (lambda d: d["entries"].__setitem__(1, dict(d["entries"][0])), "registry order"),
    (lambda d: d["entries"][4].update(voice_id="qwen3-male-1"), "does not match the registry"),
    (lambda d: d["entries"][4].update(wav_sha256="f" * 64), "does not match the registry"),
    (lambda d: d["entries"][0].update(text="   "), "blank"),
    (lambda d: d["entries"][0].update(text=None), "not a string"),
    (lambda d: d["entries"][0].update(text=" " + d["entries"][0]["text"]), "whitespace"),
    (lambda d: d["entries"][0].update(text=d["entries"][0]["text"] + "\n"), "whitespace"),
    (lambda d: d["entries"][0].update(text=d["entries"][0]["text"].replace(" ", "\t", 1)), "control"),
    (lambda d: d["entries"][0].update(text="x" * (cte.MAX_TRANSCRIPT_CHARS + 1)), "production limit"),
    (lambda d: d["entries"][5].update(text=d["entries"][5]["text"][len(cte.MALE4_PREFIX):].lstrip()), "Male-4"),
    (lambda d: d["entries"][5].update(text="“" + d["entries"][5]["text"]), "Male-4"),
])
def test_an_envelope_or_entry_that_is_not_exactly_the_expected_shape_is_refused(fake, mutate, why):
    assert_refused(fake.run(_mutated(fake, mutate)), why)


def test_a_final_format_digest_mismatch_is_refused(fake):
    fake.doc = fake.final_doc()
    assert_refused(fake.run(_mutated(fake, lambda d: d["entries"][1].update(text_sha256="2" * 64))),
                   "recorded digest")
    fake.doc = fake.final_doc()
    assert_refused(fake.run(_mutated(fake, lambda d: d["entries"][1].update(text_length=1))), "recorded digest")


def test_duplicate_keys_a_byte_order_mark_and_bad_json_are_refused(fake):
    text = json.dumps(fake.doc, ensure_ascii=False)
    assert_refused(fake.run(fake.write(text.replace('"schema": 1,', '"schema": 1, "schema": 1,', 1).encode())),
                   "duplicate key")
    assert_refused(fake.run(fake.write(b"\xef\xbb\xbf" + text.encode("utf-8"))), "byte-order mark")
    assert_refused(fake.run(fake.write(b"{not json")), "not valid UTF-8 JSON")
    assert_refused(fake.run(fake.write(b"\xff\xfe")), "not valid UTF-8 JSON")
    assert_refused(fake.run(fake.write(b"[]")), "not a clone transcript review file")


def test_a_changed_or_missing_recording_is_refused(fake):
    approved = fake.write()
    wav = fake.root / cte.REFS_REL / cte.REGISTRY[3][2]
    wav.write_bytes(b"a different recording")
    assert_refused(fake.run(approved), "recordings")
    wav.unlink()
    assert_refused(fake.run(approved), "recordings")


def test_an_unexpected_error_withholds_its_details(fake, monkeypatch):
    import io

    approved = fake.write()
    monkeypatch.setattr(ctb, "render", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(fake.secrets[0])))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    code = ctb.main(["--repo-root", str(fake.root), "--artifact", ARTIFACT_REL, "--approved-sha256", approved],
                    registry=tuple(tuple(r) for r in fake.registry))
    report = json.loads(out.getvalue())
    assert code == ctb.EXIT_UNEXPECTED and report["failure"] == "unexpected RuntimeError (details withheld)"
    assert fake.secrets[0] not in out.getvalue() and not fake.bundle.exists()


# --------------------------------------------------------------------------- #
# Tool boundaries
# --------------------------------------------------------------------------- #
def test_the_tool_imports_only_the_standard_library_and_the_extraction_helper():
    tree = ast.parse((DEV_TOOLS / "clone_transcript_bundle.py").read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add((node.module or "").split(".")[0])
    assert modules - {"__future__", "clone_transcript_extract"} <= set(sys.stdlib_module_names), modules
    assert "tts" not in modules and "shared" not in modules  # never the app


def test_the_bundle_destination_is_the_runtime_path_and_shipped():
    from tts import qwen3_runtime as rt

    assert REPO_ROOT / ctb.BUNDLE_REL == rt.bundled_transcripts_path()
    assert ctb.SCHEMA_VERSION == rt.BUNDLE_SCHEMA_VERSION
    ignored = subprocess.run(["git", "check-ignore", "-q", ctb.BUNDLE_REL], cwd=REPO_ROOT)
    assert ignored.returncode == 1, "the bundle must be trackable"
