"""The explicit execution plan, changed selection and routine capability classification (v0.8.2 Phase 1A-1).

Pure and synthetic: every plan here is resolved from a small policy and inventory written in the test, every change set
from a throwaway Git repository, every classification from test source written into a temporary tree. Nothing here runs
the gate, a journey, a scenario or a real engine. The gate's own command-line contracts are proved from outside in
``test_verification_gate_contract.py``; this module pins the pieces those runs are built from.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gate_locator import GATE_DIR, REPO_ROOT

sys.path.insert(0, str(GATE_DIR))
from helpers import effects, evidence_ledger, git_changes, selection  # noqa: E402
from helpers import execution_plan as ep  # noqa: E402

GUARD = "files/tests/test_guard.py"
GROUPS = {"heavy": ["test_guarded.py"]}


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=ACT test", "-c", "user.email=act-test@example.invalid", "-c", "commit.gpgsign=false",
         "-c", "core.autocrlf=false", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def passthrough(selectors, explicit):
    return ep.EffectResult(executable=tuple(selectors))


def context(*, policy=None, coverage=None, groups=None, effects_for=passthrough, **extra) -> ep.Context:
    base_policy = {"focused": {"required_guards": [GUARD]}, "changed": {"always": [GUARD]},
                   "quick": {"checks": [{"id": "docnames"}, {"id": "json-validity"}]},
                   "regression": {"components": {"mp3": {"tools": ["mp3-tool"]}, "gate": {"tools": [],
                                                                                          "tests": ["files/tests/test_gate.py"]}}},
                   "acceptance": {"required_scenarios": ["mp3.journey"], "optional_scenarios": ["mp3.optional"]}}
    base_coverage = {"features": [
        {"id": "ACT.MP3.ONE", "tool": "mp3-tool", "selection": ["files/tests/test_mp3.py"], "journeys": ["mp3.journey"],
         "verification": {"all_of": [{"kind": "behavior", "test": "files/tests/test_mp3.py::test_one"},
                                     {"kind": "native", "scenario": "mp3.journey"},
                                     {"kind": "owner", "what": "listen to it"}]}},
        {"id": "ACT.MP3.EMPTY", "tool": "mp3-tool", "selection": [], "verification": {"all_of": []}}]}
    return ep.Context(policy=policy or base_policy, coverage=coverage or base_coverage,
                      groups=dict(GROUPS if groups is None else groups), native_platform="windows", effects_for=effects_for,
                      scenarios={"edge-low-memory": {"runner": "qualification/edge.py", "effects": ["external-network"]},
                                 "fresh-macos": {"runner": "qualification/mac.py"}},
                      scenario_platform={"edge-low-memory": "windows", "fresh-macos": "macos"}, **extra)


def resolve(mode, ctx=None, **selectors) -> ep.ExecutionPlan:
    return ep.resolve(ep.Request(mode=mode, **selectors), ctx or context())


# --------------------------------------------------------------------------- #
#  The representation
# --------------------------------------------------------------------------- #
def test_every_collection_of_a_plan_defaults_to_empty_and_empty_selects_nothing():
    plan = ep.ExecutionPlan(mode="focused", kind="focused", requested=(), native_platform="windows",
                            target_platforms=("windows",))
    for name in ("static_checks", "guards", "scope", "ordinary", "guarded", "journeys", "effects", "obligations", "withheld",
                 "gaps"):
        assert getattr(plan, name) == (), name
    assert plan.scenario is None and plan.release_partition is False and plan.executable_now is False
    assert plan.status == "NOT RUN" and plan.record()["ordinary"] == [] and plan.record()["guarded"] == {}
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.ordinary = ("files/tests",)


def test_only_the_full_constructor_names_the_release_partition():
    full = resolve("full")
    assert full.ordinary == (ep.ORDINARY_PARTITION,) and full.release_partition is True
    assert full.guarded == (("heavy", ("test_guarded.py",)),) and full.journeys == ("mp3.journey", "mp3.optional")
    assert full.executable_now and "owner authorization" in full.activation and "no download" in full.activation
    assert [item.subject for item in full.obligations] == ["scenario:edge-low-memory"], "another platform's scenario is not owed here"
    with pytest.raises(ep.PlanError):
        ep.full_plan(ep.Request(mode="full", tests=("files/tests/test_a.py",)), context())
    with pytest.raises(ep.PlanError):
        ep.full_plan(ep.Request(mode="focused", tests=("files/tests/test_a.py",)), context())
    for mode, selectors in (("focused", {"tests": ("files/tests/test_a.py",)}), ("quick", {}),
                            ("regression", {"components": ("mp3",)}), ("qualification", {"journeys": ("mp3.journey",)})):
        plan = resolve(mode, **selectors)
        assert plan.release_partition is False and ep.ORDINARY_PARTITION not in plan.ordinary, mode


# --------------------------------------------------------------------------- #
#  The six modes
# --------------------------------------------------------------------------- #
def test_quick_is_the_fixed_static_checks_and_executes():
    plan = resolve("quick")
    assert plan.static_checks == ("docnames", "json-validity") and plan.pytest_selectors() == ()
    assert plan.status == "COMPLETE" and plan.executable_now is True and plan.activation == ""
    with pytest.raises(ep.PlanError, match="known static checks"):
        resolve("quick", context(policy={"quick": {"checks": [{"id": "rm -rf"}]}}))


def test_focused_tests_keep_suite_order_drop_duplicates_and_add_the_required_guard():
    plan = resolve("focused", tests=("files/tests/test_b.py", "files/tests/test_a.py::test_x", "files/tests/test_a.py",
                                     "files/tests/test_b.py"))
    assert plan.ordinary == ("files/tests/test_a.py", "files/tests/test_b.py", GUARD)
    assert plan.scope == ("files/tests/test_b.py", "files/tests/test_a.py::test_x", "files/tests/test_a.py")
    assert plan.guards == (GUARD,) and plan.status == "COMPLETE" and plan.executable_now is True
    assert plan.requested == ("test:files/tests/test_b.py", "test:files/tests/test_a.py::test_x", "test:files/tests/test_a.py",
                              "test:files/tests/test_b.py")


def test_a_guarded_module_keeps_its_group_membership():
    plan = resolve("focused", tests=("files/tests/test_guarded.py::test_one", "files/tests/test_a.py"))
    assert plan.ordinary == ("files/tests/test_a.py", GUARD)
    assert plan.guarded == (("heavy", ("test_guarded.py::test_one",)),)


def test_a_focused_feature_runs_its_tests_and_lists_its_journeys_and_owner_checks_as_obligations():
    plan = resolve("focused", features=("ACT.MP3.ONE",))
    assert plan.ordinary == (GUARD, "files/tests/test_mp3.py") and plan.journeys == ()
    owed = {(item.subject, item.kind) for item in plan.obligations}
    assert owed == {("journey:mp3.journey", "native"), ("owner:ACT.MP3.ONE", "owner")}
    assert plan.status == "COMPLETE" and plan.executable_now is True, "focused --feature executes (v0.8.2 simplification)"


def test_a_guard_alone_never_satisfies_requested_work():
    plan = resolve("focused", features=("ACT.MP3.EMPTY",))
    assert plan.scope == () and plan.ordinary == (GUARD,) and plan.status == "INCOMPLETE"
    assert [gap.subject for gap in plan.gaps] == ["feature:ACT.MP3.EMPTY"]

    def withhold(selectors, explicit):
        return ep.EffectResult(withheld=tuple(ep.Entry(s, "declares real-engine", "effect", ("real-engine",), s in explicit)
                                              for s in selectors))

    plan = resolve("focused", context(effects_for=withhold), tests=("files/tests/test_engine.py",))
    assert plan.ordinary == (GUARD,) and plan.scope == () and plan.status == "INCOMPLETE"
    assert plan.withheld[0].requested is True


def test_regression_names_its_components_and_never_all():
    plan = resolve("regression", components=("mp3",))
    assert plan.ordinary == (GUARD, "files/tests/test_mp3.py") and plan.executable_now is True
    assert {item.subject for item in plan.obligations} >= {"journey:mp3.journey"}
    assert resolve("regression", components=("gate",)).ordinary == ("files/tests/test_gate.py", GUARD)
    for components in ((), ("all",), ("no-such",)):
        with pytest.raises(ep.PlanError):
            resolve("regression", components=components)


def test_qualification_takes_one_scenario_or_a_set_of_journeys():
    scenario = resolve("qualification", scenario="edge-low-memory")
    assert scenario.scenario == "edge-low-memory" and scenario.effects == ("external-network",)
    assert scenario.executable_now is True and "owner authorization" in scenario.activation
    assert resolve("qualification", scenario="fresh-macos").status == "BLOCKED", "another platform's scenario"
    journeys = resolve("qualification", journeys=("mp3.optional", "mp3.journey", "mp3.optional"))
    assert journeys.journeys == ("mp3.optional", "mp3.journey") and journeys.executable_now is False
    assert journeys.pytest_selectors() == () and journeys.static_checks == ()
    for bad in ({"journeys": ("nothing.here",)}, {"scenario": "made-up"}, {},
                {"scenario": "edge-low-memory", "journeys": ("mp3.journey",)}):
        with pytest.raises(ep.PlanError):
            resolve("qualification", **bad)


@pytest.mark.parametrize("mode, selectors, needle", [
    ("focused", {"journeys": ("mp3.journey",)}, "--mode qualification --journey"),
    ("focused", {}, "an empty selection is not a test run"),
    ("focused", {"tests": ("",)}, "may not be empty"),
    ("quick", {"tests": ("files/tests/test_a.py",)}, "--test does not go with --mode quick"),
    ("full", {"components": ("mp3",)}, "--component does not go with --mode full"),
    ("full", {"base": "HEAD"}, "--base does not go with --mode full"),
    ("changed", {"features": ("ACT.MP3.ONE",)}, "--feature does not go with --mode changed"),
    ("regression", {"scenario": "edge-low-memory"}, "--scenario does not go with --mode regression"),
    ("everything", {}, "unknown mode"),
])
def test_an_invalid_request_is_refused_with_a_reason(mode, selectors, needle):
    with pytest.raises(ep.PlanError, match=None) as raised:
        ep.check_request(ep.Request(mode=mode, **selectors))
    assert needle in str(raised.value)


def test_a_changed_plan_without_relevant_change_is_not_run_and_runs_no_guard():
    plan = resolve("changed", context(routing=selection.Routing()))
    assert plan.status == "NOT RUN" and plan.ordinary == () and plan.guards == () and plan.executable_now is False


def test_a_changed_test_withheld_as_heavyweight_is_a_gap_not_a_skip():
    def withhold(selectors, explicit):
        heavy = [s for s in selectors if "engine" in s]
        return ep.EffectResult(executable=tuple(s for s in selectors if s not in heavy),
                               withheld=tuple(ep.Entry(s, "declares real-engine", "effect", ("real-engine",)) for s in heavy))

    routing = selection.Routing(relevant=["files/tests/test_engine.py", "files/tests/test_a.py"],
                                tests=["files/tests/test_engine.py", "files/tests/test_a.py"])
    plan = resolve("changed", context(effects_for=withhold, routing=routing))
    assert plan.ordinary == ("files/tests/test_a.py", GUARD) and plan.status == "INCOMPLETE"
    assert [(gap.subject, gap.kind) for gap in plan.gaps] == [("files/tests/test_engine.py", "withheld")]


# --------------------------------------------------------------------------- #
#  The execution-boundary check, with its mutations
# --------------------------------------------------------------------------- #
@pytest.fixture
def valid_plan() -> ep.ExecutionPlan:
    plan = resolve("focused", tests=("files/tests/test_a.py", "files/tests/test_guarded.py"))
    ep.validate(plan, GROUPS)  # the no-change control: a resolved plan passes
    return plan


@pytest.mark.parametrize("change, needle", [
    ({"ordinary": ("files/tests",)}, "release partition"),
    ({"release_partition": True}, "release partition"),
    ({"journeys": ("mp3.journey",)}, "routine modes never start native work"),
    ({"scenario": "edge-low-memory"}, "routine modes never start native work"),
    ({"effects": ("real-engine",)}, "heavyweight effects"),
    ({"ordinary": ("files/tests/test_a.py",)}, "required guard"),
    ({"guarded": (("nobody", ("test_guarded.py",)),)}, "unknown guarded group"),
    ({"guarded": (("heavy", ("test_a.py",)),)}, "is not a module of guarded group"),
    ({"guarded": (("heavy", ()),)}, "with no target"),
    ({"ordinary": ("files/tests/test_a.py", "files/tests/test_a.py", GUARD)}, "listed twice"),
    ({"ordinary": ("files/tests/test_a.py; rm x", GUARD)}, "not a test identity"),
    ({"ordinary": ("-k nothing", GUARD)}, "not a test identity"),
    ({"static_checks": ("format-disk",)}, "unknown static check"),
    ({"mode": "everything"}, "unknown mode"),
])
def test_the_boundary_refuses_a_plan_resolve_could_not_have_made(valid_plan, change, needle):
    mutated = dataclasses.replace(valid_plan, **change)
    with pytest.raises(ep.PlanError) as raised:
        ep.validate(mutated, GROUPS)
    assert needle in str(raised.value)


def test_the_full_plan_cannot_be_narrowed_at_the_boundary():
    full = resolve("full")
    ep.validate(full, GROUPS)
    for change in ({"ordinary": ("files/tests/test_a.py",)}, {"release_partition": False},
                   {"ordinary": (ep.ORDINARY_PARTITION, "files/tests/test_a.py")}):
        with pytest.raises(ep.PlanError):
            ep.validate(dataclasses.replace(full, **change), GROUPS)


def test_split_matches_the_gates_long_standing_ordinary_and_guarded_split():
    ordinary, guarded = ep.split(["files/tests/test_b.py", "files/tests/test_a.py::x", "files/tests/test_a.py",
                                  "files/tests/test_guarded.py::t"], {"test_guarded.py": "heavy"})
    assert ordinary == ["files/tests/test_a.py", "files/tests/test_b.py"]
    assert guarded == (("heavy", ("test_guarded.py::t",)),)


# --------------------------------------------------------------------------- #
#  Changed files, read from Git
# --------------------------------------------------------------------------- #
LOCAL_ONLY = [".ai/", "AGENTS.md", "files/run-temp/"]


@pytest.fixture
def repo(tmp_path) -> Path:
    root = (tmp_path / "r").resolve()
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("A = 1\n", encoding="utf-8")
    (root / "src" / "b.py").write_text("B = 1\n", encoding="utf-8")
    (root / "README.md").write_text("readme\n", encoding="utf-8")
    (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fixture")
    return root


def collect(root, **kwargs) -> git_changes.ChangeSet:
    return git_changes.collect(root, local_only=LOCAL_ONLY, **kwargs)


def by_path(changes) -> dict:
    return {change.path: (change.status, change.old_path, change.sources) for change in changes.changes}


def test_head_is_the_default_anchor_and_every_working_stream_is_seen(repo):
    (repo / "src" / "a.py").write_text("A = 2\n", encoding="utf-8")
    git(repo, "add", "src/a.py")
    (repo / "src" / "b.py").write_text("B = 2\n", encoding="utf-8")
    (repo / "deep" / "er").mkdir(parents=True)
    (repo / "deep" / "er" / "new.txt").write_text("x\n", encoding="utf-8")
    (repo / "ignored").mkdir()
    (repo / "ignored" / "skip.txt").write_text("x\n", encoding="utf-8")
    changes = collect(repo)
    assert changes.base is None and changes.head == git(repo, "rev-parse", "HEAD").strip()
    assert by_path(changes) == {"src/a.py": ("M", None, ("staged",)), "src/b.py": ("M", None, ("unstaged",)),
                                "deep/er/new.txt": ("?", None, ("untracked",))}


def test_a_clean_checkout_after_a_commit_has_no_change(repo):
    (repo / "src" / "a.py").write_text("A = 2\n", encoding="utf-8")
    git(repo, "commit", "-qam", "c")
    assert collect(repo).changes == []


def test_a_base_adds_the_candidate_side_since_the_merge_base_and_never_the_other_side(repo):
    git(repo, "branch", "base")
    (repo / "src" / "a.py").write_text("A = 2\n", encoding="utf-8")
    git(repo, "commit", "-qam", "candidate")
    git(repo, "checkout", "-q", "base")
    (repo / "README.md").write_text("theirs\n", encoding="utf-8")
    git(repo, "commit", "-qam", "theirs")
    git(repo, "checkout", "-q", "main")
    changes = collect(repo, base="base")
    assert by_path(changes) == {"src/a.py": ("M", None, ("committed",))}, "the base's own README change is not ours"
    assert changes.base["ref"] == "base" and changes.base["merge_base"] == git(repo, "rev-parse", "main~1").strip()
    ancestor = collect(repo, base="HEAD~1")
    assert by_path(ancestor) == {"src/a.py": ("M", None, ("committed",))}


@pytest.mark.parametrize("base, needle", [("no-such-ref", "does not name a commit"), ("-x", "is not a revision"),
                                          (" HEAD", "is not a revision")])
def test_an_unknown_or_malformed_base_is_refused(repo, base, needle):
    with pytest.raises(git_changes.ChangeError, match=needle):
        collect(repo, base=base)


def test_an_unrelated_base_is_refused(repo):
    git(repo, "checkout", "-q", "--orphan", "other")
    git(repo, "commit", "-q", "-m", "unrelated", "--allow-empty")
    git(repo, "branch", "-q", "unrelated")
    git(repo, "checkout", "-q", "-f", "main")
    with pytest.raises(git_changes.ChangeError, match="shares no history"):
        collect(repo, base="unrelated")


def test_a_staged_change_reversed_in_the_working_tree_is_still_a_change(repo):
    (repo / "src" / "a.py").write_text("A = 2\n", encoding="utf-8")
    git(repo, "add", "src/a.py")
    (repo / "src" / "a.py").write_text("A = 1\n", encoding="utf-8")
    changes = collect(repo)
    assert by_path(changes)["src/a.py"][2] == ("staged", "unstaged")
    assert any("reversed in the working tree" in note for note in changes.notes)


def test_a_rename_keeps_both_paths_and_a_case_only_rename_too(repo):
    git(repo, "mv", "src/a.py", "src/renamed.py")
    git(repo, "mv", "src/b.py", "src/B.py")
    changes = collect(repo)
    found = by_path(changes)
    assert found["src/renamed.py"][:2] == ("R", "src/a.py") and found["src/B.py"][:2] == ("R", "src/b.py")
    assert set(changes.paths()) == {"src/renamed.py", "src/a.py", "src/B.py", "src/b.py"}


def test_a_staged_delete_recreated_in_the_working_tree_is_seen_from_both_sides(repo):
    git(repo, "rm", "-q", "src/a.py")
    (repo / "src" / "a.py").write_text("A = 3\n", encoding="utf-8")
    status, _old, sources = by_path(collect(repo))["src/a.py"]
    assert status == "D" and sources == ("staged", "untracked")


def test_unresolved_conflicts_are_refused(repo):
    git(repo, "checkout", "-q", "-b", "side")
    (repo / "src" / "a.py").write_text("A = 'side'\n", encoding="utf-8")
    git(repo, "commit", "-qam", "side")
    git(repo, "checkout", "-q", "main")
    (repo / "src" / "a.py").write_text("A = 'main'\n", encoding="utf-8")
    git(repo, "commit", "-qam", "main")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "merge", "-q", "side"], cwd=repo,
                   capture_output=True)
    with pytest.raises(git_changes.ChangeError, match="unresolved conflicts"):
        collect(repo)


def test_local_only_files_are_excluded_by_entry_and_count_and_never_named(repo):
    (repo / ".ai").mkdir()
    (repo / ".ai" / "private-notes.md").write_text("secret\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("private\n", encoding="utf-8")
    (repo / ".aim.txt").write_text("not local-only: a bare prefix never matches\n", encoding="utf-8")
    changes = collect(repo)
    assert by_path(changes) == {".aim.txt": ("?", None, ("untracked",))}
    assert changes.excluded == {".ai/": 1, "AGENTS.md": 1}
    assert "private-notes" not in json.dumps(changes.record())


def test_a_tracked_local_only_path_is_a_violation_and_a_gap(repo):
    (repo / "AGENTS.md").write_text("private\n", encoding="utf-8")
    git(repo, "add", "AGENTS.md")
    changes = collect(repo)
    assert changes.changes == [] and changes.violations and "AGENTS.md" in changes.violations[0]
    routing = selection.route_changes(changes, {}, {}, _index(repo), native_platform="windows", known_journeys=[])
    assert [(gap.subject, gap.kind) for gap in routing.gaps] == [("local-only", "policy-violation")]


def test_the_candidate_identity_binds_the_working_bytes_and_never_follows_a_link(repo):
    (repo / "src" / "a.py").write_text("A = 2\n", encoding="utf-8")
    first = git_changes.candidate_identity(repo, collect(repo), "policy")
    again = git_changes.candidate_identity(repo, collect(repo), "policy")
    assert first == again and first["paths"] == 1 and first["head"]
    (repo / "src" / "a.py").write_text("A = 3\n", encoding="utf-8")
    assert git_changes.candidate_identity(repo, collect(repo), "policy")["working_digest"] != first["working_digest"]
    assert git_changes.candidate_identity(repo, collect(repo), "other")["policy_digest"] == "other"
    target = repo.parent / "outside"
    target.mkdir()
    (target / "x.txt").write_text("outside\n", encoding="utf-8")
    link = repo / "linked"
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))  # a reparse point; needs no privilege
    else:
        link.symlink_to(target, target_is_directory=True)
    changes = collect(repo)
    git_changes.candidate_identity(repo, changes, "policy")
    assert any("link or reparse point" in problem for problem in changes.problems), changes.problems
    routing = selection.route_changes(changes, {}, {}, _index(repo), native_platform="windows", known_journeys=[])
    assert any(gap.kind == "unreadable" for gap in routing.gaps)


def test_the_name_status_parser_reads_nul_records_and_refuses_truncation():
    assert git_changes.parse_name_status("M\0a b.txt\0R100\0old\0new\0D\0gone\0") == [
        ("M", None, "a b.txt"), ("R", "old", "new"), ("D", None, "gone")]
    for text in ("M\0", "R100\0old\0"):
        with pytest.raises(git_changes.ChangeError):
            git_changes.parse_name_status(text)
    assert git_changes.matches("files/run-temp/x", "files/run-temp/") and not git_changes.matches("files/run-tempx", "files/run-temp/")


# --------------------------------------------------------------------------- #
#  Routing through the reverse import closure
# --------------------------------------------------------------------------- #
def _index(root: Path) -> selection.ReverseIndex:
    return selection.ReverseIndex(root, evidence_ledger.Closures(root))


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def code_tree(tmp_path) -> Path:
    root = (tmp_path / "c").resolve()
    write(root, "scripts/tts/__init__.py", "")
    write(root, "scripts/tts/engine.py", "from . import voices\nVALUE = voices.NAMES\n")
    write(root, "scripts/tts/voices.py", "NAMES = ['a']\n")
    write(root, "scripts/shared/util.py", "def helper():\n    return 1\n")
    write(root, "scripts/lonely.py", "X = 1\n")
    write(root, "files/tests/conftest.py", "")
    write(root, "files/tests/test_engine.py", "from tts import engine\n\ndef test_engine():\n    assert engine.VALUE\n")
    write(root, "files/tests/test_util.py", "from shared.util import helper\n\ndef test_util():\n    assert helper()\n")
    write(root, "files/tests/test_other.py", "def test_other():\n    pass\n")
    return root


POLICY = {"changed": {"routes": {".gitignore": ["files/tests/test_other.py"]},
                      "static": {"md-instructions/": ["docnames", "docs"], "config.toml": ["config"]},
                      "obligations": {"Setup.bat": {"kind": "archive", "why": "a launcher: owed to the release archive"}},
                      "suite_wide": {"files/tests/conftest.py": ["files/tests/test_other.py"]},
                      "max_routed_modules": 40}}


def changed(*rows) -> git_changes.ChangeSet:
    return git_changes.ChangeSet(head="h", base=None, changes=[git_changes.Change(path, status, old, ("unstaged",))
                                                               for path, status, old in rows])


def route(root, *rows, policy=POLICY, coverage=None, native="windows") -> selection.Routing:
    return selection.route_changes(changed(*rows), policy, coverage or {}, _index(root), native_platform=native,
                                   known_journeys=[])


def test_a_changed_module_selects_the_tests_that_reach_it_directly_and_through_relative_imports(code_tree):
    routing = route(code_tree, ("scripts/tts/voices.py", "M", None))
    assert routing.tests == ["files/tests/test_engine.py"] and routing.gaps == []
    assert route(code_tree, ("scripts/shared/util.py", "M", None)).tests == ["files/tests/test_util.py"]


def test_the_reverse_index_is_built_once_per_snapshot(code_tree, monkeypatch):
    closures = evidence_ledger.Closures(code_tree)
    calls = []
    original = closures.closure
    monkeypatch.setattr(closures, "closure", lambda entries, **kw: calls.append(entries) or original(entries, **kw))
    index = selection.ReverseIndex(code_tree, closures)
    assert len(calls) == 3
    for path in ("scripts/tts/voices.py", "scripts/shared/util.py", "scripts/tts/engine.py"):
        index.consumers(path)
    assert len(calls) == 3, "a lookup must not rebuild a closure"


def test_a_deleted_or_renamed_away_module_still_finds_its_former_consumers(code_tree):
    (code_tree / "scripts" / "shared" / "util.py").unlink()
    routing = route(code_tree, ("scripts/shared/util.py", "D", None))
    assert routing.tests == ["files/tests/test_util.py"] and routing.gaps == []


def test_a_deleted_test_never_satisfies_itself(code_tree):
    (code_tree / "files" / "tests" / "test_util.py").unlink()
    routing = route(code_tree, ("files/tests/test_util.py", "D", None))
    assert routing.tests == [] and [(gap.subject, gap.kind) for gap in routing.gaps] == [
        ("files/tests/test_util.py", "deleted-test")]
    coverage = {"features": [{"id": "ACT.X.Y", "selection": ["files/tests/test_util.py", "files/tests/test_other.py"]}]}
    survived = route(code_tree, ("files/tests/test_util.py", "D", None), coverage=coverage)
    assert survived.tests == ["files/tests/test_other.py"] and survived.gaps == []


def test_a_parse_error_is_a_gap_never_no_dependencies(code_tree):
    write(code_tree, "scripts/shared/util.py", "def broken(:\n")
    routing = route(code_tree, ("scripts/shared/util.py", "M", None))
    assert ("scripts/shared/util.py", "unparsed") in [(gap.subject, gap.kind) for gap in routing.gaps]
    write(code_tree, "files/tests/test_broken.py", "def test_x(:\n")
    routing = route(code_tree, ("scripts/tts/voices.py", "M", None))
    assert ("files/tests/test_broken.py", "unparsed") in [(gap.subject, gap.kind) for gap in routing.gaps]


def test_an_unreached_source_and_an_unknown_path_are_gaps_and_nothing_widens(code_tree):
    routing = route(code_tree, ("scripts/lonely.py", "M", None), ("some/new/place.bin", "A", None))
    assert routing.tests == [] and {gap.subject for gap in routing.gaps} == {"scripts/lonely.py", "some/new/place.bin"}
    assert all(gap.kind == "unmapped" for gap in routing.gaps)


def test_documents_configuration_and_launchers_route_to_static_checks_and_obligations(code_tree):
    routing = route(code_tree, ("md-instructions/Handoff.md", "M", None), ("config.toml", "M", None),
                    ("Setup.bat", "M", None), (".gitignore", "M", None))
    assert routing.static_checks == ["config", "docnames", "docs"] and routing.gaps == []  # paths in sorted order
    assert routing.tests == ["files/tests/test_other.py"]
    assert [(item.subject, item.kind) for item in routing.obligations] == [("archive:Setup.bat", "archive")]


def test_suite_wide_infrastructure_selects_representatives_and_keeps_the_scope_incomplete(code_tree):
    routing = route(code_tree, ("files/tests/conftest.py", "M", None))
    assert routing.tests == ["files/tests/test_other.py"]
    assert [(gap.subject, gap.kind) for gap in routing.gaps] == [("files/tests/conftest.py", "over-budget")]


def test_a_source_over_the_budget_is_a_gap_with_a_regression_obligation(code_tree):
    policy = {"changed": {**POLICY["changed"], "max_routed_modules": 0}}
    coverage = {"features": [{"id": "ACT.TTS.X", "tool": "tts-audiobook", "source": [{"path": "scripts/tts/voices.py"}],
                              "selection": ["files/tests/test_engine.py"]}]}
    routing = route(code_tree, ("scripts/tts/voices.py", "M", None), policy=policy, coverage=coverage)
    assert routing.tests == ["files/tests/test_engine.py"], "the reviewed feature tests still run"
    assert [(gap.subject, gap.kind) for gap in routing.gaps] == [("scripts/tts/voices.py", "over-budget")]
    assert ("component:tts-audiobook", "regression") in [(item.subject, item.kind) for item in routing.obligations]


def test_a_platform_specific_change_owes_the_other_platform(code_tree):
    write(code_tree, "scripts/shared/macos_bits.py", "X = 1\n")
    routing = route(code_tree, ("scripts/shared/macos_bits.py", "M", None))
    assert ("platform:macos", "platform") in [(item.subject, item.kind) for item in routing.obligations]


def test_a_journey_route_is_a_suggested_obligation_never_a_journey_to_run(code_tree):
    policy = {"changed": POLICY["changed"], "acceptance": {"journey_routes": {"scripts/tts/": ["tts.journey"]}}}
    routing = selection.route_changes(changed(("scripts/tts/voices.py", "M", None)), policy, {}, _index(code_tree),
                                      native_platform="windows", known_journeys=["tts.journey"])
    assert [(item.subject, item.kind) for item in routing.obligations] == [("journey:tts.journey", "native")]


# --------------------------------------------------------------------------- #
#  Routine capability classification, read statically
# --------------------------------------------------------------------------- #
@pytest.fixture
def effect_tree(tmp_path) -> Path:
    root = (tmp_path / "e").resolve()
    write(root, "files/tests/test_plain.py", "def test_a():\n    pass\n")
    write(root, "files/tests/test_heavy.py", "ACT_EFFECTS = {'*': ('real-engine',)}\n\ndef test_a():\n    pass\n")
    write(root, "files/tests/test_mixed.py", "ACT_EFFECTS = {'test_real': ('real-engine',), 'TestWindow': "
                                             "('native-desktop',)}\n\ndef test_quick():\n    pass\n\ndef test_real():\n"
                                             "    pass\n\nclass TestWindow:\n    def test_x(self):\n        pass\n")
    write(root, "files/tests/test_generated.py", "ACT_EFFECTS = {'test_real': ('real-engine',)}\n\n"
                                                 "def pytest_generate_tests(metafunc):\n    pass\n\ndef test_real():\n    pass\n")
    write(root, "files/tests/driver_helper.py", "ACT_EFFECTS = {'*': ('native-desktop',)}\n")
    write(root, "files/tests/test_via_helper.py", "import driver_helper\n\ndef test_a():\n    pass\n")
    write(root, "files/tests/test_opt_in.py", "import os\n\nREAL = os.environ.get('ACT_FOO_REAL')\n\ndef test_a():\n    pass\n")
    write(root, "files/tests/test_reviewed.py", "import os\n\nREAL = os.environ.get('ACT_BAR_REAL')\n\ndef test_a():\n    pass\n")
    return root


def classify(root, selectors, explicit=()):
    classifier = effects.Classifier(root, {"effects": {"reviewed_bounded": {"files/tests/test_reviewed.py": "reviewed"}}},
                                    evidence_ledger.Closures(root))
    return classifier(list(selectors), set(explicit))


def test_an_ordinary_test_declares_nothing_and_runs(effect_tree):
    result = classify(effect_tree, ["files/tests/test_plain.py", "files/tests/test_reviewed.py", "files/tests/test_gone.py"])
    assert result.executable == ("files/tests/test_plain.py", "files/tests/test_reviewed.py")
    assert result.withheld == ()
    # Phase 1A-1 R1 (M1): a missing module is this plan's selection gap, no longer left for pytest to report.
    assert [(gap.subject, gap.kind) for gap in result.gaps] == [("files/tests/test_gone.py", "missing")]


def test_a_declared_module_or_node_is_withheld_and_owed(effect_tree):
    result = classify(effect_tree, ["files/tests/test_heavy.py", "files/tests/test_mixed.py::test_real[a]",
                                    "files/tests/test_mixed.py::TestWindow::test_x"], explicit=["files/tests/test_heavy.py"])
    assert result.executable == ()
    assert [(item.subject, item.requested) for item in result.withheld] == [
        ("files/tests/test_heavy.py", True), ("files/tests/test_mixed.py::test_real[a]", False),
        ("files/tests/test_mixed.py::TestWindow::test_x", False)]
    assert {item.kind for item in result.obligations} == {"qualification"}


def test_a_mixed_module_selected_whole_runs_only_its_routine_tests(effect_tree):
    result = classify(effect_tree, ["files/tests/test_mixed.py"], explicit=["files/tests/test_mixed.py"])
    assert result.executable == ("files/tests/test_mixed.py::test_quick",)
    # Phase 1A-1 R1 (M1, semantics A): requested explicitly, the whole module is the scope, so each declared node is withheld
    # from it and disclosed exactly; reached any other way, only the obligations below.
    assert {(item.subject, item.requested) for item in result.withheld} == {
        ("files/tests/test_mixed.py::test_real", True), ("files/tests/test_mixed.py::TestWindow", True)}
    assert classify(effect_tree, ["files/tests/test_mixed.py"]).withheld == ()
    assert {item.subject for item in result.obligations} == {"test:files/tests/test_mixed.py::test_real",
                                                            "test:files/tests/test_mixed.py::TestWindow"}
    generated = classify(effect_tree, ["files/tests/test_generated.py"])
    assert generated.executable == () and [gap.kind for gap in generated.gaps] == ["unenumerable"]


def test_a_declaring_test_helper_is_inherited_through_the_import_closure(effect_tree):
    result = classify(effect_tree, ["files/tests/test_via_helper.py"])
    assert result.executable == () and "through files/tests/driver_helper.py" in result.withheld[0].reason


def test_an_unclassified_live_boundary_is_withheld_as_a_gap(effect_tree):
    result = classify(effect_tree, ["files/tests/test_opt_in.py"], explicit=["files/tests/test_opt_in.py"])
    assert result.executable == () and [gap.kind for gap in result.gaps] == ["unclassified"]
    assert result.withheld[0].requested is True


def test_a_declaration_must_be_a_literal_naming_known_effects(tmp_path):
    for text in ("ACT_EFFECTS = {'*': ('teleport',)}\n", "ACT_EFFECTS = dict(x=1)\n", "ACT_EFFECTS = {}\n",
                 "ACT_EFFECTS = {'*': ()}\n"):
        write(tmp_path, "files/tests/test_bad.py", text)
        with pytest.raises(effects.DeclarationError):
            effects.module_facts(tmp_path, "files/tests/test_bad.py")


def test_markers_and_file_names_alone_classify_nothing(tmp_path):
    write(tmp_path, "files/tests/test_real_engine_gui_native.py",
          "import pytest\n\n@pytest.mark.slow\ndef test_a():\n    pass\n")
    facts = effects.module_facts(tmp_path, "files/tests/test_real_engine_gui_native.py")
    assert facts.declared == {} and facts.indicators == []


# --------------------------------------------------------------------------- #
#  The real tree: every boundary classified, every entrypoint reviewed
# --------------------------------------------------------------------------- #
def _policy() -> dict:
    return json.loads((GATE_DIR / "verification.json").read_text(encoding="utf-8"))


def test_the_real_suite_has_no_unclassified_live_boundary():
    found = effects.unclassified_boundaries(REPO_ROOT, _policy(), evidence_ledger.Closures(REPO_ROOT))
    assert found == {}, found


def test_the_reviewed_bounded_list_names_only_real_modules_with_a_reason():
    reviewed = _policy()["effects"]["reviewed_bounded"]
    for module, why in reviewed.items():
        assert (REPO_ROOT / module).is_file() and str(why).strip(), module
        facts = effects.module_facts(REPO_ROOT, module)
        assert facts.indicators, f"{module} shows no live-boundary indicator: it needs no review entry"


@pytest.mark.parametrize("module, selector, effect", [
    ("files/tests/test_macos_p1b_gui_containment.py", "*", "real-app-launch"),
    ("files/tests/test_macos_p2_kokoro_real.py", "*", "real-engine"),
    ("files/tests/test_omnivoice_phase1.py", "test_real_clone_proof", "real-engine"),
    ("files/tests/test_root_lifetime.py", "test_the_negative_control_crashes_once_the_application_holder_is_gone_too",
     "real-app-launch"),
    ("files/tests/test_first_run_setup_ownership.py",
     "test_force_quitting_the_first_run_window_ends_its_worker_pip_and_helper", "native-desktop"),
])
def test_the_boundaries_the_architecture_spike_named_are_declared(module, selector, effect):
    assert effect in effects.module_facts(REPO_ROOT, module).declared[selector]


def test_every_executable_verification_entrypoint_is_classified():
    tracked = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=REPO_ROOT,
                             capture_output=True, check=True).stdout.decode("utf-8", "surrogateescape").split("\0")
    discovered = effects.tracked_entrypoints(REPO_ROOT, [path for path in tracked if path])
    table = _policy()["entrypoints"]
    assert effects.entrypoint_problems(table, discovered) == []
    assert {"files/dev-work/verification-gate/acceptance_runner.py", "files/dev-work/verification-gate/verify.py"} <= set(discovered)
    assert table["files/dev-work/verification-gate/acceptance_runner.py"]["routine"] == "data-only"
    assert all(table[path]["routine"] == "refused" for path in discovered
               if path.startswith(("files/dev-work/verification-gate/qualification/", "files/dev-work/verification-gate/scaling/"))
               and path in table and table[path]["class"] != "support")
    # The check has teeth: a new __main__ the table does not know, and a row with an unknown disposition.
    assert effects.entrypoint_problems(table, [*discovered, "files/dev-tools/new_tool.py"]) == [
        "unclassified executable entrypoint files/dev-tools/new_tool.py"]
    broken = {**table, "files/dev-tools/new_tool.py": {"class": "active", "routine": "sometimes", "why": "x"}}
    assert any("not a known value" in problem
               for problem in effects.entrypoint_problems(broken, [*discovered, "files/dev-tools/new_tool.py"]))


def test_the_real_policy_resolves_every_mode_without_importing_a_test():
    """Resolution reads text: a test module imported by it would show up in sys.modules."""
    before = set(sys.modules)
    policy = _policy()
    coverage = json.loads((GATE_DIR / "coverage.json").read_text(encoding="utf-8"))
    groups = {group["name"]: list(group["modules"]) for group in
              json.loads((REPO_ROOT / "files" / "tests" / "guarded_groups.json").read_text(encoding="utf-8"))["groups"]}
    closures = evidence_ledger.Closures(REPO_ROOT)
    ctx = ep.Context(policy=policy, coverage=coverage, groups=groups, native_platform="windows",
                     effects_for=effects.Classifier(REPO_ROOT, policy, closures), scenarios=policy.get("scenarios", {}),
                     scenario_platform={name: "windows" for name in policy.get("scenarios", {})})
    for mode, selectors in (("quick", {}), ("focused", {"tests": ("files/tests/test_omnivoice_phase1.py",)}),
                            ("regression", {"components": ("gate",)}), ("full", {})):
        plan = ep.resolve(ep.Request(mode=mode, **selectors), ctx)
        ep.validate(plan, groups)
    focused = ep.resolve(ep.Request(mode="focused", tests=("files/tests/test_omnivoice_phase1.py",)), ctx)
    assert "files/tests/test_omnivoice_phase1.py::test_real_clone_proof" not in focused.ordinary
    assert "test:files/tests/test_omnivoice_phase1.py::test_real_clone_proof" in {item.subject for item in focused.obligations}
    heavy = ep.resolve(ep.Request(mode="focused", tests=("files/tests/test_macos_p2_kokoro_real.py",)), ctx)
    assert heavy.status == "INCOMPLETE" and heavy.scope == ()
    imported = {name for name in set(sys.modules) - before if name.startswith("test_")}
    assert imported == set(), imported
    assert os.environ.get("ACT_VERIFY_CONTEXT") == "routine", "this suite runs inside the routine envelope"


# =========================================================================== #
#  Phase 1A-1 R1 regression controls (H4, M1, M3, C1-C4). Each was run against the defective 8d7226d implementation first
#  and failed there (the R1 record in the plan lists them). All synthetic: in-memory plans, temporary trees and Git
#  repositories, and the real gate only in --plan mode (prints a plan, runs nothing).
# =========================================================================== #
from helpers import repo_files  # noqa: E402

GUARDED_V3 = "files/tests/test_optional_setup_exchange_v3.py"
CASE_INSENSITIVE_CHECKOUT = not repo_files.probe_case_sensitive(REPO_ROOT)


def _link_dir(target: Path, link: Path) -> None:
    """A directory link that needs no privilege: a junction on Windows, a symlink elsewhere."""
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def _real_plan(*selectors: str) -> dict:
    """The real gate's plan for a focused request: ``--plan`` prints it and runs nothing (data-only)."""
    argv = [sys.executable, str(GATE_DIR / "verify.py"), "--mode", "focused"]
    for selector in selectors:
        argv += ["--test", selector]
    done = subprocess.run([*argv, "--plan"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=300)
    assert done.returncode in (3, 64), (done.returncode, done.stdout[-2000:], done.stderr[-2000:])
    if done.returncode == 64:
        return {"refused": done.stderr}
    text = done.stdout
    return json.loads(text[text.index("{"):text.rindex("}") + 1])


# ------------------------------------------------------------------ H4: canonical identity and guarded routing
@pytest.mark.skipif(not CASE_INSENSITIVE_CHECKOUT, reason="needs a case-insensitive checkout (native Windows; APFS default "
                    "is pending native macOS verification); the portable simulation below covers case-sensitive behaviour")
def test_r1_h4_a_windows_case_variant_of_a_guarded_module_never_reaches_ordinary_pytest():
    variant = "files/tests/test_Optional_setup_exchange_v3.py"
    assert (REPO_ROOT / variant).is_file(), "the variant names the same file on this filesystem"
    plan = _real_plan(variant)
    assert "refused" in plan or variant not in plan["ordinary"], plan
    if "refused" not in plan:
        assert GUARDED_V3 not in plan["ordinary"], plan
        assert plan["guarded"].get("v3-planning") == [GUARDED_V3.rsplit("/", 1)[-1]], plan
        assert plan["requested"] == [f"test:{GUARDED_V3}"], "the plan records the canonical identity"


def test_r1_h4_the_canonical_selector_routes_to_its_guarded_group():
    plan = _real_plan(GUARDED_V3)
    assert plan["guarded"].get("v3-planning") == ["test_optional_setup_exchange_v3.py"], plan
    assert all("test_optional_setup_exchange_v3" not in item for item in plan["ordinary"])


def test_r1_h4_a_guarded_basename_in_another_directory_is_not_a_test_identity_nor_a_member():
    for raw in ("files/tests/sub/test_optional_setup_exchange_v3.py", "scripts/test_optional_setup_exchange_v3.py",
                "../elsewhere/files/tests/test_guarded.py"):
        with pytest.raises(selection.SelectorError):
            selection.parse_selector(raw)
    plan = resolve("focused", tests=("files/tests/test_a.py",))
    for target in ("sub/test_guarded.py", "../x/test_guarded.py", "files/tests/sub/test_guarded.py::t"):
        with pytest.raises(ep.PlanError, match="guarded"):
            ep.validate(dataclasses.replace(plan, guarded=(("heavy", (target,)),)), GROUPS)


@pytest.mark.parametrize("ordinary", [("files/tests/test_guarded.py", GUARD), ("files/tests/test_guarded.py::t", GUARD),
                                      ("files/tests/test_Guarded.py", GUARD)])
def test_r1_h4_a_guarded_module_placed_in_the_ordinary_list_is_refused(ordinary):
    plan = resolve("focused", tests=("files/tests/test_a.py",))
    mutated = dataclasses.replace(plan, ordinary=ordinary, scope=tuple(s for s in ordinary if s != GUARD))
    with pytest.raises(ep.PlanError, match="guarded"):
        ep.validate(mutated, GROUPS)


def test_r1_h4_the_gate_refuses_a_guarded_member_in_its_ordinary_pytest_command():
    from gate_locator import load_gate

    gate = load_gate("act_verify_r1_ordinary_scope")
    assert gate._ordinary_scope(["files/tests/test_cancel_semantics.py"]) == ["files/tests/test_cancel_semantics.py"]
    for target in (GUARDED_V3, GUARDED_V3 + "::test_x", "files/tests/test_Optional_setup_exchange_v3.py"):
        with pytest.raises(ValueError, match="guarded"):
            gate._ordinary_scope([target])


@pytest.mark.parametrize("raw", [".\\files\\tests\\test_a.py", "./files/tests/test_a.py", "files//tests/./test_a.py",
                                 "files\\tests\\test_a.py"])
def test_r1_h4_alternate_separators_and_dot_spellings_normalize_to_one_identity(raw):
    assert selection.parse_selector(raw) == "files/tests/test_a.py"
    assert selection.parse_selector(raw + "::test_x[a/b]") == "files/tests/test_a.py::test_x[a/b]"


def test_r1_h4_a_linked_test_directory_is_refused_and_never_read(tmp_path):
    root = (tmp_path / "t").resolve()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "test_x.py").write_text("ACT_EFFECTS = {'*': ('real-engine',)}\n\ndef test_a():\n    pass\n",
                                       encoding="utf-8")
    (root / "files").mkdir(parents=True)
    _link_dir(outside, root / "files" / "tests")
    result = classify(root, ["files/tests/test_x.py"], explicit=["files/tests/test_x.py"])
    assert result.executable == () and [gap.kind for gap in result.gaps] == ["unsafe"], result
    inventory = repo_files.Inventory(root)
    assert inventory.canonical("files/tests/test_x.py")[1] == repo_files.INSIDE_LINK
    with pytest.raises(repo_files.UnsafePath):
        inventory.read_text("files/tests/test_x.py")


def test_r1_h4_case_semantics_are_the_filesystems_simulated_portably(tmp_path):
    """Native macOS (APFS) verification of this is still pending; this injects the listing and the case rule."""
    (tmp_path / "files" / "tests").mkdir(parents=True)
    (tmp_path / "files" / "tests" / "test_a.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    insensitive = repo_files.Inventory(tmp_path, case_sensitive=False)
    assert insensitive.canonical("FILES/Tests/TEST_A.py")[:2] == ("files/tests/test_a.py", repo_files.FILE)
    sensitive = repo_files.Inventory(tmp_path, case_sensitive=True)
    assert sensitive.canonical("files/tests/TEST_A.py")[1] == repo_files.MISSING
    listing = {"": ["files"], "files": ["tests"], "files/tests": ["test_a.py", "Test_A.py"]}

    def fake(path):
        relative = Path(path).relative_to(tmp_path).as_posix()
        return listing["" if relative == "." else relative]

    twins = repo_files.Inventory(tmp_path, case_sensitive=False, listdir=fake)
    assert twins.canonical("files/tests/test_a.py")[1] == repo_files.AMBIGUOUS
    ctx = context(inventory=repo_files.Inventory(tmp_path, case_sensitive=False))
    plan = resolve("focused", ctx, tests=("files/tests/TEST_A.py",))
    assert plan.requested == ("test:files/tests/test_a.py",) and "files/tests/test_a.py" in plan.ordinary
    with pytest.raises(ep.PlanError, match="ambiguous"):
        resolve("focused", context(inventory=twins), tests=("files/tests/test_a.py",))


# ------------------------------------------------------------------ M1: requested-scope reconciliation
def _effects_ctx(root, **extra):
    classifier = effects.Classifier(root, {"effects": {"reviewed_bounded": {}}}, evidence_ledger.Closures(root))
    return context(effects_for=classifier, **extra)  # resolution uses the classifier's own inventory


def test_r1_m1a_an_explicit_mixed_module_is_the_whole_scope_and_discloses_each_withheld_node(effect_tree):
    plan = resolve("focused", _effects_ctx(effect_tree), tests=("files/tests/test_mixed.py",))
    assert plan.status == "INCOMPLETE", plan.record()
    assert {(item.subject, item.requested) for item in plan.withheld} == {
        ("files/tests/test_mixed.py::test_real", True), ("files/tests/test_mixed.py::TestWindow", True)}
    assert "files/tests/test_mixed.py::test_quick" in plan.ordinary


def test_r1_m1b_a_routine_node_runs_and_a_heavy_node_is_withheld(effect_tree):
    ctx = _effects_ctx(effect_tree)
    assert resolve("focused", ctx, tests=("files/tests/test_mixed.py::test_quick",)).status == "COMPLETE"
    heavy = resolve("focused", ctx, tests=("files/tests/test_mixed.py::test_real",))
    assert heavy.status == "INCOMPLETE" and [i.subject for i in heavy.withheld] == ["files/tests/test_mixed.py::test_real"]


@pytest.mark.parametrize("node", ["files/tests/test_plain.py::test_nope", "files/tests/test_plain.py::test_nope[1]",
                                  "files/tests/test_mixed.py::TestNobody::test_x"])
def test_r1_m1b_a_nonexistent_node_never_disappears_under_its_whole_module(effect_tree, node):
    module = node.split("::", 1)[0]
    plan = resolve("focused", _effects_ctx(effect_tree), tests=(module, node))
    assert plan.status == "INCOMPLETE", plan.record()
    assert any(gap.subject == node and gap.requested and gap.kind == "missing" for gap in plan.gaps), plan.gaps


def test_r1_m1b_a_parametrized_node_is_validated_by_its_head(effect_tree):
    plan = resolve("focused", _effects_ctx(effect_tree), tests=("files/tests/test_plain.py::test_a[x-1]",))
    assert plan.status == "COMPLETE" and "files/tests/test_plain.py::test_a[x-1]" in plan.ordinary


def test_r1_m1_a_module_with_a_heavy_node_requested_too_is_incomplete(effect_tree):
    plan = resolve("focused", _effects_ctx(effect_tree), tests=("files/tests/test_mixed.py",
                                                                "files/tests/test_mixed.py::test_real"))
    assert plan.status == "INCOMPLETE" and "files/tests/test_mixed.py::test_real" not in plan.ordinary


def test_r1_m1_a_missing_module_is_a_requested_gap_not_pytests_problem(effect_tree):
    plan = resolve("focused", _effects_ctx(effect_tree), tests=("files/tests/test_gone.py",))
    assert plan.status == "INCOMPLETE" and "files/tests/test_gone.py" not in plan.ordinary
    assert [(gap.subject, gap.kind, gap.requested) for gap in plan.gaps] == [("files/tests/test_gone.py", "missing", True)]


def _feature_coverage(*selections):
    return {"features": [{"id": f"ACT.F.{index}", "tool": "t", "selection": list(selection)}
                         for index, selection in enumerate(selections)]}


def test_r1_m1c_a_feature_on_a_mixed_module_keeps_routine_coverage_and_owes_the_heavy_nodes(effect_tree):
    plan = resolve("focused", _effects_ctx(effect_tree, coverage=_feature_coverage(["files/tests/test_mixed.py"])),
                   features=("ACT.F.0",))
    assert plan.status == "COMPLETE" and plan.scope == ("files/tests/test_mixed.py::test_quick",)
    assert {item.subject for item in plan.obligations} >= {"test:files/tests/test_mixed.py::test_real"}


def test_r1_m1c_a_feature_with_only_withheld_behaviour_or_a_missing_test_file_is_incomplete(effect_tree):
    coverage = _feature_coverage(["files/tests/test_heavy.py"], ["files/tests/test_plain.py", "files/tests/test_gone.py"])
    ctx = _effects_ctx(effect_tree, coverage=coverage)
    assert resolve("focused", ctx, features=("ACT.F.0",)).status == "INCOMPLETE"
    missing = resolve("focused", ctx, features=("ACT.F.1",))
    assert missing.status == "INCOMPLETE"
    assert [(g.subject, g.kind) for g in missing.gaps] == [("files/tests/test_gone.py", "missing")]


def test_r1_m1_requested_nodes_are_reconciled_with_what_executed():
    plan = resolve("focused", tests=("files/tests/test_a.py", "files/tests/test_b.py::test_x[1]",
                                     "files/tests/test_c.py::TestK"))
    executed = {"files/tests/test_a.py::test_one", "files/tests/test_b.py::test_x[1]", "files/tests/test_c.py::TestK::test_m"}
    assert ep.unexecuted(plan, executed) == []
    assert ep.unexecuted(plan, executed - {"files/tests/test_b.py::test_x[1]"}) == ["files/tests/test_b.py::test_x[1]"]
    assert ep.unexecuted(plan, {"files/tests/test_b.py::test_x[10]"}) == [
        "files/tests/test_a.py", "files/tests/test_b.py::test_x[1]", "files/tests/test_c.py::TestK"]


# ------------------------------------------------------------------ M3: the execution-boundary trust boundary
def test_r1_m3_an_omitted_required_guard_is_refused_against_the_policy():
    request = ep.Request(mode="focused", tests=("files/tests/test_a.py",))
    plan = ep.resolve(request, context())
    ep.admit(plan, request, context())  # the no-change control
    mutated = dataclasses.replace(plan, guards=(), ordinary=("files/tests/test_a.py",))
    with pytest.raises(ep.PlanError, match="guard"):
        ep.admit(mutated, request, context())


@pytest.mark.parametrize("change, needle", [
    (lambda p: {"ordinary": ("files/tests/test_a.py", "files/tests/test_a.py::test_x", GUARD),
                "scope": ("files/tests/test_a.py", "files/tests/test_a.py::test_x")}, "overlap"),
    (lambda p: {"scope": ("files/tests/test_b.py",)}, "scope"),
    (lambda p: {"withheld": (ep.Entry("files/tests/test_a.py", "declares real-engine", "effect", ("real-engine",)),)},
     "withheld and executable"),
    (lambda p: {"requested": (*p.requested, "test:files/tests/test_c.py")}, "unrepresented"),
], ids=["whole-module-and-its-node", "disjoint-reported-scope", "withheld-and-executable", "unrepresented-request"])
def test_r1_m3_the_boundary_refuses_contradictory_scope(change, needle):
    plan = resolve("focused", tests=("files/tests/test_a.py",))
    ep.validate(plan, GROUPS)
    with pytest.raises(ep.PlanError, match=needle):
        ep.validate(dataclasses.replace(plan, **change(plan)), GROUPS)


@pytest.mark.parametrize("mode, selectors", [("qualification", {"journeys": ("mp3.journey",)})])
def test_r1_m3_a_plan_only_mode_marked_executable_is_refused(mode, selectors):
    plan = resolve(mode, **selectors)
    assert plan.executable_now is False
    with pytest.raises(ep.PlanError, match="activated"):
        ep.validate(dataclasses.replace(plan, executable_now=True), GROUPS)


def test_r1_m3_a_heavyweight_selector_with_empty_declared_effects_is_reclassified_and_refused():
    request = ep.Request(mode="focused", tests=("files/tests/test_engine.py",))
    plan = ep.resolve(request, context())  # a caller whose classification declared nothing

    def withhold(selectors, explicit):
        heavy = tuple(s for s in selectors if "engine" in s)
        return ep.EffectResult(executable=tuple(s for s in selectors if s not in heavy),
                               withheld=tuple(ep.Entry(s, "declares real-engine", "effect", ("real-engine",), s in explicit)
                                              for s in heavy))

    with pytest.raises(ep.PlanError):
        ep.admit(plan, request, context(effects_for=withhold))


def test_r1_m3_the_request_the_plan_claims_must_be_the_authoritative_one():
    plan = ep.resolve(ep.Request(mode="focused", tests=("files/tests/test_a.py",)), context())
    with pytest.raises(ep.PlanError, match="resolve"):
        ep.admit(plan, ep.Request(mode="focused", tests=("files/tests/test_b.py",)), context())


@pytest.mark.parametrize("fact", ["status", "ordinary", "requested", "executable_now", "guarded"])
def test_r1_m3_a_supplemental_fact_never_overwrites_an_authoritative_field(fact):
    plan = resolve("focused", tests=("files/tests/test_a.py",))
    with pytest.raises(ep.PlanError, match="authoritative"):
        record = dataclasses.replace(plan, facts={fact: "forged"}).record()
        assert record[fact] != "forged", "a forged fact reached the record"


def test_r1_m3_identity_fields_cannot_be_changed_after_construction():
    candidate = {"head": "abc", "nested": {"x": [1]}}
    facts = {"change": {"paths": ["a"]}}
    plan = resolve("focused", context(candidate=candidate, facts=facts), tests=("files/tests/test_a.py",))
    candidate["head"] = "forged"
    facts["change"]["paths"].append("forged")
    assert plan.record()["candidate"]["head"] == "abc" and plan.record()["change"] == {"paths": ["a"]}
    with pytest.raises(TypeError):
        plan.candidate["head"] = "forged"
    with pytest.raises((TypeError, AttributeError)):
        plan.facts["change"]["paths"].append("forged")
    json.dumps(plan.record())  # still serializable


# ------------------------------------------------------------------ C1: one no-follow inventory
def test_r1_c1_the_import_closure_never_reads_through_a_link(tmp_path):
    root = (tmp_path / "c").resolve()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "mod.py").write_text("import secret_thing\n", encoding="utf-8")
    write(root, "scripts/real.py", "X = 1\n")
    write(root, "files/tests/test_l.py", "from linked import mod\nimport real\n\ndef test_a():\n    pass\n")
    _link_dir(outside, root / "scripts" / "linked")
    closures = evidence_ledger.Closures(root)
    reach = closures.closure(["files/tests/test_l.py"])
    assert "scripts/linked/mod.py" not in reach and "scripts/real.py" in reach, reach
    assert "secret_thing" not in str(closures.names)
    routing = route(root, ("scripts/linked/mod.py", "M", None))
    assert routing.gaps and all(gap.kind in ("unreadable", "unsafe") for gap in routing.gaps), routing.gaps


def test_r1_c1_a_directory_where_a_test_module_should_be_is_a_gap(effect_tree):
    (effect_tree / "files" / "tests" / "test_dir.py").mkdir()
    result = classify(effect_tree, ["files/tests/test_dir.py"], explicit=["files/tests/test_dir.py"])
    assert result.executable == () and [gap.kind for gap in result.gaps] == ["unsafe"], result


# ------------------------------------------------------------------ C2: local-only privacy identity
def test_r1_c2_an_already_tracked_local_only_path_is_a_violation_without_any_delta(repo):
    (repo / "AGENTS.md").write_text("private\n", encoding="utf-8")
    git(repo, "add", "AGENTS.md")
    git(repo, "commit", "-q", "-m", "a mistake")
    changes = collect(repo)
    assert changes.changes == [] and changes.violations, changes.record()
    assert "private" not in json.dumps(changes.record())


@pytest.mark.skipif(not CASE_INSENSITIVE_CHECKOUT, reason="the alias needs a case-insensitive filesystem")
def test_r1_c2_a_case_alias_of_a_local_only_path_is_still_local_only(repo):
    (repo / ".AI").mkdir()
    (repo / ".AI" / "private-notes.md").write_text("secret\n", encoding="utf-8")
    (repo / "agents.md").write_text("private\n", encoding="utf-8")
    changes = collect(repo)
    assert changes.changes == [] and changes.excluded == {".ai/": 1, "AGENTS.md": 1}, changes.record()
    assert "private-notes" not in json.dumps(changes.record())


def test_r1_c2_local_only_matching_follows_the_case_rule_and_component_boundaries():
    assert git_changes.local_only_entry("AGENTS.MD", LOCAL_ONLY, case_sensitive=False) == "AGENTS.md"
    assert git_changes.local_only_entry(".AI\\x.md", LOCAL_ONLY, case_sensitive=False) == ".ai/"
    assert git_changes.local_only_entry(".aim.txt", LOCAL_ONLY, case_sensitive=False) is None
    assert git_changes.local_only_entry("AGENTS.MD", LOCAL_ONLY, case_sensitive=True) is None
    assert git_changes.local_only_entry("docs/AGENTS.md", LOCAL_ONLY, case_sensitive=False) is None


def test_r1_c2_a_rename_out_of_a_local_only_path_keeps_the_public_side_and_names_no_private_path(repo):
    (repo / ".ai").mkdir()
    (repo / ".ai" / "secret-plan.md").write_text("x\n", encoding="utf-8")
    git(repo, "add", "-f", ".ai/secret-plan.md")
    git(repo, "commit", "-q", "-m", "a mistake")
    git(repo, "mv", ".ai/secret-plan.md", "docs-plan.md")
    changes = collect(repo)
    assert changes.violations and "docs-plan.md" in by_path(changes), changes.record()
    assert "secret-plan" not in json.dumps(changes.record())


# ------------------------------------------------------------------ C3: staged deletion and recreation
def test_r1_c3_a_staged_deletion_recreated_keeps_both_facts_and_routes_the_working_file(repo, code_tree):
    git(repo, "rm", "-q", "src/a.py")
    (repo / "src" / "a.py").write_text("A = 3\n", encoding="utf-8")
    change = next(item for item in collect(repo).changes if item.path == "src/a.py")
    assert change.status == "D" and "staged" in change.sources and change.present is True
    assert change.record()["present"] is True
    routing = route(code_tree, ("files/tests/test_other.py", "D", None))  # deleted in the index, present in the tree
    assert routing.tests == ["files/tests/test_other.py"] and not [g for g in routing.gaps if g.kind == "deleted-test"]


# ------------------------------------------------------------------ C4: dependency uncertainty and candidate identity
def test_r1_c4_an_unparsed_helper_in_a_tests_closure_keeps_a_changed_source_incomplete(code_tree):
    write(code_tree, "scripts/shared/broken_helper.py", "def broken(:\n")
    write(code_tree, "files/tests/test_more.py", "from shared import broken_helper\n\ndef test_more():\n    pass\n")
    routing = route(code_tree, ("scripts/tts/voices.py", "M", None))
    assert "files/tests/test_engine.py" in routing.tests
    assert any(gap.kind == "unparsed" and "broken_helper" in gap.reason for gap in routing.gaps), routing.gaps


def test_r1_c4_an_ambiguous_import_reaches_every_candidate(code_tree):
    write(code_tree, "files/tests/shared/util.py", "def helper():\n    return 2\n")
    routing = route(code_tree, ("files/tests/shared/util.py", "M", None))
    assert "files/tests/test_util.py" in routing.tests, routing.gaps


def test_r1_c4_a_missing_mapped_test_is_a_gap_and_a_static_route_alone_never_covers_python(code_tree):
    coverage = {"features": [{"id": "ACT.X", "tool": "t", "source": [{"path": "scripts/lonely.py"}],
                              "selection": ["files/tests/test_other.py", "files/tests/test_missing.py"]}]}
    routing = route(code_tree, ("scripts/lonely.py", "M", None), coverage=coverage)
    assert any(gap.kind == "missing" and "test_missing" in gap.subject + gap.reason for gap in routing.gaps), routing.gaps
    policy = {"changed": {**POLICY["changed"], "static": {"scripts/lonely.py": ["config"]}}}
    static_only = route(code_tree, ("scripts/lonely.py", "M", None), policy=policy)
    assert any(gap.kind == "unmapped" for gap in static_only.gaps), static_only.gaps


def test_r1_c4_the_plan_candidate_binds_working_bytes_not_porcelain_status(repo):
    (repo / "src" / "a.py").write_text("A = 2\n", encoding="utf-8")
    first = git_changes.selection_identity(repo, policy_digest="p", local_only=LOCAL_ONLY)
    (repo / "src" / "a.py").write_text("A = 3\n", encoding="utf-8")  # the same porcelain status " M src/a.py"
    second = git_changes.selection_identity(repo, policy_digest="p", local_only=LOCAL_ONLY)
    assert first["available"] and first["working_digest"] != second["working_digest"]
    assert "not an authorization" in first["limitation"]


# --------------------------------------------------------------------------- #
#  Phase 1A-1 R2: privacy before reads (C2) and ambiguous imports as gaps (C4)
# --------------------------------------------------------------------------- #
def test_r2_c2_a_tracked_private_path_stops_the_evidence_map_without_naming_it(repo):
    (repo / ".ai").mkdir()
    (repo / ".ai" / "secret-notes.md").write_text("private\n", encoding="utf-8")
    assert "secret-notes" not in json.dumps(evidence_ledger.blob_map(repo, local_only=LOCAL_ONLY)), "untracked: never read"
    git(repo, "add", "-f", ".ai/secret-notes.md")
    with pytest.raises(git_changes.PrivacyViolation) as stopped:
        evidence_ledger.blob_map(repo, local_only=LOCAL_ONLY)
    assert "secret-notes" not in str(stopped.value) and "1 tracked path" in str(stopped.value)
    assert git_changes.tracked_private_count(repo, LOCAL_ONLY) == 1


def test_r2_c2_the_tree_fingerprint_neither_reads_nor_names_a_private_path(repo, monkeypatch):
    sys.path.insert(0, str(GATE_DIR))
    import verify as gate  # noqa: E402 - the gate module, imported for its pure fingerprint

    (repo / ".ai").mkdir()
    (repo / ".ai" / "secret.md").write_text("private\n", encoding="utf-8")
    git(repo, "add", "-f", ".ai/secret.md")
    (repo / ".ai" / "secret.md").write_text("changed\n", encoding="utf-8")
    read = []
    real = gate.runstore.sha256_file
    monkeypatch.setattr(gate.runstore, "sha256_file", lambda path: (read.append(str(path)), real(path))[1])
    found = gate.tree_fingerprint(repo, local_only=LOCAL_ONLY)
    assert found["available"] and found["private_tracked"] == 1
    assert not any("secret" in path for path in read), "a private file is never read"
    assert "secret" not in json.dumps(found), "a private path is never named"


def test_r2_c2_a_candidate_with_tracked_private_paths_blocks_the_plan():
    plan = ep.ExecutionPlan(mode="focused", kind="focused", requested=("files/tests/test_a.py",), native_platform="windows",
                            target_platforms=("windows",), candidate={"violations": 1}, scope=("files/tests/test_a.py",),
                            ordinary=("files/tests/test_a.py",))
    assert plan.status == "BLOCKED"
    assert dataclasses.replace(plan, candidate={"violations": 0}).status != "BLOCKED"


def test_r2_c4_a_relevant_ambiguous_import_is_a_gap_for_the_importer_the_candidates_and_what_they_reach(code_tree):
    write(code_tree, "files/tests/shared/__init__.py", "")
    write(code_tree, "files/tests/shared/util.py", "from shared import deeper\n\ndef helper():\n    return 2\n")
    write(code_tree, "files/tests/shared/deeper.py", "X = 1\n")
    for path in ("scripts/shared/util.py", "files/tests/shared/util.py", "files/tests/shared/deeper.py",
                 "files/tests/test_util.py"):
        routing = route(code_tree, (path, "M", None))
        assert any(gap.kind == "ambiguous" and gap.subject == path for gap in routing.gaps), (path, routing.gaps)
    unrelated = route(code_tree, ("scripts/tts/voices.py", "M", None))
    assert not any(gap.kind == "ambiguous" for gap in unrelated.gaps), unrelated.gaps


def test_r2_c4_an_ambiguous_import_no_test_reaches_decides_nothing(code_tree):
    write(code_tree, "scripts/orphan.py", "from shared import util\n")
    write(code_tree, "files/tests/shared/util.py", "def helper():\n    return 2\n")
    write(code_tree, "files/tests/test_util.py", "def test_util():\n    pass\n")  # nothing imports shared.util any more
    routing = route(code_tree, ("scripts/shared/util.py", "M", None))
    assert not any(gap.kind == "ambiguous" for gap in routing.gaps), routing.gaps
