# FAIL — ACT v0.8.2 Phase 1A-1 R2 independent review

**Scope:** Windows 11, designated Python 3.12.15, branch `0.8.2`, candidate `b96c36f1bd7f703bf4a2c59860d9d16364ee6789`, tree `dde73bc25cab4d3823f60dadde3632cc91bd2fd2`, parent `25c02c416828211cce326cde94adcd5a1ba23b8a`. Local and live remote pointed to the candidate at review start. The committed delta is 48 paths (42 modified, six added), confined to verification infrastructure, tests and docs. Application VERSION is 0.8.1. Phase 1A-2 remains on HOLD. Native macOS proof is pending.

## Required corrections

| Severity | Finding and independent observation | Smallest correction |
|---|---|---|
| High | **Early startup and inert classification, H2/H3.** The real nested routine runner accepted a replacement PYTHONPATH with a disposable sitecustomize. It printed that routine_effects was absent, then the inner session and ledger passed. The inert AST profile also admitted a plain inline import of signal with a disposable cwd. A local signal module printed that routine_effects was absent and the child exited zero. The allowed syntax does not establish import identity. The final audit admits on environment object identity and argument tail, with no comparison of the actual executable or cwd. See routine_effects.py:818, :963, :1806 and routine_fixtures.py:928–976. | Share startup validation for nested and ordinary Python. Preserve legitimate target imports only after bootstrap. Permit unchanged inert forms only with a trusted startup and import path (including cwd and user site when applicable). Bind and compare the complete normalized invocation through the actual OS boundary. Keep exact exceptions. |
| High | **Synthetic outputs and stage-zero boundary, H1/H3.** The current fixed recipe rejects a changed or re-declared backend, and targeted tests refused historical and real backend bytes. A classification-only probe nevertheless admitted the exact acceptance recipe with a report outside its owned fixture and a traversal-shaped journey ID. check_operation checks a relative stand-in before the actual spawn. The recipe uses argv as writable destinations. The real Windows stage-zero script also classified bounded with AssumeNo and a disposable OutFile, although its real existing-interpreter/Tk proof precedes consent. No backend or stage-zero script was executed. See routine_effects.py:753, routine_context.py:1250 and :1396, scripted_acceptance_runner.py:15–38, routine_fixtures.py:287, bootstrap_host.ps1:50 and :190. | Bind the actual supervised executable, complete argv, helper identities and environment. Check every output and relative ID under the owner-established no-follow root. Admit assume-no against a proved disposable setup state and exact shell startup. Check cmd startup and PATH/cwd fallback, and Bash startup and helper resolution. |
| High | **Terminal accounting can pass without independent launch evidence, M2/R1-03.** A format-3 fixture retained the parent reservation and child start, init and end, while removing the parent spawn and observation. read_ledger returned PASS with no problems. The ordinary ended-child branch only compares observations if present. In explained stops, taskkill intent records ok=True before the tool runs, and exit matching allows code-less stops. The descendant logic can use a tree flag independently of the stop that was proved, or accept gone without binding its order to that stop. The failed-stop control correctly returned FAIL. Process-wide lifecycle scopes can stamp concurrent unrelated launches with a matching crash expectation. See routine_context.py:871–927, :1024–1135, routine_effects.py:382, :1059 and :1124–1141. | Require one owner-side spawn and an independently bound observation for every completed reserved launch. For explained stops, match a single successful bound action, membership, chronology and observed outcome before accounting for descendants or accepting an exit mismatch. Carry test-scoped authority only into its intended worker launches. Keep initial-write failures and unexpected refusals fatal. |
| High | **Privacy and containment before evidence, C2.** The six requested concerns are reconciled below. | Put all candidate/evidence paths behind the existing privacy predicate and no-follow inventory. Fail closed on unavailable policy and tracked violations before reads, logging or CURRENT. Maintain sealed historical status readback. |
| Medium | **Qwen3 compatibility hidden by missing prior prerequisite.** In a pure comparison with simulated installed interpreter resolution, original R1 classification allowed the exact read-only selfcheck and R2 refused it as real-engine. The policy still classifies that fixed selfcheck as bounded, and the ordinary module is outside the guarded groups. See routine_effects.py:895–905, guarded_pytest.py:211 and :291, verification.json:1161 and test_qwen3_calm_harness.py:440–453. | Bind one exact disposable/offline read-only selfcheck profile if that contract is retained. Prove the launch decision with a simulated environment independently of the installed-library result. The real environment proof requires a separate authorized environment with the prerequisite present. |
| Low | **Execution documentation drift.** Briefing section 8 still tells readers owner authorization can enable plan-only modes and refers to guarded direct pytest. | Align Briefing and the current Handoff with GATE.md. Preserve all historical evidence and status. |

### C2 disposition

1. **Unavailable policy reproduced.** A disposable Git index held an inert private file. When policy loading failed, tree_fingerprint reported available, private_tracked=0, included the sentinel name in tracked status, and its digest changed when only private bytes changed. The index-aware blob_map control with usable policy raised PrivacyViolation and withheld the filename. verify.py:563–615 and :1054–1065 run capture before the later policy check.
2. **Direct hashing reproduced.** A public-looking tracked path under a Windows junction led into a disposable private directory. tree_fingerprint reported zero violations and changed when the private target changed. The same risk applies to an outside-tree junction. verify.py:613–619 bypasses the Inventory.
3. **Blob mapping reproduced for an ancestor junction.** blob_map returned a new Git blob identity for the private target reached through the public alias. It rejects line-break names before stdin-paths, so the proposed newline split did not survive R2. The file checks follow links and Git still applies configured clean filters. helpers/evidence_ledger.py:86–114.
4. **Historical handling open.** blob_map_at reproduced accepting the unfiltered aliased path. It has no policy argument and load_runs also consumes saved maps unfiltered. Existing historical status can remain read-only. Filter names at evidence consumption and redact a violation or suppress the current claim. helpers/evidence_ledger.py:117 and :392–416.
5. **Ordering open by source inspection.** Changed selection runs rename-aware staged, working and historical Git diffs before the full index privacy check and rename-side redaction. Git can inspect content for similarity. tree_fingerprint similarly calls status after merely counting private tracked names. This review did not instrument Git's internal reads for each rename form. helpers/git_changes.py:178–241 and verify.py:586–603.
6. **Diagnostics and current claims reproduced.** Injected Git stderr containing an inert private name flowed through ChangeError unchanged. The raw argv is logged before privacy admission. The current-identity comparator returned exact for equal digests with private_tracked=1. Stop or redact all three paths. helpers/git_changes.py:83–89, helpers/evidence_ledger.py:75–80, verify.py:2143–2156 and helpers/runstore.py:295–308.

## Finding reconciliation

| Finding | Windows disposition | Evidence and limit |
|---|---|---|
| H1 / R1-02 | PARTIALLY CLOSED | Known historical/modified/real backend controls passed. Positive byte identity exists. The actual recipe output, imported helpers and complete shell fallback contract remain open. |
| H2 / R1-01 | PARTIALLY CLOSED | Ordinary effect-capable child bootstrap and argv controls passed. Source binds reservations in routine_child.py and routine_effects.py. Nested startup, shadowed imports, shell environment and final audit binding remain open. |
| H3 | PARTIALLY CLOSED | Both real guarded and ordinary stages give early runner records. D-R2-7 inert events proved the measured guard decides first and the envelope refuses a permitted event. Before-envelope startup and synthetic/stage-zero seams remain open. |
| H4 | CLOSED | Canonical Windows guarded routing passed fresh in e12e. Native APFS pending. |
| M1 / R1-05 | CLOSED for reproduced post-collection removal | Fresh two-test silent-removal control failed the inner direct run as expected. gate_session_probe.py:71 and pytest_reports.py:107 catch disappearance after item collection. Both saved real runners carry initial/retained inventories; fake pytest is explicitly a synthetic recipe. Explicit selectors, guards and named skips retain their own checks. |
| M2 / R1-03 | PARTIALLY CLOSED | First-record failure stays outstanding and the named guard test passed. Parent reservation, owned stage and probe identity are materially improved. Missing parent spawn/exit, stop outcome binding, descendant attribution and scope isolation remain open. |
| M2 / R1-04 | CLOSED for reported malformed-row failure | Array/object controls passed fresh. e12e exercised a damaged inner ledger, required sealed FAIL and validated it in the contract test. Format-3 counts and malformed shapes fail through a controlled parser. |
| M3 | CLOSED | execution_plan.admit still re-resolves immutable authoritative request; contract campaign includes mutation controls. |
| C1 | CLOSED for selection | repo_files.Inventory still protects selector and closure reads. Legacy evidence readers have the separate C2 gap. |
| C2 | OPEN | Direct, status, evidence-map, history and diagnostic seams reproduced or traced above. |
| C3 | CLOSED | git_changes.collect still preserves staged deletion plus recreation and routes on working presence. Saved plan tests cover the case. |
| C4 | CLOSED for relevant supported routes | Closures retains candidate edges; ReverseIndex and route_changes emit a gap for importer, candidates or reached dependencies. Saved controls retain known routes and leave unrelated ambiguity alone. |

| Decision | Disposition |
|---|---|
| D-R2-1 | PARTIALLY CLOSED. First-record refusal and failed-stop controls pass. Parent observations and proved stop attribution remain mandatory. |
| D-R2-2 | PARTIALLY CLOSED. Exact Tk startup measurements retained. Unapproved nested startup reproduced. |
| D-R2-3 | CLOSED in Windows scope. Fixed base-interpreter pre-venv footprint profile, -I -S, disposable cwd and exact code. |
| D-R2-4 | PARTIALLY CLOSED. Windows Job/native and multiprocessing controls are represented. Shell startup and actual invocation binding remain open. Native macOS remains pending. |
| D-R2-5 | CLOSED as a budgeted attempt. The first campaign exhausted its limit and was correctly recorded BLOCKED, including guard failures. D-R2-10 replaced it. |
| D-R2-6 | CLOSED. Raw pytest refusal retained, stage-with-no-session still tested separately. |
| D-R2-7 | CLOSED in tested Windows scope. Inert synthetic audit event produced worker-first with clean ledger and envelope-refused with failed ledger if the worker allowed it. An explicitly adopted negative control can handle that expected inner failure. Ordinary accounting would fail. |
| D-R2-8 | PARTIALLY CLOSED. Startup cancellation controls are genuine. Non-isolated inert profile can import code from cwd, so the leaf exemption exceeds its contract. |
| D-R2-9 | CLOSED in saved Windows scope. Exact six-name worker profiles and both genuine guarded groups reproduced in saved evidence. |
| D-R2-10 | CLOSED as a campaign budget and scope record. Three segments and 23 real runs, with three failed runs retained. It cannot close the defects above. |

## Saved evidence

Independent recomputation verified 24 result seals and 3,385 artifact sizes/hashes, including the separate 111-pass documentation run. No missing or unlisted files appeared. The 23 campaign runs had **9,574 passing executions across 8,586 unique passing node IDs, 988 repeat pass executions and 466 skips across 421 IDs**. The reported 9,042 is the ordinary passing count. The 532 guarded passes are additional to that count and already included in 9,574. The 20 passing campaign envelopes contain 7,256 passing executions. The remaining 2,318 passed at test level within three failed envelopes.

All 377 recorded campaign selector entries reconcile with the normalized planned selectors. Only the intentionally misrequested Kokoro script lacks a corresponding executed node. Full exact selectors, executed IDs and skip reasons were retained in the local independent audit. The 29 actual pytest stages had matching probe/JUnit tokens, supervised PID or redirector parent, participant and stage-ledger token, and consistent initial/retained collection. Ledger re-read yielded 28 PASS and the historical batch-12 FAIL, with 1,549 participant records, 1,458 graceful ends, 89 explained stops and 21,411 reconciled or reported launch entries. Saved ownership was clean with zero surviving owned children. Campaign wall budget 4,442 s, segments 1,929/2,045/468 s. Sum of sealed run elapsed times 4,341.30 s, test-stage supervisor times 4,069.20 s and JUnit suite times 4,054.17 s.

| Batch | Run | Result | Passing cases | Skips |
|---:|---|---|---:|---:|
| 0 | 8de1 | PASS | 418 | 29 |
| 1 | bdce | PASS | 601 | 19 |
| 2 | 3c1d | PASS | 622 | 0 |
| 3 | 4d61 | FAIL | 427 | 18 |
| 4 | 2bab | PASS | 120 | 0 |
| 5 | ec0a | PASS | 677 | 0 |
| 6 | 870a | PASS | 450 | 67 |
| 7 | 9f9b | PASS | 225 | 119 |
| 8 | c363 | PASS | 464 | 44 |
| 9 | c9b6 | FAIL | 1176 | 78 |
| 10 | ec2a | PASS | 582 | 2 |
| 11 | a6fe | PASS | 1410 | 0 |
| 12 | 5d8a | FAIL | 715 | 45 |
| 13 | a6ba | PASS | 75 | 0 |
| 14 | 0264 | PASS | 102 | 0 |
| 15 | 11d6 | PASS | 76 | 0 |
| 16 | f7a9 | PASS | 121 | 0 |
| 17 | 2431 | PASS | 88 | 0 |
| 18 | 2389 | PASS | 98 | 0 |
| 19 | 1383 | PASS | 60 | 0 |
| 20 | 6e78 | PASS | 255 | 0 |
| 21 | fdcf | PASS | 96 | 0 |
| 22 | 4e38 | PASS | 716 | 45 |
| Docs | 2130 | PASS | 111 | 0 |

The five guarded stages executed v3-supervisor **75** and v3-planning **85, 47, 242 and 83**. Each had its own JUnit/probe/ledger identity, actual Windows Job, clean lifetime report and equal runner/config hashes. Each run also executed 13 ordinary guards. The protected source/write, unexpected process and network/model reports were clean.

All campaign executions report parent HEAD with dirty candidate bytes. The blob maps agree within batches 0–9, 10–20, and 21–22. The 10–20 delta from 0–9 is Handoff only. The 21–22 delta from 10–20 is the Tcl crash marker plus its comment. Removing those two lines reproduces the exact older clean-filtered Git blob. The raw marker-on SHA-256 matches the implementation record. The live 800-file byte fingerprint equals the documentation run (`79b6eb308274ede40432382904c9b0438d6adfacf209d70d03f7db5585cb44e2`). The final tree commits a different mixed-EOL Decisions blob. Recomputing with those committed raw bytes gives `a111b46c48da0f90b4f3968d3a87ab792785aaebb645e2b90b8327d46c192a9d`. Early documentation blob objects were unavailable for an exact full raw reconstruction. The maps identify their paths and execution digests. No independent reason to replay earlier unaffected selections solely for this docs/one-marker delta.

- **Batch 3:** FAIL is correct. test_kokoro_voices.py is a manual script in inventory.modules_without_tests. The batch ran 28 passing test_kokoro_health.py cases. The manifest error does not negate those executions.
- **Batch 9:** FAIL is correct. test_qwen3_calm_harness.py::test_the_real_library_merges_an_explicit_baseline_identically_and_temperature_alone_changes_one_value skipped with “no Qwen3 environment or Base model on this machine.” Requires the engine interpreter and Base generation_config.json, not inference. Existing skip policy has no waiver. The same historical skip appears in f22b and the older full baseline is recorded in Handoff. The 70 other calm-harness cases passed. The missing prerequisite is a pre-existing environment obligation (B). The removed routine selfcheck allowance is an R2 compatibility regression (C), concealed by that skip. It blocks an unconditional compatibility PASS. Committing R2 as adequately verified did not meet the stated condition. Owner disposition if needed after correction is whether to accept an expressly Windows-scoped checkpoint with the installed-library proof deferred, or require an authorized run of that one read-only check against an already provisioned environment. Neither changes the historical batch FAIL.
- **Batch 12:** FAIL is correct. Both deliberate Tcl_AsyncDelete variants lacked an approved lifecycle. Both observed stops appear in the sealed old ledger as unexplained. Corrective 4e38 passed 716 tests and included the complete Tk module and test_hardening_matrix.py::test_no_structural_guard_in_this_phase_slices_python_source. Marker-off/on is supported by the saved ledgers and exact marker-only blob change. The current process-wide lifecycle activation needs the scope correction above before claiming it cannot excuse an unrelated concurrent matching crash.

## Fresh review, workspace and next action

The supported direct routine runner ran six named selectors expanded to 20 cases, 20 PASS and zero skips in 4.19 s. They covered effective Python child enforcement and dispatch, first-record loss, malformed rows, the two-test silent-removal control and positive recipe identity. A fresh focused gate run e12e selected the malformed-ledger sealing and Windows case-variant contract tests, with 15 passes including required guards in 7.18 pytest seconds, no skips and a valid outer seal. The controlled synthetic and pure probes above touched only disposable fixtures. No campaign replay or real heavyweight operation was needed.

R1 review artifacts remain present. Four historical passing R1 seals and f22b were rechecked. The cleanup record names three authorized scratch deletions, 6f39, ea44 and f611. Those scratch directories are gone and 6dc8/b18e remain. The record reports 32.28 GiB reclaimed. Historical full-run copies named by those three markers were outside the permitted review locations, so their separately retained seals were not independently rehashed. Current R1/R2 materials were preserved.

The adopted workspace instructions were present and excluded from the index and candidate diff. Local HEAD and index were preserved, including the pre-existing unstaged Decisions line-ending difference and existing untracked scratch. Free space was about 41.9 GiB before probes and 41.6 GiB afterward. Local PowerShell, Git, ripgrep, Python, code-review, agent-skills and Git workflow guidance were used. Installed capabilities were inspected. GitHub was used to publish this single sanitized report on the working branch.

**Next action:** Scope a bounded follow-up to the five findings above, keeping the existing plan, GateRun, supervisor, probe and ledger. Re-run the exact negative controls and affected focused cases independently. Preserve native macOS as pending. Continue the Phase 1A-2 hold.
