"""Privacy and no-follow containment before evidence (v0.8.2 Phase 1A-1 R3, correction group R3-04; review finding C2).

Every control here builds a throwaway Git repository under ``tmp_path`` and plants only inert sentinel text
(``INERT_PRIVATE_SENTINEL``); no owner-private file of this checkout is read, untracked or deleted. The one real-checkout
read is the sealed status of an existing gate run, read back unchanged.

What is pinned:

* an unavailable, malformed or incomplete local-only policy stops the fingerprint, the evidence map, the change set, the
  evidence command and the argv record before Git is asked anything or any byte is read -- a controlled, nameless outcome;
* a tracked local-only path stops capture before Git compares any working file;
* a public-looking path below a junction (into private storage, or out of the checkout) is never read: the fingerprint
  withholds itself, the evidence map and the change set refuse, and nothing beneath a link is named;
* historical maps (a commit's tree, a recorded ``evidence-files.json``) are consumed with private and linked names
  suppressed, the saved record untouched;
* rename similarity never runs over a private side; Git's stderr never escapes into an error; a private argument is never
  logged; equal digests never make an identity current over a privacy problem;
* public look-alike names stay eligible, a sealed historical run still reads back, and blob identities stay Git's own
  (text=auto, CRLF already in the index, binary), with an external clean filter refused rather than run.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from gate_locator import GATE_DIR, GATE_PATH, REPO_ROOT, load_gate

sys.path.insert(0, str(GATE_DIR))
from helpers import evidence_ledger, git_changes, repo_files, runstore  # noqa: E402

SENTINEL = "INERT_PRIVATE_SENTINEL"
#: The shape of the real policy's ``changed.local_only`` (entries only; nothing here reads the real paths).
LOCAL_ONLY = [".ai/", "AI-WORKSPACE.md", "AGENTS.md", "CLAUDE.md", ".claude/", "scripts/project-status.py", "files/run-temp/"]
ENV = {"python": "3.12.15", "executable": "python.exe"}


# --------------------------------------------------------------------------- #
#  Disposable fixtures (plain helpers, so every control takes only tmp_path and monkeypatch)
# --------------------------------------------------------------------------- #
def git(root: Path, *args: str, data: bytes | None = None) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=ACT test", "-c", "user.email=act-test@example.invalid", "-c", "commit.gpgsign=false",
         "-c", "core.autocrlf=false", *args], cwd=root, check=True, capture_output=True, input=data)
    return done.stdout.decode("utf-8", "replace")


def make_repo(tmp_path: Path, name: str = "repo") -> Path:
    root = (tmp_path / name).resolve()
    (root / "scripts").mkdir(parents=True)
    (root / "files" / "tests").mkdir(parents=True)
    (root / "scripts" / "app.py").write_text("A = 1\n", encoding="utf-8")
    (root / "files" / "tests" / "test_app.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    (root / "README.md").write_text("readme\n", encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fixture")
    return root


def private_file(root: Path, text: str = "first inert payload", suffix: str = ".txt") -> Path:
    (root / ".ai").mkdir(exist_ok=True)
    path = root / ".ai" / f"{SENTINEL}{suffix}"
    path.write_text(text, encoding="utf-8")
    return path


def link_dir(target: Path, link: Path) -> None:
    """A directory link that needs no privilege: a junction on Windows, a symlink elsewhere."""
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def track_without_reading(root: Path, name: str, data: bytes = b"public-looking bytes\n") -> None:
    """An index entry at ``name`` made from bytes on stdin: Git never opens ``name`` (it may lie through a link)."""
    blob = git(root, "hash-object", "-w", "--stdin", data=data).strip()
    git(root, "update-index", "--add", "--cacheinfo", f"100644,{blob},{name}")


def plain_hash(root: Path, name: str) -> str:
    """Git's own blob id for the working file, under the same configuration the evidence map runs with."""
    return subprocess.run(["git", "hash-object", "--", name], cwd=root, check=True, capture_output=True,
                          text=True).stdout.strip()


def record_reads(monkeypatch) -> list[str]:
    """Every content read the fingerprint and the evidence map can make: the no-follow inventory and the old direct hash."""
    reads: list[str] = []
    real_inventory, real_hash = repo_files.Inventory.read_bytes, runstore.sha256_file
    monkeypatch.setattr(repo_files.Inventory, "read_bytes",
                        lambda self, text: (reads.append(str(text)), real_inventory(self, text))[1])
    monkeypatch.setattr(runstore, "sha256_file", lambda path: (reads.append(str(path)), real_hash(path))[1])
    return reads


def record_git(monkeypatch, module, name: str = "_git") -> list[tuple]:
    calls: list[tuple] = []
    real = getattr(module, name)
    monkeypatch.setattr(module, name, lambda root, *args, **kwargs: (calls.append(args), real(root, *args, **kwargs))[1])
    return calls


def gate():
    return load_gate("act_r3_privacy")


# --------------------------------------------------------------------------- #
#  8.1 An unavailable policy stops everything before Git or any read
# --------------------------------------------------------------------------- #
def test_r3_an_unavailable_policy_stops_before_git_or_any_read_with_a_controlled_outcome(tmp_path, monkeypatch, capsys):
    module = gate()
    root = make_repo(tmp_path)
    private = private_file(root)
    git(root, "add", "-f", "--", f".ai/{SENTINEL}.txt")
    calls, reads = record_git(monkeypatch, module), record_reads(monkeypatch)
    monkeypatch.setattr(module, "load_policy", lambda path=None: (_ for _ in ()).throw(module.PolicyError("unavailable")))
    first = module.tree_fingerprint(root)
    private.write_text("second inert payload", encoding="utf-8")
    second = module.tree_fingerprint(root)
    assert first == second and calls == [] and reads == [], (calls, reads)
    assert (first["available"], first["privacy"], first["sha256"], first["private_tracked"]) == (False, "unavailable", None, None)
    assert SENTINEL not in json.dumps(first)
    # A malformed declaration is unavailable too, never "nothing is private".
    for malformed in (".ai/", [None], [""], 7):
        found = module.tree_fingerprint(root, local_only=malformed)
        assert (found["available"], found["privacy"], found["sha256"]) == (False, "unavailable", None), malformed
    assert calls == [] and reads == []
    # The other readers refuse the same way, before Git.
    ledger_calls, change_calls = record_git(monkeypatch, evidence_ledger), record_git(monkeypatch, git_changes)
    for read in (lambda: evidence_ledger.blob_map(root, local_only=None),
                 lambda: git_changes.collect(root, local_only=None),
                 lambda: evidence_ledger.load_runs(root, [tmp_path], local_only=None)):
        with pytest.raises(git_changes.PrivacyViolation) as stopped:
            read()
        assert SENTINEL not in str(stopped.value)
    assert ledger_calls == [] and change_calls == [] and reads == []
    # Nothing can be told apart, so every argument is withheld from the record; only the count stays.
    monkeypatch.setattr(module, "_local_only", lambda: None)
    shown = module.redact_argv(["--mode", "focused", "--test", f".ai/{SENTINEL}.py"])
    assert SENTINEL not in json.dumps(shown) and len(shown) == 1 and "4 argument(s) withheld" in shown[0]


def test_r3_an_incomplete_policy_file_is_unusable_and_the_evidence_command_blocks_without_a_traceback(tmp_path, monkeypatch,
                                                                                                    capsys):
    module = gate()
    policy = json.loads((GATE_DIR / "verification.json").read_text(encoding="utf-8"))
    del policy["changed"]["local_only"]
    incomplete = tmp_path / "verification.json"
    incomplete.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(module.PolicyError, match="local_only"):
        module.load_policy(incomplete)
    policy["changed"]["local_only"] = ".ai/"  # a bare string is not a list of entries
    incomplete.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(module.PolicyError, match="local_only"):
        module.load_policy(incomplete)
    monkeypatch.setattr(module, "POLICY_FILE", incomplete)
    assert module._local_only() is None
    ledger_calls = record_git(monkeypatch, evidence_ledger)
    code = module._evidence_command(types.SimpleNamespace(evidence_root=None, test=None, journey=None, scenario=None))
    assert code == runstore.EXIT_BLOCKED and "EVIDENCE: BLOCKED" in capsys.readouterr().out
    assert ledger_calls == []


# --------------------------------------------------------------------------- #
#  A tracked private path stops capture
# --------------------------------------------------------------------------- #
def test_r3_an_already_tracked_private_path_stops_capture_before_status_or_any_read(tmp_path, monkeypatch):
    module = gate()
    root = make_repo(tmp_path)
    private_file(root)
    git(root, "add", "-f", "--", f".ai/{SENTINEL}.txt")
    (root / "scripts" / "app.py").write_text("A = 2\n", encoding="utf-8")
    calls, reads = record_git(monkeypatch, module), record_reads(monkeypatch)
    found = module.tree_fingerprint(root, local_only=LOCAL_ONLY)
    assert (found["available"], found["privacy"], found["private_tracked"], found["sha256"]) == (True, "violation", 1, None)
    assert [args[0] for args in calls] == ["ls-files"], calls  # names only: no status, no other listing
    assert reads == [] and SENTINEL not in json.dumps(found)
    assert runstore.compare_identity(found, found, ENV, ENV)[0] != "exact"


# --------------------------------------------------------------------------- #
#  8.2 / 8.3 No-follow: a public-looking path through a junction is never read
# --------------------------------------------------------------------------- #
def test_r3_a_public_looking_junction_into_private_storage_is_never_read(tmp_path, monkeypatch):
    module = gate()
    root = make_repo(tmp_path)
    private = private_file(root)
    link_dir(root / ".ai", root / "scripts" / "public")
    name = f"scripts/public/{SENTINEL}.txt"
    track_without_reading(root, name)
    reads = record_reads(monkeypatch)
    first = module.tree_fingerprint(root, local_only=LOCAL_ONLY)
    private.write_text("second inert payload", encoding="utf-8")
    second = module.tree_fingerprint(root, local_only=LOCAL_ONLY)
    assert first == second and (first["privacy"], first["sha256"], first["linked_paths"]) == ("linked", None, 1), first
    assert SENTINEL not in json.dumps(first)
    for read in (lambda: evidence_ledger.blob_map(root, local_only=LOCAL_ONLY),
                 lambda: git_changes.collect(root, local_only=LOCAL_ONLY)):
        with pytest.raises(git_changes.LinkedPath) as stopped:
            read()
        assert SENTINEL not in str(stopped.value)
    assert not any(SENTINEL in path for path in reads), reads
    assert runstore.compare_identity(first, first, ENV, ENV)[0] != "exact"


@pytest.mark.parametrize("tracked", [False, True], ids=["untracked-in-scope", "tracked"])
def test_r3_a_public_looking_junction_out_of_the_repository_is_never_read(tmp_path, monkeypatch, tracked):
    module = gate()
    root = make_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / f"{SENTINEL}.txt").write_text("outside one\n", encoding="utf-8")
    link_dir(outside, root / "files" / "tests" / "ext")
    if tracked:
        track_without_reading(root, f"files/tests/ext/{SENTINEL}.txt")
    reads = record_reads(monkeypatch)
    first = module.tree_fingerprint(root, local_only=LOCAL_ONLY)
    (outside / f"{SENTINEL}.txt").write_text("outside two\n", encoding="utf-8")
    second = module.tree_fingerprint(root, local_only=LOCAL_ONLY)
    assert first == second and (first["privacy"], first["sha256"]) == ("linked", None), first
    assert SENTINEL not in json.dumps(first)
    with pytest.raises(git_changes.LinkedPath) as stopped:
        evidence_ledger.blob_map(root, local_only=LOCAL_ONLY)
    assert SENTINEL not in str(stopped.value)
    assert not any(SENTINEL in path for path in reads), reads


def test_r3_the_evidence_map_rejects_linked_ancestors_and_the_change_set_names_only_the_link(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    private_file(root)
    link_dir(root / ".ai", root / "scripts" / "pub")  # untracked, in the evidence scopes
    reads = record_reads(monkeypatch)
    with pytest.raises(git_changes.LinkedPath) as stopped:
        evidence_ledger.blob_map(root, local_only=LOCAL_ONLY)
    assert SENTINEL not in str(stopped.value)
    changes = git_changes.collect(root, local_only=LOCAL_ONLY)
    git_changes.candidate_identity(root, changes, "policy")
    assert "scripts/pub" in changes.paths() and SENTINEL not in json.dumps(changes.record()), changes.record()
    assert any("link or reparse point" in problem for problem in changes.problems), changes.problems
    assert not any(SENTINEL in path for path in reads), reads


# --------------------------------------------------------------------------- #
#  8.4 Historical maps are filtered as they are consumed
# --------------------------------------------------------------------------- #
def test_r3_historical_private_and_linked_names_are_never_exported_and_the_record_is_untouched(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    private_file(root)
    git(root, "add", "-f", "--", f".ai/{SENTINEL}.txt")
    git(root, "commit", "-q", "-m", "a mistake")
    then = git(root, "rev-parse", "HEAD").strip()
    git(root, "rm", "-q", "--cached", "--", f".ai/{SENTINEL}.txt")
    git(root, "commit", "-q", "-m", "untracked again")
    history = evidence_ledger.blob_map_at(root, then, local_only=LOCAL_ONLY)
    assert "scripts/app.py" in history and SENTINEL not in json.dumps(history), history
    # A tree path that today lies through a junction into private storage is suppressed as well.
    link_dir(root / ".ai", root / "scripts" / "public")
    track_without_reading(root, f"scripts/public/{SENTINEL}.txt")
    tree = git(root, "write-tree").strip()
    assert SENTINEL not in json.dumps(evidence_ledger.blob_map_at(root, tree, local_only=LOCAL_ONLY))
    git(root, "update-index", "--force-remove", "--", f"scripts/public/{SENTINEL}.txt")  # metadata only
    # A recorded run's file map: read, filtered, never rewritten.
    folder = tmp_path / "outputs" / "2026-01-01_000000_focused_aaaa"
    folder.mkdir(parents=True)
    (folder / "results.json").write_text(json.dumps({"run_id": folder.name, "status": "PASS", "started_at": "2026-01-01",
                                                     "environment": ENV}), encoding="utf-8")
    (folder / "start.json").write_text(json.dumps({"identity": {"head": then}}), encoding="utf-8")
    saved = json.dumps({"scripts/app.py": "a" * 40, f".ai/{SENTINEL}.txt": "b" * 40}).encode("utf-8")
    (folder / evidence_ledger.FILES_NAME).write_bytes(saved)
    monkeypatch.setattr(evidence_ledger, "admissible", lambda path: (True, ""))
    runs, _skipped = evidence_ledger.load_runs(root, [tmp_path / "outputs"], local_only=LOCAL_ONLY)
    assert [run.run_id for run in runs] == [folder.name] and runs[0].files == {"scripts/app.py": "a" * 40}
    assert (folder / evidence_ledger.FILES_NAME).read_bytes() == saved
    assert evidence_ledger.changed_between(runs[0].files, {"scripts/app.py": "c" * 40}) == ["scripts/app.py"]


# --------------------------------------------------------------------------- #
#  8.5 Rename similarity never runs over a private side
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("direction", ["out-of-private", "into-private"])
def test_r3_rename_detection_never_reads_an_unchecked_private_side(tmp_path, monkeypatch, direction):
    root = make_repo(tmp_path)
    if direction == "out-of-private":
        private_file(root, suffix=".md")
        git(root, "add", "-f", "--", f".ai/{SENTINEL}.md")
        git(root, "commit", "-q", "-m", "a mistake")
        git(root, "mv", f".ai/{SENTINEL}.md", "docs-plan.md")
        public, status = "docs-plan.md", "A"
    else:
        (root / ".ai").mkdir()
        git(root, "mv", "-f", "scripts/app.py", f".ai/{SENTINEL}.py")
        public, status = "scripts/app.py", "D"
    calls = record_git(monkeypatch, git_changes)
    changes = git_changes.collect(root, local_only=LOCAL_ONLY)
    assert not any("--find-renames" in args for args in calls), calls
    found = {change.path: change.status for change in changes.changes}
    assert found.get(public) == status and changes.violations, changes.record()
    assert SENTINEL not in json.dumps(changes.record())


def test_r3_rename_detection_still_runs_when_every_side_is_public(tmp_path, monkeypatch):
    module = gate()
    root = make_repo(tmp_path)
    git(root, "mv", "scripts/app.py", "scripts/renamed.py")
    calls = record_git(monkeypatch, git_changes)
    found = {change.path: (change.status, change.old_path) for change in git_changes.collect(root, local_only=LOCAL_ONLY).changes}
    assert found["scripts/renamed.py"] == ("R", "scripts/app.py") and any("--find-renames" in args for args in calls)
    status_calls = record_git(monkeypatch, module)
    assert module.tree_fingerprint(root, local_only=LOCAL_ONLY)["privacy"] == "ok"
    assert all("--no-renames" in args for args in status_calls if args[0] == "status") and \
        any(args[0] == "status" for args in status_calls)


# --------------------------------------------------------------------------- #
#  8.6 Diagnostics, argv and current claims
# --------------------------------------------------------------------------- #
def test_r3_injected_private_git_stderr_never_escapes_an_error(tmp_path, monkeypatch):
    module = gate()
    said = f"fatal: bad object .ai/{SENTINEL}.txt"

    def fake_run(*args, **kwargs):
        text = kwargs.get("text") or kwargs.get("encoding")
        return types.SimpleNamespace(returncode=128, stdout="" if text else b"", stderr=said if text else said.encode())

    with monkeypatch.context() as patched:
        patched.setattr(git_changes.subprocess, "run", fake_run)
        with pytest.raises(git_changes.ChangeError) as changes_error:
            git_changes._git(tmp_path, "ls-files", "-z")
        with pytest.raises(RuntimeError) as ledger_error:
            evidence_ledger._git(tmp_path, "ls-files", "-z")
    for raised in (changes_error, ledger_error):
        assert SENTINEL not in str(raised.value) and "bad object" in str(raised.value), raised.value

    def failing(root, *args):
        raise subprocess.CalledProcessError(128, ["git", *args, f".ai/{SENTINEL}.txt"], stderr=said.encode())

    monkeypatch.setattr(module, "_git", failing)
    found = module.tree_fingerprint(make_repo(tmp_path), local_only=LOCAL_ONLY)
    assert found["available"] is False and found["error"] and SENTINEL not in json.dumps(found)


def test_r3_a_raw_private_argument_is_never_logged_or_recorded(tmp_path, monkeypatch):
    module = gate()
    monkeypatch.setattr(module, "_local_only", lambda: list(LOCAL_ONLY))
    directory = tmp_path / "run"
    directory.mkdir()
    monkeypatch.setattr(module.runstore, "reserve_run_dir", lambda *args, **kwargs: directory)
    seen = {}

    class Run:
        started_at, current_gate, lifecycle = "2026-01-01", "preflight", "started"

        def __init__(self, args, argv, record, established, plan, plan_error):
            seen["argv"] = list(argv)

        def mark(self):
            pass

        def execute(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(module, "GateRun", Run)
    absolute = module.REPO_ROOT / ".ai" / f"{SENTINEL}2.py"
    argv = [str(GATE_PATH), "--mode", "focused", "--test", f".ai/{SENTINEL}.py", f"--test={absolute}",
            "--test", "files/tests/test_public.py", "--label", ".ai-public/notes"]
    code = module._execute_run(types.SimpleNamespace(mode="focused"), argv, {})
    assert code == runstore.EXIT_INTERRUPTED
    logged = (directory / runstore.LOG_NAME).read_text(encoding="utf-8")
    assert SENTINEL not in logged and SENTINEL not in json.dumps(seen["argv"]), (logged, seen)
    assert "files/tests/test_public.py" in logged and ".ai-public/notes" in seen["argv"]
    assert seen["argv"].count(module.WITHHELD_ARGUMENT) == 2
    if not repo_files.probe_case_sensitive(REPO_ROOT):  # a case alias of a private path is still private
        assert module.redact_argv([f".AI/{SENTINEL}.py"], LOCAL_ONLY) == [module.WITHHELD_ARGUMENT]


def test_r3_equal_digests_never_make_an_identity_current_over_a_privacy_problem():
    sample = {key: "present" for key in (*runstore.EXECUTION_DIGESTS, "docs_digest")}
    assert runstore.compare_identity(sample, dict(sample), ENV, ENV) == ("exact", [])  # the control
    for problem in ({"private_tracked": 1}, {"privacy": "linked"}, {"privacy": "unavailable"}, {"available": False}):
        for recorded, current in (({**sample, **problem}, sample), (sample, {**sample, **problem})):
            outcome, why = runstore.compare_identity(recorded, current, ENV, ENV)
            assert outcome != "exact" and any(item.startswith("privacy:") for item in why), (problem, outcome, why)


# --------------------------------------------------------------------------- #
#  What must keep working
# --------------------------------------------------------------------------- #
def test_r3_public_prefix_lookalikes_of_local_only_entries_stay_eligible(tmp_path, monkeypatch):
    module = gate()
    root = make_repo(tmp_path)
    lookalikes = [".ai-public/notes.txt", ".aiX/notes.txt", "AGENTS.md.txt", "scripts/project-status.py.txt",
                  "files/run-temporary/notes.txt"]
    for name in lookalikes:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("public\n", encoding="utf-8")
    git(root, "add", "--", *lookalikes)
    git(root, "commit", "-q", "-m", "look-alikes")
    for name in lookalikes:
        (root / name).write_text("public, changed\n", encoding="utf-8")
    found = module.tree_fingerprint(root, local_only=LOCAL_ONLY)
    assert (found["privacy"], found["private_tracked"], found["tracked_files"]) == ("ok", 0, 3 + len(lookalikes))
    assert found["sha256"] and all(any(line.endswith(name) for line in found["dirty_tracked"]) for name in lookalikes)
    mapped = evidence_ledger.blob_map(root, local_only=LOCAL_ONLY)
    assert all(mapped[name] == plain_hash(root, name) for name in lookalikes)
    assert set(lookalikes) <= set(git_changes.collect(root, local_only=LOCAL_ONLY).paths())
    assert module.redact_argv(["--test", *lookalikes], LOCAL_ONLY) == ["--test", *lookalikes]


def test_r3_a_sealed_historical_run_still_reads_back_and_its_own_identity_is_current():
    folder = next((GATE_DIR / "outputs").glob("*_e12e"), None)
    if folder is None:
        pytest.skip("the sealed e12e run is not in this checkout's outputs")
    before = sorted((path.relative_to(folder).as_posix(), path.stat().st_size, path.stat().st_mtime_ns)
                    for path in folder.rglob("*") if path.is_file())
    outcome = runstore.read_run_status(folder)
    assert outcome["valid"] and outcome["status"] in runstore.RESULTS, outcome["problems"]
    results = outcome["results"]
    recorded = results["identity"]["start"]
    assert runstore.read_run_status(folder, recorded, results["environment"])["current"] == "exact"
    violated = runstore.read_run_status(folder, {**recorded, "private_tracked": 1}, results["environment"])
    assert violated["valid"] and violated["current"] == "stale" and violated["status"] == outcome["status"]
    assert sorted((path.relative_to(folder).as_posix(), path.stat().st_size, path.stat().st_mtime_ns)
                  for path in folder.rglob("*") if path.is_file()) == before


def test_r3_blob_identities_stay_gits_own_and_raw_bytes_stay_distinct(tmp_path):
    module = gate()
    root = (tmp_path / "blobs").resolve()
    (root / "files" / "tests").mkdir(parents=True)
    (root / "crlf-in-index.txt").write_bytes(b"x\r\ny\r\n")  # committed before any attribute: CRLF stays in the index
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "crlf in the index")
    (root / ".gitattributes").write_bytes(b"* text=auto\n*.bin binary\n")
    (root / "lf.txt").write_bytes(b"a\nb\n")
    (root / "crlf.txt").write_bytes(b"a\r\nb\r\n")
    (root / "data.bin").write_bytes(b"\x00\x01\r\n\xff")
    git(root, "add", "--", ".gitattributes", "lf.txt", "crlf.txt", "data.bin")
    git(root, "commit", "-q", "-m", "attributes")
    (root / "lf.txt").write_bytes(b"a\r\nb\r\nc\r\n")
    (root / "crlf-in-index.txt").write_bytes(b"x\r\ny\r\nz\r\n")
    (root / "data.bin").write_bytes(b"\x00\x02\r\n\xfe")
    (root / "files" / "tests" / "test_new.py").write_bytes(b"def test_n():\r\n    pass\r\n")
    mapped = evidence_ledger.blob_map(root, local_only=LOCAL_ONLY)
    for name in ("lf.txt", "crlf.txt", "crlf-in-index.txt", "data.bin", "files/tests/test_new.py", ".gitattributes"):
        assert mapped[name] == plain_hash(root, name), name
    # The raw fingerprint sees bytes; the Git identity sees the clean-converted blob.
    first = module.tree_fingerprint(root, local_only=LOCAL_ONLY)
    (root / "crlf.txt").write_bytes(b"a\nb\n")
    second = module.tree_fingerprint(root, local_only=LOCAL_ONLY)
    assert first["sha256"] != second["sha256"]
    assert evidence_ledger.blob_map(root, local_only=LOCAL_ONLY)["crlf.txt"] == mapped["crlf.txt"]


def test_r3_an_external_clean_filter_is_refused_rather_than_run(tmp_path, monkeypatch):
    root = make_repo(tmp_path)
    (root / ".gitattributes").write_text("*.flt filter=inert\n", encoding="utf-8")
    (root / "files" / "tests" / f"{SENTINEL}.flt").write_text("filtered\n", encoding="utf-8")
    started: list[list[str]] = []
    real = evidence_ledger.subprocess.run
    monkeypatch.setattr(evidence_ledger.subprocess, "run",
                        lambda argv, *args, **kwargs: (started.append(list(argv)), real(argv, *args, **kwargs))[1])
    with pytest.raises(RuntimeError, match="clean filter") as stopped:
        evidence_ledger.blob_map(root, local_only=LOCAL_ONLY)
    assert SENTINEL not in str(stopped.value)
    assert not any("hash-object" in argv for argv in started), started
