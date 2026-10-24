"""v0.7.0 P03A — the no-echo transcript extraction helper (``files/dev-tools/clone_transcript_extract.py``).

Synthetic fixtures only (plan Revision 2 §5.3 step 6). Every case builds a throwaway git repository under ``tmp_path``
with six synthetic recordings, a synthetic preservation manifest and a synthetic store whose texts each carry a unique
secret marker; nothing here reads the real private store, the owner's review artifact or the real recordings' text.
Each run is checked for its exit code, what was (not) written, an unchanged source, and that no secret reaches stdout,
stderr or the metadata report.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
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

import clone_transcript_extract as cte  # noqa: E402

TAG = "20990101-000000-0badc0de"  # synthetic; the real tag lives only in the owner's ignored manifest
MANIFEST_REL = f"files/dev-work/manual-fresh-install/preservation-{TAG}.json"
IDS = [row[0] for row in cte.REGISTRY]
DRIVER = ("import sys, json; sys.path.insert(0, sys.argv[1]); import clone_transcript_extract as m; "
          "reg = tuple(tuple(r) for r in json.load(open(sys.argv[2], encoding='utf-8'))); "
          "sys.exit(m.main(sys.argv[3:], registry=reg))")


def secret() -> str:
    return "ZSECRET" + uuid.uuid4().hex


class Fake:
    """A synthetic repository with six recordings and a valid approved store."""

    def __init__(self, base: Path):
        self.root = base / "repo"
        self.root.mkdir(parents=True)
        # An empty template keeps sample hooks (and their long paths) out of the throwaway repository.
        subprocess.run(["git", "init", "-q", "--template=", str(self.root)], check=True)
        (self.root / ".gitignore").write_text("files/dev-work/\nfiles/runtime-data*/\n", encoding="utf-8")
        refs = self.root / cte.REFS_REL
        refs.mkdir(parents=True)
        self.registry = []
        for ref_id, voice_id, basename, _real_hash in cte.REGISTRY:
            data = f"RIFF-synthetic-{ref_id}-{uuid.uuid4().hex}".encode()
            (refs / basename).write_bytes(data)
            self.registry.append([ref_id, voice_id, basename, hashlib.sha256(data).hexdigest()])
        self.regfile = base / "registry.json"
        self.regfile.write_text(json.dumps(self.registry), encoding="utf-8")
        self.preserved = self.root / "files" / f"runtime-data.act67-preserved-{TAG}"
        (self.preserved / "qwen3").mkdir(parents=True)
        self.store = self.preserved / "qwen3" / "transcripts.json"
        self.secrets: list[str] = []
        self.texts: dict[str, str] = {}
        for ref_id in IDS:
            mark = secret()
            self.secrets.append(mark)
            prefix = cte.MALE4_PREFIX + " " if ref_id == "Male-4" else ""
            self.texts[ref_id] = f"{prefix}The {mark} lantern stayed lit until morning."
        self.data = {ref_id: self.entry(ref_id) for ref_id in IDS}
        self.manifest = {"Purpose": "synthetic", "Tag": TAG, "Repository": str(self.root), "Branch": "x",
                         "StartingHead": "0" * 40, "CreatedUtc": "2099-01-01T00:00:00Z", "State": "Preserved",
                         "Directories": [
                             {"Original": str(self.root / ".venv"),
                              "Preserved": str(self.root / f".venv.act67-preserved-{TAG}")},
                             {"Original": str(self.root / "files" / "runtime-data"), "Preserved": str(self.preserved)},
                         ]}

    def wav_hash(self, ref_id: str) -> str:
        return next(r[3] for r in self.registry if r[0] == ref_id)

    def entry(self, ref_id: str) -> dict:
        text = self.texts[ref_id]
        return {"text": text, "approved": True, "wav_sha256": self.wav_hash(ref_id),
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "approved_by": "owner (review page)", "approved_on": "2099-01-01"}

    def write(self, raw: str | None = None) -> None:
        self.store.write_text(raw if raw is not None else json.dumps(self.data, indent=2), encoding="utf-8")
        mpath = self.root / MANIFEST_REL
        mpath.parent.mkdir(parents=True, exist_ok=True)
        mpath.write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")

    def argv(self, mode: str | None = None, manifest: str = MANIFEST_REL) -> list[str]:
        return ["--repo-root", str(self.root), "--manifest", manifest] + (["--mode", mode] if mode else [])

    def run(self, mode: str | None = None, manifest: str = MANIFEST_REL) -> "Outcome":
        before = self.store.read_bytes() if self.store.is_file() else None
        done = subprocess.run([sys.executable, "-I", "-c", DRIVER, str(DEV_TOOLS), str(self.regfile),
                               *self.argv(mode, manifest)],
                              capture_output=True, text=True, encoding="utf-8")
        after = self.store.read_bytes() if self.store.is_file() else None
        return Outcome(self, done.returncode, done.stdout, done.stderr, before == after)

    def artifacts(self) -> list[Path]:
        base = self.root / cte.REVIEW_BASE_REL
        return [p for p in base.rglob("*") if p.is_file()] if base.is_dir() else []


class Outcome:
    def __init__(self, fake: Fake, code: int, out: str, err: str, source_same: bool):
        self.fake, self.code, self.out, self.err, self.source_same = fake, code, out, err, source_same
        self.report = json.loads(out) if out.strip().startswith("{") else None
        meta = ""
        if self.report and self.report.get("metadata_file"):
            meta = (fake.root / self.report["metadata_file"]).read_text(encoding="utf-8")
        self.meta = meta
        haystack = out + err + meta
        self.leaks = [s for s in fake.secrets if s in haystack] + [t for t in fake.texts.values() if t in haystack]


def _has_key(obj, key: str) -> bool:
    if isinstance(obj, dict):
        return key in obj or any(_has_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_key(v, key) for v in obj)
    return False


def assert_refused(o: Outcome, failure_contains: str = "", code: int = cte.EXIT_REFUSED) -> None:
    assert o.code == code, (o.code, o.report and o.report.get("failure"), o.err[-400:])
    assert o.report is not None and o.report["result"] == "FAIL"
    assert failure_contains in (o.report["failure"] or "")
    assert o.fake.artifacts() == [], "a refused run left a review file behind"
    assert o.source_same, "the source store changed"
    assert o.leaks == [], "a fixture secret reached stdout/stderr/metadata"
    assert not _has_key(o.report, "text"), "the console report carries a text field"


@pytest.fixture
def fake(tmp_path) -> Fake:
    return Fake(tmp_path)


def junction(link: Path, target: Path) -> None:
    """A directory junction on Windows (no privilege needed), a symlink elsewhere."""
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


# --------------------------------------------------------------------------- #
# A clean extraction
# --------------------------------------------------------------------------- #
def test_a_valid_store_yields_exactly_one_private_artifact_with_the_six_exact_texts(fake):
    fake.write()
    store_before = fake.store.read_bytes()
    o = fake.run()
    assert o.code == cte.EXIT_PASS, o.report and o.report.get("failure")
    assert o.report["result"] == "PASS" and o.leaks == [] and o.source_same
    assert not _has_key(o.report, "text")
    (artifact,) = fake.artifacts()
    assert artifact.name == cte.ARTIFACT_NAME
    doc = json.loads(artifact.read_text(encoding="utf-8"))
    assert doc["kind"] == cte.KIND and doc["schema"] == cte.SCHEMA and doc["manifest_tag"] == TAG
    assert doc["source_store_sha256"] == hashlib.sha256(store_before).hexdigest()
    assert [e["reference_id"] for e in doc["entries"]] == IDS
    for entry in doc["entries"]:
        assert set(entry) == {"reference_id", "voice_id", "wav_sha256", "text_sha256", "text_length", "text"}
        assert entry["text"] == fake.texts[entry["reference_id"]]
        assert entry["wav_sha256"] == fake.wav_hash(entry["reference_id"])
        assert entry["text_sha256"] == hashlib.sha256(entry["text"].encode("utf-8")).hexdigest()
    # Approval history and anything else in the store stay behind.
    assert "approved_by" not in artifact.read_text(encoding="utf-8")
    # Metadata about the artifact, and the source fingerprinted unchanged.
    meta = o.report["artifact"]
    assert meta["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest() and meta["entry_count"] == 6
    assert meta["gitignored"] is True and meta["access"]["owner_only"] is True
    src = o.report["source_store"]
    assert src["unchanged"] is True and src["fingerprint_before"] == src["fingerprint_after"]
    assert o.report["male4_prefix_ok"] is True
    assert fake.store.read_bytes() == store_before


def test_text_is_copied_byte_exact_without_stripping_or_normalising(fake):
    decomposed = unicodedata.normalize("NFD", "café")
    assert decomposed != unicodedata.normalize("NFC", decomposed)
    fake.texts["Female-1"] = f"  {fake.secrets[0]} {decomposed}\r\nline two \t"
    fake.data["Female-1"] = fake.entry("Female-1")
    fake.write()
    o = fake.run()
    assert o.code == cte.EXIT_PASS and o.leaks == []
    (artifact,) = fake.artifacts()
    entry = json.loads(artifact.read_text(encoding="utf-8"))["entries"][0]
    assert entry["text"] == fake.texts["Female-1"]
    row = next(r for r in o.report["entries"] if r["reference_id"] == "Female-1")
    assert row["text_has_outer_whitespace"] is True


def test_an_absent_stored_text_digest_is_accepted_and_reported_as_absent(fake):
    for ref_id in IDS:
        del fake.data[ref_id]["text_sha256"]
    fake.write()
    o = fake.run()
    assert o.code == cte.EXIT_PASS and o.leaks == []
    assert {r["stored_text_digest"] for r in o.report["entries"]} == {"absent"}


@pytest.mark.skipif(os.name != "nt", reason="the Windows owner-only DACL")
def test_the_artifact_is_restricted_to_the_current_user_on_windows(fake):
    fake.write()
    o = fake.run()
    assert o.code == cte.EXIT_PASS
    access = o.report["artifact"]["access"]
    assert access["method"] == "windows-protected-dacl" and access["ace_count"] == 1


# --------------------------------------------------------------------------- #
# Entry refusals (one entry each)
# --------------------------------------------------------------------------- #
ENTRY_FAULTS = {
    "approved-string-true": lambda e: e.__setitem__("approved", "true"),
    "approved-one": lambda e: e.__setitem__("approved", 1),
    "approved-false": lambda e: e.__setitem__("approved", False),
    "approved-missing": lambda e: e.pop("approved"),
    "wrong-wav-hash": lambda e: e.__setitem__("wav_sha256", "0" * 64),
    "wav-hash-missing": lambda e: e.pop("wav_sha256"),
    "text-digest-mismatch": lambda e: e.__setitem__("text_sha256", "f" * 64),
    "text-digest-not-a-string": lambda e: e.__setitem__("text_sha256", 7),
    "text-blank": lambda e: e.__setitem__("text", "   \n\t "),
    "text-empty": lambda e: e.__setitem__("text", ""),
    "text-not-a-string": lambda e: e.__setitem__("text", ["a", "list"]),
    "text-missing": lambda e: e.pop("text"),
    "text-oversized": lambda e: e.__setitem__("text", "x" * (cte.MAX_TRANSCRIPT_CHARS + 1)),
}


@pytest.mark.parametrize("fault", sorted(ENTRY_FAULTS))
@pytest.mark.parametrize("ref_id", ["Female-1", "Male-4"])
def test_a_bad_entry_is_refused_naming_only_its_id(fake, fault, ref_id):
    entry = dict(fake.data[ref_id])
    if fault in ("text-blank", "text-empty", "text-oversized"):
        entry.pop("text_sha256")  # so the text check itself is what refuses
    ENTRY_FAULTS[fault](entry)
    fake.data[ref_id] = entry
    fake.write()
    o = fake.run()
    assert_refused(o, f"entries failed validation: {ref_id}")


def test_an_entry_that_is_not_an_object_is_refused(fake):
    fake.data["Male-2"] = fake.texts["Male-2"]  # a bare string holding a secret
    fake.write()
    assert_refused(fake.run(), "entries failed validation: Male-2")


# --------------------------------------------------------------------------- #
# Store-shape refusals
# --------------------------------------------------------------------------- #
def test_a_missing_reference_id_is_refused(fake):
    del fake.data["Male-3"]
    fake.write()
    o = fake.run()
    assert_refused(o, "exactly the six expected reference IDs")
    assert o.report["store_shape"]["missing_reference_ids"] == ["Male-3"]


def test_an_extra_reference_id_is_refused_and_counted_never_named(fake):
    extra = secret()
    fake.secrets.append(extra)
    fake.data[extra] = fake.entry("Female-1")
    fake.write()
    o = fake.run()
    assert_refused(o, "exactly the six expected reference IDs")
    assert o.report["store_shape"]["unexpected_key_count"] == 1


def test_a_duplicate_key_is_refused(fake):
    body = json.dumps(fake.data, indent=2)
    duplicate = json.dumps({"text": fake.texts["Female-1"] + " again", "approved": True,
                            "wav_sha256": fake.wav_hash("Female-1")})
    fake.write(body[:-2] + f',\n  "Female-1": {duplicate}\n}}')
    assert_refused(fake.run(), "duplicate key")


@pytest.mark.parametrize("raw", ["[]", '"just a string"', "{not json", "\ufeff{}"])
def test_a_store_that_is_not_a_json_object_is_refused(fake, raw):
    fake.write(raw)
    o = fake.run()
    assert o.code == cte.EXIT_REFUSED and fake.artifacts() == [] and o.leaks == []


def test_a_store_that_is_not_utf8_is_refused(fake):
    fake.write()
    fake.store.write_bytes(b"\xff\xfe" + json.dumps(fake.data).encode("utf-16-le"))
    assert_refused(fake.run(), "not valid UTF-8 JSON")


def test_an_oversized_store_is_refused_before_it_is_read(fake):
    fake.write(json.dumps(fake.data) + " " * cte.MAX_STORE_BYTES)
    assert_refused(fake.run(), "larger than any six-entry store")


# --------------------------------------------------------------------------- #
# The recordings
# --------------------------------------------------------------------------- #
def test_a_recording_with_the_wrong_bytes_is_refused(fake):
    fake.write()
    (fake.root / cte.REFS_REL / "Chatterbox - Male 1.wav").write_bytes(b"not the registered recording")
    o = fake.run()
    assert_refused(o, "do not match their registered hash")
    row = next(r for r in o.report["recordings"] if r["reference_id"] == "Male-1")
    assert row["matches"] is False


def test_a_missing_recording_is_refused(fake):
    fake.write()
    (fake.root / cte.REFS_REL / "Chatterbox - Female 2.wav").unlink()
    assert_refused(fake.run(), "do not match their registered hash")


def test_a_recording_only_at_the_pre_v070_path_is_not_used(fake):
    fake.write()
    canonical = fake.root / cte.REFS_REL / "Chatterbox - Male 4.wav"
    legacy = fake.root / "files" / "Chatterbox-Voice-Uploads"
    legacy.mkdir()
    (legacy / canonical.name).write_bytes(canonical.read_bytes())
    canonical.unlink()
    assert_refused(fake.run(), "do not match their registered hash")


# --------------------------------------------------------------------------- #
# Male-4 prefix and the review-pending mode
# --------------------------------------------------------------------------- #
def _drop_male4_prefix(fake: Fake) -> None:
    fake.texts["Male-4"] = fake.texts["Male-4"].removeprefix(cte.MALE4_PREFIX + " ")
    fake.data["Male-4"] = fake.entry("Male-4")


def test_final_mode_refuses_a_male4_text_without_the_required_opening(fake):
    _drop_male4_prefix(fake)
    fake.write()
    o = fake.run()
    assert_refused(o, "entries failed validation: Male-4")
    assert o.report["male4_prefix_ok"] is False


def test_review_pending_flags_the_male4_opening_and_never_reports_pass(fake):
    _drop_male4_prefix(fake)
    fake.write()
    o = fake.run(mode=cte.MODE_REVIEW_PENDING)
    assert o.code == cte.EXIT_REVIEW_PENDING and o.report["result"] == "REVIEW_PENDING"
    assert o.leaks == [] and o.source_same and not _has_key(o.report, "text")
    assert o.report["owner_correction_required"] == ["Male-4"]
    (artifact,) = fake.artifacts()
    assert artifact.name == cte.PENDING_ARTIFACT_NAME and artifact.parent.name.endswith("-review-pending")
    doc = json.loads(artifact.read_text(encoding="utf-8"))
    assert doc["kind"] == cte.PENDING_KIND and doc["approval"] == "UNAPPROVED - NOT FOR SYNTHESIS"
    status = {e["reference_id"]: e["review_status"] for e in doc["entries"]}
    assert status == {**{i: cte.REVIEW_REQUIRED for i in IDS}, "Male-4": cte.CORRECTION_REQUIRED}
    # The original text verbatim: nothing is prepended to "fix" it.
    assert {e["reference_id"]: e["text"] for e in doc["entries"]} == fake.texts
    assert o.report["artifact"]["approved_for_synthesis"] is False and o.report["artifact"]["access"]["owner_only"]


def test_review_pending_still_refuses_every_other_fault(fake):
    fake.data["Female-2"]["approved"] = "true"
    fake.write()
    assert_refused(fake.run(mode=cte.MODE_REVIEW_PENDING), "entries failed validation: Female-2")


# --------------------------------------------------------------------------- #
# Manifest and path hazards
# --------------------------------------------------------------------------- #
def test_a_manifest_outside_the_repository_is_refused(fake, tmp_path):
    fake.write()
    outside = tmp_path / f"preservation-{TAG}.json"
    outside.write_text(json.dumps(fake.manifest), encoding="utf-8")
    assert_refused(fake.run(manifest=str(outside)), "outside the repository")
    assert_refused(fake.run(manifest=f"../preservation-{TAG}.json"), "outside the repository")


def test_a_manifest_with_an_unexpected_file_name_is_refused(fake):
    fake.write()
    renamed = fake.root / "files" / "dev-work" / "manual-fresh-install" / "manifest.json"
    renamed.write_text(json.dumps(fake.manifest), encoding="utf-8")
    assert_refused(fake.run(manifest="files/dev-work/manual-fresh-install/manifest.json"), "preservation-<tag>.json")


@pytest.mark.parametrize("field, value, message", [
    ("Tag", "20990101-000000-00000000", "tag or state"),
    ("State", "Restored", "tag or state"),
    ("Repository", "C:/somewhere/else", "repository does not match"),
    ("Directories", "not-a-list", "Directories missing"),
])
def test_a_manifest_that_disagrees_with_this_checkout_is_refused(fake, field, value, message):
    fake.manifest[field] = value
    fake.write()
    assert_refused(fake.run(), message)


def test_a_manifest_without_exactly_one_runtime_data_entry_is_refused(fake):
    fake.manifest["Directories"].append(dict(fake.manifest["Directories"][1]))
    fake.write()
    assert_refused(fake.run(), "exactly one files/runtime-data")


def test_a_preserved_directory_without_the_tag_is_refused(fake):
    fake.manifest["Directories"][1]["Preserved"] = str(fake.root / "files" / "runtime-data")
    fake.write()
    assert_refused(fake.run(), "does not carry the tag")


def test_a_preserved_directory_that_is_a_junction_is_refused(fake, tmp_path):
    fake.write()
    real = tmp_path / "elsewhere"
    fake.preserved.rename(real)
    junction(fake.preserved, real)
    o = fake.run()
    assert o.code == cte.EXIT_REFUSED and fake.artifacts() == [] and o.leaks == []
    assert "link or junction" in o.report["failure"] or "outside the repository" in o.report["failure"]


def test_a_review_destination_that_is_a_junction_is_refused(fake, tmp_path):
    fake.write()
    elsewhere = tmp_path / "escape"
    elsewhere.mkdir()
    base = fake.root / cte.REVIEW_BASE_REL
    base.parent.mkdir(parents=True, exist_ok=True)
    junction(base, elsewhere)
    assert_refused(fake.run(), "link or junction")
    assert list(elsewhere.iterdir()) == []


def test_a_review_destination_that_is_not_gitignored_is_refused(fake):
    fake.write()
    (fake.root / ".gitignore").write_text("", encoding="utf-8")
    assert_refused(fake.run(), "not gitignored")


def test_an_existing_run_folder_is_never_overwritten(fake, capsys):
    fake.write()
    stamp = "20990101T000000000000Z"
    run_dir = fake.root / cte.REVIEW_BASE_REL / f"run-{stamp}"
    run_dir.mkdir(parents=True)
    planted = run_dir / cte.ARTIFACT_NAME
    planted.write_bytes(b"the owner's earlier file")
    code = cte.main(fake.argv(), registry=tuple(tuple(r) for r in fake.registry), _stamp=stamp)
    out = capsys.readouterr()
    assert code == cte.EXIT_REFUSED and "already exists" in json.loads(out.out)["failure"]
    assert planted.read_bytes() == b"the owner's earlier file"
    assert not any(s in out.out + out.err for s in fake.secrets)


# --------------------------------------------------------------------------- #
# Source integrity and redaction (in process, to inject faults)
# --------------------------------------------------------------------------- #
def test_a_store_changed_during_the_run_is_refused_and_no_artifact_survives(fake, capsys):
    fake.write()

    def tamper(store: Path) -> None:
        store.write_text(store.read_text(encoding="utf-8") + " ", encoding="utf-8")

    code = cte.main(fake.argv(), registry=tuple(tuple(r) for r in fake.registry), _after_read=tamper)
    out = capsys.readouterr()
    report = json.loads(out.out)
    assert code == cte.EXIT_REFUSED and "changed during extraction" in report["failure"]
    assert fake.artifacts() == [] and report["artifact"] is None
    assert not any(s in out.out + out.err for s in fake.secrets)


def test_an_unexpected_exception_is_reported_by_type_only(fake, capsys, monkeypatch):
    fake.write()
    leaked = fake.secrets[0]

    def explode(*_a, **_k):
        raise RuntimeError(f"boom {leaked} {fake.texts['Female-1']}")

    monkeypatch.setattr(cte, "validate_store", explode)
    code = cte.main(fake.argv(), registry=tuple(tuple(r) for r in fake.registry))
    out = capsys.readouterr()
    report = json.loads(out.out)
    assert code == cte.EXIT_UNEXPECTED and report["failure"] == "unexpected RuntimeError (details withheld)"
    meta = (fake.root / report["metadata_file"]).read_text(encoding="utf-8")
    assert leaked not in out.out + out.err + meta
    assert fake.artifacts() == []


def test_a_failed_access_restriction_removes_the_artifact(fake, capsys, monkeypatch):
    fake.write()

    def refuse(_path):
        raise cte.ExtractError("review artifact: could not restrict access to the owner")

    monkeypatch.setattr(cte, "_restrict_owner_only", refuse)
    code = cte.main(fake.argv(), registry=tuple(tuple(r) for r in fake.registry))
    out = capsys.readouterr()
    assert code == cte.EXIT_REFUSED and "restrict access" in json.loads(out.out)["failure"]
    assert fake.artifacts() == []
    assert list((fake.root / cte.REVIEW_BASE_REL).iterdir()) == [], "the empty run folder was not released"


# --------------------------------------------------------------------------- #
# The tool's own shape
# --------------------------------------------------------------------------- #
def test_the_pinned_registry_equals_the_application_registry():
    from tts import chatterbox_synth as cbx
    from tts import qwen3_runtime as rt
    from tts import voice_registry as vr

    clones = [v for v in rt.QWEN3_VOICES if v.kind == rt.KIND_CLONE]
    app = tuple((v.reference_name, v.voice_id, vr.reference_recording_filename("qwen3", v.voice_id), v.reference_sha256)
                for v in clones)
    assert cte.REGISTRY == app
    assert {row[3] for row in cte.REGISTRY} == {v.source_sha256 for v in cbx.REFERENCE_VOICES.values()}
    assert cte.REFS_REL == "/".join(vr.REFERENCE_DIRECTORY)
    assert cte.MAX_TRANSCRIPT_CHARS == rt.MAX_TRANSCRIPT_CHARS
    assert cte.STORE_SUBPATH == rt.local_transcripts_path().relative_to(rt.runtime_dir().parent).parts


def test_the_tool_imports_only_the_standard_library_and_takes_no_text_arguments():
    tree = ast.parse((DEV_TOOLS / "clone_transcript_extract.py").read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module}
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported - set(sys.stdlib_module_names)
    flags = [node.args[0].value for node in ast.walk(tree)
             if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_argument"]
    assert flags == ["--repo-root", "--manifest", "--mode"]


def test_the_tool_is_tracked_developer_tooling_and_never_shipped():
    from shared import release

    rel = "files/dev-tools/clone_transcript_extract.py"
    assert subprocess.run(["git", "check-ignore", "-q", rel], cwd=REPO_ROOT).returncode == 1
    assert not rel.startswith("scripts/") and rel not in release.REFERENCE_ASSETS


@pytest.mark.parametrize("base_rel, name", [
    (cte.REVIEW_BASE_REL, f"run-x/{cte.ARTIFACT_NAME}"),
    (cte.REVIEW_BASE_REL, f"run-x-review-pending/{cte.PENDING_ARTIFACT_NAME}"),
    (cte.METADATA_BASE_REL, "extraction-x.json"),
])
def test_every_output_location_is_gitignored_in_the_real_repository(base_rel, name):
    """Checked by rule only (``--no-index``); nothing is created in the real checkout."""
    done = subprocess.run(["git", "check-ignore", "--no-index", "-q", "--", f"{base_rel}/{name}"], cwd=REPO_ROOT)
    assert done.returncode == 0
