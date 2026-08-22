"""The permanent repository contract: exact documentation names and the config gate.

The four canonical documents in ``md-instructions/`` must keep their exact names
and casing forever, and no case-variant alias may reappear. This suite proves
that with **real directory entries**, never ``Path.exists()`` — on Windows a
path lookup is case-insensitive, so ``md-instructions/CHANGELOG.md`` "exists"
even though the file is ``Changelog.md``. That is precisely how a stale
reference survived unnoticed in ``scripts/verify.py``.

Because a case-insensitive filesystem will not let us stage a real alias beside
the canonical file, the negative cases run against temporary trees through the
gate's injectable parameters.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MD_DIR = REPO_ROOT / "md-instructions"
PROTECTED_DIR = MD_DIR / "don't-delete"

CANONICAL_DOCS = ("Briefing.md", "Changelog.md", "Decisions.md", "Handoff.md")
FORBIDDEN_ALIASES = (
    "CHANGELOG.md",
    "DECISIONS.md",
    "handoff.md",
    "BRIEFING.md",
    "changelog.md",
    "decisions.md",
    "briefing.md",
)
PROTECTED_REFERENCES = (
    "Audiobook-Creation-Tool-v0.6.x-Approved-Plan-Series-Map.md",
    "Audiobook-Creation-Tool-v0.6.x-Decision-Register-1-55.md",
    "Audiobook-Creation-Tool-v0.6.x-Master-Implementation-Plan-Index.md",
    "Audiobook-Creation-Tool-v0.6.x-Planning-Handoff-2026-07-31.md",
)


def load_verify():
    """Import scripts/verify.py as a module so its checks can be called directly."""
    spec = importlib.util.spec_from_file_location("act_verify", REPO_ROOT / "scripts" / "verify.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["act_verify"] = module
    spec.loader.exec_module(module)
    return module


def build_md_tree(root: Path, doc_names, reference_names=PROTECTED_REFERENCES) -> Path:
    md = root / "md-instructions"
    (md / "don't-delete").mkdir(parents=True)
    for name in doc_names:
        (md / name).write_text("# doc\n", encoding="utf-8")
    for name in reference_names:
        (md / "don't-delete" / name).write_text("# reference\n", encoding="utf-8")
    return md


# --------------------------------------------------------------------------- #
# The live repository
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", CANONICAL_DOCS)
def test_each_canonical_document_exists_under_its_exact_name(name):
    entries = os.listdir(MD_DIR)
    assert name in entries, f"{name} is missing from md-instructions/ (exact-name check)"


@pytest.mark.parametrize("alias", FORBIDDEN_ALIASES)
def test_no_forbidden_case_variant_alias_exists(alias):
    entries = os.listdir(MD_DIR)
    assert alias not in entries, f"{alias} must never be recreated"


def test_no_two_documents_differ_only_by_case():
    entries = [e for e in os.listdir(MD_DIR) if (MD_DIR / e).is_file()]
    lowered = [e.lower() for e in entries]
    duplicates = {e for e in lowered if lowered.count(e) > 1}
    assert not duplicates, f"case-only duplicate documents: {sorted(duplicates)}"


def test_the_exact_name_check_is_genuinely_case_sensitive():
    """Guard the guard: prove exists() would have passed where listdir does not.

    On a case-insensitive filesystem this asserts the two disagree. On a
    case-sensitive one both reject the alias, which is also correct — so the
    test states the invariant that actually matters either way.
    """
    entries = os.listdir(MD_DIR)
    assert "CHANGELOG.md" not in entries
    if (MD_DIR / "CHANGELOG.md").exists():
        # Windows/macOS: the path lookup lies, the directory listing does not.
        assert "Changelog.md" in entries


@pytest.mark.parametrize("name", PROTECTED_REFERENCES)
def test_each_permanent_planning_reference_survives(name):
    assert name in os.listdir(PROTECTED_DIR), f"{name} is protected and must not be removed"


def test_the_protected_directory_itself_exists():
    assert PROTECTED_DIR.is_dir()
    assert "don't-delete" in os.listdir(MD_DIR)


# --------------------------------------------------------------------------- #
# verify.py's own references
# --------------------------------------------------------------------------- #


def test_verify_py_points_at_the_canonical_changelog():
    verify = load_verify()
    assert verify.CHANGELOG.name == "Changelog.md"
    assert verify.BRIEFING.name == "Briefing.md"
    assert verify.CHANGELOG.is_file()


def test_verify_py_holds_no_stale_alias_as_a_real_string_value():
    """Only prose may still name the old spellings — never a string the gate uses.

    Docstrings are excluded deliberately: ``verify.py`` explains *why* the
    case-insensitive lookup was wrong, and that explanation is worth keeping.
    Everything else — constants, path fragments, messages — must be canonical.
    """
    import ast

    tree = ast.parse((REPO_ROOT / "scripts" / "verify.py").read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))

    offending = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and node.value in ("CHANGELOG.md", "DECISIONS.md", "handoff.md")
    ]
    assert not offending, f"verify.py still uses stale document names: {offending}"


def test_verify_py_knows_the_same_contract_this_suite_does():
    verify = load_verify()
    assert verify.CANONICAL_DOCS == CANONICAL_DOCS
    assert set(verify.PROTECTED_REFERENCES) == set(PROTECTED_REFERENCES)


# --------------------------------------------------------------------------- #
# The gate accepts the real tree and rejects broken ones
# --------------------------------------------------------------------------- #


def test_the_gate_passes_against_the_real_repository():
    verify = load_verify()
    name, ok, detail = verify.check_doc_names()
    assert ok, detail


def test_the_gate_passes_a_healthy_temporary_tree(tmp_path):
    verify = load_verify()
    md = build_md_tree(tmp_path, CANONICAL_DOCS)
    _name, ok, detail = verify.check_doc_names(md_dir=md)
    assert ok, detail


def test_the_gate_fails_when_a_canonical_document_is_missing(tmp_path):
    verify = load_verify()
    md = build_md_tree(tmp_path, ("Briefing.md", "Changelog.md", "Decisions.md"))
    _name, ok, detail = verify.check_doc_names(md_dir=md)
    assert not ok
    assert "Handoff.md" in detail


def test_the_gate_fails_when_an_alias_replaces_a_canonical_document(tmp_path):
    """The exact case the stale verify.py reference hid: CHANGELOG.md, not Changelog.md."""
    verify = load_verify()
    md = build_md_tree(tmp_path, ("Briefing.md", "CHANGELOG.md", "Decisions.md", "Handoff.md"))
    _name, ok, detail = verify.check_doc_names(md_dir=md)
    assert not ok
    assert "forbidden alias" in detail
    assert "CHANGELOG.md" in detail


@pytest.mark.parametrize("alias", ["handoff.md", "decisions.md", "briefing.md"])
def test_the_gate_fails_for_every_lowercase_alias(tmp_path, alias):
    verify = load_verify()
    canonical = alias[0].upper() + alias[1:]
    names = tuple(n for n in CANONICAL_DOCS if n != canonical) + (alias,)
    md = build_md_tree(tmp_path, names)
    _name, ok, detail = verify.check_doc_names(md_dir=md)
    assert not ok
    assert alias in detail


def test_the_gate_fails_when_a_permanent_reference_is_deleted(tmp_path):
    verify = load_verify()
    md = build_md_tree(tmp_path, CANONICAL_DOCS, reference_names=PROTECTED_REFERENCES[:2])
    _name, ok, detail = verify.check_doc_names(md_dir=md)
    assert not ok
    assert "missing permanent reference" in detail


def test_the_gate_fails_when_the_protected_directory_is_gone(tmp_path):
    verify = load_verify()
    md = tmp_path / "md-instructions"
    md.mkdir(parents=True)
    for name in CANONICAL_DOCS:
        (md / name).write_text("# doc\n", encoding="utf-8")
    _name, ok, detail = verify.check_doc_names(md_dir=md)
    assert not ok
    assert "don't-delete" in detail


# --------------------------------------------------------------------------- #
# The committed configuration is part of the contract
# --------------------------------------------------------------------------- #


def test_the_committed_config_file_exists_at_the_repository_root():
    assert "config.toml" in os.listdir(REPO_ROOT)


def test_config_template_toml_is_not_the_projects_config():
    """The maintainer's unrelated root file must never become config.toml.

    Phase 6 names it in exactly one place — ``maintenance.PROTECTED_RELATIVE``,
    the list of paths a cleanup target may never be or contain. That is the
    opposite of using it, so the file is allowed to appear there and nowhere
    else; the assertions below pin it to that one list.
    """
    verify = load_verify()
    assert verify.CONFIG_FILE.name == "config.toml"
    maintenance_module = REPO_ROOT / "scripts" / "Universal" / "shared" / "maintenance.py"
    for path in (REPO_ROOT / "scripts").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path == maintenance_module:
            continue
        assert "config-template.toml" not in text, path

    from shared import maintenance

    assert "config-template.toml" in maintenance.PROTECTED_RELATIVE
    body = maintenance_module.read_text(encoding="utf-8")
    assert body.count("config-template.toml") == 1, "named once, as protected only"
    assert "tomllib" not in body and "open(" not in body


def test_the_config_gate_passes_against_the_committed_file():
    verify = load_verify()
    _name, ok, detail = verify.check_config()
    assert ok, detail


def test_the_config_gate_fails_an_invalid_committed_file(tmp_path):
    """The runtime tolerates a bad value; the repository gate must not."""
    verify = load_verify()
    root = tmp_path / "repo"
    (root / "scripts" / "Universal").mkdir(parents=True)
    (root / "scripts" / "Universal" / "launcher.py").write_text("#\n", encoding="utf-8")
    bad = root / "config.toml"
    bad.write_text(
        "[project]\n"
        'name = ""\n'
        '[logging]\n'
        "max_sessions = 0\n",
        encoding="utf-8",
    )
    _name, ok, detail = verify.check_config(config_file=bad, repo_root=root)
    assert not ok
    assert "project.name" in detail
    assert "logging.max_sessions" in detail


def test_the_config_gate_fails_a_missing_file(tmp_path):
    verify = load_verify()
    _name, ok, detail = verify.check_config(config_file=tmp_path / "nope.toml", repo_root=tmp_path)
    assert not ok
    assert "missing" in detail


def test_the_config_gate_fails_on_project_version_drift(tmp_path):
    verify = load_verify()
    root = tmp_path / "repo"
    (root / "scripts" / "Universal").mkdir(parents=True)
    (root / "scripts" / "Universal" / "launcher.py").write_text("#\n", encoding="utf-8")
    drifted = root / "config.toml"
    drifted.write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
    _name, ok, detail = verify.check_config(config_file=drifted, repo_root=root)
    assert not ok
    assert "9.9.9" in detail


def test_the_config_gate_fails_malformed_toml(tmp_path):
    verify = load_verify()
    broken = tmp_path / "config.toml"
    broken.write_text("[project\nname = oops", encoding="utf-8")
    _name, ok, detail = verify.check_config(config_file=broken, repo_root=tmp_path)
    assert not ok
    assert "TOML" in detail


# --------------------------------------------------------------------------- #
# Phase 1 stayed inside its scope
# --------------------------------------------------------------------------- #


def test_the_application_version_is_unchanged():
    from shared.version import VERSION

    # v0.6.1 Plan 4 Phase 15 closeout: the bump from 0.5.1 happened here and
    # nowhere else. This guard now pins the approved closeout version.
    assert VERSION == "0.6.1"


def test_the_launcher_carries_no_cleanup_behaviour():
    """Phase 2 added Preferences; actual downloaded-data cleanup is Phase 6.

    This guard moved with the phase boundary rather than being deleted: the
    launcher may now name Preferences, but nothing in it may inventory, spawn,
    schedule or delete anything.
    """
    import ast

    source = (REPO_ROOT / "scripts" / "Universal" / "launcher.py").read_text(encoding="utf-8")
    assert "Preferences" in source, "Phase 2 owns the Preferences entry point"

    tree = ast.parse(source)
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for phase_six in ("clear_downloaded_data", "run_cleanup", "schedule_cleanup",
                      "_cleanup", "delete_assets"):
        assert phase_six not in defined

    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for destructive in ("rmtree", "unlink", "rmdir"):
        assert destructive not in called


def test_phase_one_added_no_output_run_reservation():
    """Run reservation, collision numbering and mirroring belong to Phase 3.

    Phase 1 may only *resolve* the output base; it must not reserve, number,
    create or mirror anything, and ``shared/paths.py`` must be untouched.
    """
    import ast

    src = REPO_ROOT / "scripts" / "Universal" / "shared" / "config.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    defined = {
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for later_phase in ("reserve_run_dir", "next_run_dir", "plan_outputs", "mirror_relative"):
        assert later_phase not in defined

    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    # 'replace' is deliberately absent from this list: str.replace is legitimate.
    for filesystem_write in ("mkdir", "touch", "unlink", "rmtree", "write_text", "write_bytes"):
        assert filesystem_write not in called, "loading configuration must not write to disk"

    # The Phase 3 slug registry stays where it is and is not consumed yet.
    assert "TOOL_SLUGS" not in src.read_text(encoding="utf-8")
