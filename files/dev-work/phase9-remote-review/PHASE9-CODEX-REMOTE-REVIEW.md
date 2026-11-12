# ACT v0.7.2 — Independent Codex remote re-review

**REMOTE PREFLIGHT FAIL. INCOMPLETE / GUI GATE NOT RUN. Full Phase 9 PASS is not established.**

Review date: 2026-11-12. Independent source review and bounded adversarial execution from the remote/service session. No application fixes or verification-policy changes were made. This report is the only file authorized for staging, committing and pushing by the owner's explicit Git exception; that exception supersedes the roadmap's reviewer no-commit rule.

## Identity and scope

| Item | Verified value |
|---|---|
| Repository | `elmatthe/audiobook-creation-tool` |
| Branch | `feature/0.7.2-windows-hardening-verification` |
| Reviewed HEAD | `dd8fb1f6d1b13a906b3f18c74b23e03c60a11741` |
| Live remote feature HEAD at preflight | `dd8fb1f6d1b13a906b3f18c74b23e03c60a11741` |
| Retained remediation execution candidate | `3aa421a288a11587ad7078a5a949c05dae5f6e17` |
| Prior independently reviewed candidate | `85960252c7e2873b1e83875a759b1dfcd501c747` |
| New local evidence root | `files/run-temp/p9remote-dd8fb1-20261112/` |
| Commit scope | This Markdown report only; its publication commit is returned separately because a commit cannot contain its own SHA |

Read: `AI-WORKSPACE.md`, `.ai/AGENTS.md`, `.claude/CLAUDE.md`; the relevant current records in all four canonical documents (`Briefing.md`, `Handoff.md`, `Decisions.md`, `Changelog.md`); the authoritative `files/plans/ACT-v0.7.2-Windows-Hardening-Feature-Map-and-Verification-Gate-Implementation-Plan.md`, especially sections 13.3 and Phase 9; the prior `outputs/2026-11-11_phase9_codex_6a91/PHASE9-INDEPENDENT-CODEX-REVIEW.md`; and the retained `outputs/2026-11-11_phase9_remediation_e7b2/PHASE9-REMEDIATION-REPORT.md`. Both output paths are relative to `files/dev-work/verification-gate/`.

Git confirms that `3aa421a..dd8fb1f` changes only the four canonical documents. The prior execution candidate and reviewed HEAD therefore have identical tracked application, tests and gate code. Existing owner state comprised fourteen tracked documentation deletions and five untracked entries, including the v0.8.0 plan and `scripts/project-status.py`. The initial index was empty. No owner deletion was restored, no owner change was staged, and no reset, clean, rebase or force push was used. The v0.8.0 plan was not opened or edited.

## Findings by severity

### HIGH — R9-01: repeated body negations are still deleted (P9-01)

**Locations:** `scripts/tts/pdf_extractor.py:166` (`_edge_lines`), `:219` (`_furniture`), particularly `:239`–`:248` (repeated short capitals).

The original indiscriminate line deletion is gone, but the new classifier still cannot support the documented claim that uncertainty always errs toward narration. It treats a short capitalized body line as furniture if it is separated from the other lines and repeated at the same height on another page. There is no requirement that the line be near the physical page margin or that it be independent of a body sentence.

**Actual real-PDF reproduction:** generate two pages with PyMuPDF, default font size, placing `The signal has been checked.` at `(72, 80)`, `The next command is` at `(72, 96)` and `NOT` at `(72, 160)` on each page. These are body sentences with an emphasized negation, well inside a normal page. Extract through unchanged `extract_text_from_pdf`.

Expected: both `NOT` tokens survive. Actual: neither survives; the output contains `The next command is The signal has been checked.` and ends with `The next command is`. A control changing only the second page's final word to `NASA` retains the first page's `NOT` and the second page's `NASA`.

Evidence: `probe.py`, `probes.json`, and the two retained PDFs under `pdf/` in the new evidence root. All 50 selected existing PDF tests pass, so they do not cover this repeated-body-content case. The original single-occurrence examples are repaired; semantic preservation as a whole is still **FAIL**. This is distinct from accepting a narrated running head or the already documented compound-word limitation.

**Exact remediation needed:** preserve short repeated body lines when furniture identity is ambiguous. Constrain furniture candidates to actual page-margin regions and reject deletion when the surrounding sentence uses the candidate as content; if those conditions cannot establish furniture, retain the text. Add real-PDF regressions for repeated `NOT`, `I`, and acronyms in body text, alongside positive folio/head controls. Reassess the claim that the five existing limitations exhaust the content-loss risks.

### HIGH — R9-02: T5 can falsely certify a missed staging peak after filename reuse (P9-04)

**Locations:** `files/dev-work/verification-gate/scaling/staging.py:78`–`:79`, `:124` (watch events collapse into path sets), `:183`, `:248` (`_announced` persists), `:327`–`:330`, `:371` (set subtraction); `scaling/qualify.py`, `staging_problems` and `resource_checks`.

The literal zero-increase total budget is restored. The completeness assertion is still false: once a pathname has an announced removal, subsequent unobserved removals of another file using that pathname are covered by the old announcement. The Windows watch also stores created/removed names as sets, losing event multiplicity and file lifetimes.

**Actual filesystem reproduction, with the real Windows watcher and unchanged production T5 judge:**

1. Start `StagingCensus` on a new owned directory.
2. Create `.act-tmp-reused.mp3` with `os.open(O_CREAT|O_EXCL|O_WRONLY)`, write 100 bytes, close and unlink it in the parent. This legitimately records one removal and adds the path to `_announced`.
3. An owned Python child creates the same path, writes 200,100 bytes, confirms that size with `stat`, then unlinks it. The parent makes no corresponding audit announcement.
4. Create a separate 100-byte owned temporary and rename it to one final output. Finish the census and pass its unedited record to `qualify.staging_problems` and `qualify.resource_checks` against the clean 100-byte baseline.

| Case | Witnessed temporary bytes | Census peak | Completeness problems | Actual T5 verdict |
|---|---:|---:|---|---|
| Clean control | 100 | 100 | none | PASS |
| Reused-name child transient | 200,100 | 100 | none | **PASS — incorrect** |
| Fresh-name child transient | 200,100 | 100 | unannounced removal | FAIL — correct |

The reused-name record says watch armed and drained, lost events 0, no watch error, no unobserved operation, no missing creation, no links, no leftovers. All compared directory paths have equal length. This is an actual T5 false PASS, not an inference from a low counter. T4 counters in the judge call use the existing test fixture builder only to satisfy that separate interface; this experiment makes no claim of a complete media conversion, T4 qualification or whole-scenario PASS. The child peak occurs between sampler observations, represented by a sampled peak of zero; exact accounting must detect that case independently of sampling.

Evidence: `staging_judge.py`, `staging-judged-v2.json`, `staging-judge-v2.log`, directories `judge2-aaaa`, `judge2-bbbb`, `judge2-cccc`. An initial run with unequal-length paths was correctly refused by T5 for path length; its `staging-judged.json` and log are retained. The v2 run changes only fixture path lengths to meet that prerequisite and reproduces the false PASS.

**Exact remediation needed:** correlate ordered creation/removal/rename events and audit announcements per file lifetime, rather than permanently trusting a path. Fail closed for any lifetime that cannot be reconciled, including repeated reuse and child mutations. Add the reused-name case with a passing clean control and failing fresh-name control. Preserve the zero-increase total budget; do not replace it with tolerance or polling. Rerun the affected staging controls and scaling qualification after repair.

### HIGH — R9-03: MP3 Tool and Maker destroy a competing destination (ACT72-075)

**Locations:** `scripts/mp3/mp3_plan.py:408`, `:432`; `scripts/m4b/m4b_staging.py:148`, `:170`, `:181`.

Both publishers preflight the destination and then replace it. The Converter's new `publish_new` operation does not protect these callers. The shared M4B staging helper also serves the Metadata Editor, although this review's requested reproduction targets the Maker path.

**Actual bounded race:** construct valid disposable staging layouts and plan-shaped fixtures, let the real publisher complete its normal preflight, then insert a competing file at the boundary immediately before its real `os.replace`. The in-memory wrapper creates `competitor must survive` and calls the original filesystem replace. Neither implementation is edited.

Actual for both publishers: the function reports successful publication, the destination contains `new output`, and the competing bytes are gone. Expected: refuse publication and preserve the competing bytes. The wrapper deterministically schedules the competing writer; the destructive operation itself is the real Windows filesystem operation.

Evidence: `probe.py`, `probes.json`, retained `mp3/` and `maker/` fixture trees. This advances ACT72-075 from source-only suspicion in the remediation report to **reproduced FAIL**. Cross-device fallback was inspected but not separately executed; it also uses replacement.

**Exact remediation needed:** use an atomic no-clobber operation for every newly published destination in MP3 publication and both same-device and cross-device M4B staging paths. Preserve planned names and competing bytes. MP3 rollback must remove or move only outputs demonstrably published by this attempt, preserving retry staging and unrelated files. Add single-output, multi-output rollback, retry and cross-device collision regressions. Apply deliberate replacement only where the user explicitly authorized replacement.

### MEDIUM — R9-04: the Converter's event latch and commit authorization are not one ordered decision (P9-02 residual)

**Locations:** `scripts/m4b/converter/m4b_converter.py:1301` (`cancel` sets the panel event before calling the controller), `:1806`–`:1822` (`authorize_publication` separately checks that event and calls `controller.authorize_commit`); `scripts/shared/job_control.py:1534`.

The controller correctly orders its own Cancel flag and commit authorization under one condition lock. The panel event is outside that ordering. The comment that an event-first Cancel necessarily wins is therefore incorrect.

**Deterministic threaded reproduction:** extract the actual `cancel` method and `authorize_publication` closure from the current source using AST, execute them against a minimal panel-shaped object with real events and a real running `JobController`, and run actual `convert_segment`. Only encoding is replaced with an owned staged-byte fixture. Pause the worker after its event check but before the real controller authorization; start the actual Cancel method; yield after its event is set but before its controller request takes the lock; permit authorization; finish the controller cancellation; return from Cancel; finally permit publication.

Observed order, retained verbatim in `cancel-actual.json`:

```text
event check returned false
actual cancel reached controller with event True
controller authorized True with event True
actual cancel returned
worker published
```

The segment returns `finalised=True`, `cancelled=False`, with the output present and both the panel event and controller cancellation flag set. This is a feasible scheduler interleaving between existing operations, enforced by bounded events rather than timing sleeps. No Tk root is created.

**Interpretation and limit:** the original Cancel-during-final-measurement defect is repaired by the new checks. A commit authorized before the controller's Cancel latch is allowed to finish by the controller contract. The remaining defect is that authorization can occur *after the panel event is already latched*, contrary to the panel's stated event-first guarantee. This probe proves the segment boundary and actual Cancel method ordering; it does not establish that a full native panel run ultimately reports SUCCEEDED or retains the whole interrupted book, because later panel rollback may remove it. Do not conflate this with the prior full-GUI reproduction.

**Exact remediation needed:** establish one cancellation/publication linearization point shared by the panel and controller. A panel event set first must not permit a later authorization; checking the event separately or adding another unlocked check leaves a gap. Use one shared latch/lock for that decision and release it before filesystem I/O. Preserve the legitimate commit-first outcome and pair authorization with `commit_finished`. Add this exact interleaving, Cancel-during-validation, commit-first, Pause, split rollback and final-book settlement regressions, then verify the full panel on the interactive desktop.

## Disposition of every requested finding

| Item | Remote disposition | Reason |
|---|---|---|
| P9-01 / ACT72-070 | **FAIL** | Original single-occurrence loss repaired; repeated body negations still deleted (R9-01) |
| P9-02 / ACT72-071 | **FAIL for complete ordering closure** | Original validation-window reproduction passes; event/controller interleaving remains (R9-04) |
| P9-03 / ACT72-072 | **PASS within bounded remote scope** | Producer rejects contradictory, empty and wrong-scenario verdicts; missing required evidence rejected; existing producer/reader tests pass |
| P9-04 / ACT72-073 | **FAIL** | Zero-increase arithmetic restored, but reused lifetimes defeat completeness and produce T5 false PASS (R9-02) |
| P9-05 / ACT72-074 | **PASS within bounded Windows scope** | Converter uses no-clobber `publish_new`; occupied-name and competing-writer tests pass |
| ACT72-075 | **FAIL** | Both requested publishers overwrite a destination created after preflight (R9-03) |
| Possible `_cancel_event` / `authorize_commit` interleaving | **Confirmed** | Actual extracted methods plus real controller and segment; no full native settlement claim |
| Independent Windows native GUI gate | **BLOCKED / NOT RUN** | Review process Session 0; interactive console Session 1; `OpenInputDesktop` failed |

P9-03 is a verdict/evidence acceptance boundary result, not a claim that every measurement inside a scenario is valid. In particular, a correctly sealed verdict can contain the incorrect T5 measurement demonstrated above.

## Actual tests and evidence

The command runner initially failed to start inside the sandbox with `timed out after 15000ms connecting runner pipe-in`. Read-only inspection and tests succeeded through the approved execution path outside the sandbox. No dependency, engine, model or system-setting installation/change was performed.

Exact focused invocation from the repository root:

```powershell
.venv/Scripts/python.exe -B -m pytest files/tests/test_pdf_text_cleaning.py files/tests/test_m4b_publication_order.py files/tests/test_verification_gate_contract.py -q -p no:cacheprovider --basetemp=files/run-temp/p9remote-dd8fb1-20261112/pytest -k 'not journey and not real and not books_final and not pause_during and not between_the_authorization and not after_the_last_output and not during_retry' --junitxml=files/run-temp/p9remote-dd8fb1-20261112/focused.xml
```

**348 passed, 25 deselected, 1 warning in 285.71 seconds.** JUnit independently counts 50 PDF tests, 15 publication tests and 283 gate-contract tests. No selected test failed or skipped. The warning is pydub's Python `audioop` deprecation. The exclusions bound this remote run and avoid the panel/media journeys; they are not qualification exemptions or policy edits. This direct pytest invocation is not a sealed full or focused canonical gate result.

Additional actual executions, all using `.venv/Scripts/python.exe -B` and scripts under the new evidence root:

- `probe.py`: real generated PDFs; exact worker authorization closure; real segment publication with encoding stub; real MP3 and M4B publication with competing-writer injection; real Windows directory watcher; desktop accessibility check.
- `staging_judge.py`: real census clean/reuse/fresh controls and unchanged T5 judgement. Initial unequal-path run retained; equal-path v2 is authoritative for the T5 false-PASS claim.
- `cancel_actual.py`: actual AST-extracted Cancel and authorization functions, real controller, bounded threaded interleaving and real filesystem publication.
- `audit.py`: independent malformed-verdict calls to `judge_scenario` and `scenario_evidence_problems`; readback of five retained sealed runs; JUnit counts and evidence hashes. Failed check, zero runs and empty checks return FAIL; wrong scenario returns no admissible scenario verdict; missing identity/runs and missing T5 family are rejected. The one-check control passes only the preliminary judgement and is refused by the full evidence requirement, as intended.

For reproducing the individual probes, use a new owned directory or new fixture names: the scripts deliberately refuse to reuse their existing fixture directories. The report retains the essential reproduction steps above; local probe sources and raw outputs remain untracked and are not included in the report-only commit.

Selected evidence SHA-256 values:

| Artifact relative to new evidence root | SHA-256 |
|---|---|
| `focused.xml` | `b3d8683d411e4ac0c3d0217e802e859b0b9ebe6a6edca780a7134e6dc0273871` |
| `probes.json` | `f78a191679e41cc3b8fb657573576be01284d0f82d93bac76add5c0476025361` |
| `staging-judged-v2.json` | `5c3b3219562760b2bd61963223a423c74e6187895a115fcdb7202354ebe9db0e` |

`audit.json` contains the remaining hashes available at its execution time. Its hash of its own then-open redirected log is not a final log digest and must not be used as one. `cancel-actual.json` was produced afterwards and is not covered by that earlier manifest.

## Retained qualification evidence and GUI limitations

The current production status reader independently returned `PASS`, `valid=True`, no problems for these five retained runs:

| Run | Recorded execution HEAD |
|---|---|
| `2026-11-12_050536_full_c132` | `3aa421a288a11587ad7078a5a949c05dae5f6e17` |
| `2026-11-12_002934_qualification_2cd6` | same |
| `2026-11-12_025238_qualification_25cd` | same |
| `2026-11-12_030349_qualification_f77a` | same |
| `2026-11-12_031059_qualification_feb6` | same |

This is readback of retained evidence, not new execution. The reader was called without a current-environment identity, so `current` is null; no remote-environment freshness PASS is claimed. Git establishes the docs-only code relationship to reviewed HEAD under roadmap section 13.3. The historical full gate's FAIL and BLOCKED predecessors remain recorded in the remediation report and were not replaced by this review. A valid historical seal does not establish T5 completeness against R9-02.

The review shell process reported `SessionId: 0`; `query session` showed the service session disconnected and console Session 1 active. `OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)` returned null, error 1. Existence of an active console is not proof that this SSH process can drive it. **No full Windows native GUI gate, screenshot journey or interactive input was launched.** No new claims are made about whole-panel rollback, screenshot visibility, Explorer responsiveness, DPI, visual baselines or listening.

Also not rerun: complete scaling throughput/media qualification, network Edge qualification, optional-engine narration, fresh installation/repair qualification, macOS, Windows 10 or another physical machine. Native encoding in the race probes is stubbed; the actual filesystem boundaries and controller are exercised. The repeated-body-PDF probe uses real PDF extraction. The T5 child uses real files and the real watcher, but no full FFmpeg benchmark. These limits prevent a full Phase 9 acceptance claim even if every remote preflight check had passed.

Preservation: new writes were confined to the owned disposable evidence root and this report directory, plus normal test-owned/cache artifacts. The existing suite's preservation guards passed. Post-test `git diff --name-only HEAD -- scripts files/tests files/dev-work/verification-gate` was empty. The owner deletions/untracked entries remained present. No owner settings, models, legacy TEMP folders or prior evidence were intentionally modified or removed; this review did not perform a before/after byte census of every owner asset and does not claim one. No unrelated process was stopped, no Explorer window was opened, and no cleanup was performed.

## Final independent recommendation

**REMOTE PREFLIGHT FAIL:** remediate R9-01, R9-02 and R9-03, and resolve the event-first ordering defect R9-04 before advancing. Keep P9-01, P9-02 and P9-04 open rather than treating the passing regression suite as closure. P9-03 and P9-05 pass the bounded checks actually performed here.

**INCOMPLETE / GUI GATE NOT RUN:** after bounded fixes and their negative controls, obtain a fresh independent run of the required applicable Windows gate and affected qualifications from a verified accessible interactive desktop. Preserve the failed controls and evidence, frozen budgets, legitimate commit-first behavior, and owner files. Owner listening/visual acceptance remains separate.

Do not declare full Phase 9 PASS, enter Phase 10 as accepted, merge, tag or release on this report. The authorized next Git action is publication of this report alone to the named feature branch, followed by stopping.
