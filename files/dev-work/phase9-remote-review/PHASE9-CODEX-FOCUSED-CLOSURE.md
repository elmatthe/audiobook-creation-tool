# ACT v0.7.2 — Independent focused Codex closure review

**FOCUSED CLOSURE FAIL.** R9-02 and R9-04 pass this bounded review. R9-01 retains meaningful numeric-content deletion; R9-03 retains a reproduced **HIGH** MP3 rollback data-safety defect. This is neither full Phase 9 PASS nor release approval.

Review date: 2026-11-12. Role: independent verifier; no implementation changes. All challenges ran against the exact requested remediation source, using the existing Windows Python 3.12.10 environment. No installation, model download, environment repair, full gate, qualification orchestration, long conversion or broad audit was performed.

## Identity, scope and preservation

| Item | Verified result |
|---|---|
| Branch | `feature/0.7.2-windows-hardening-verification` |
| Exact reviewed HEAD | `a943a26f9c5592e05631e27f21019d0250aa28c4` |
| Comparison base | `4119d861a207ac4d0011acbeaf8c7ec006668d29` |
| Original report commit retained in ancestry | `664353ced520ea558cd1a633337964b3df750c84`; `git merge-base --is-ancestor` exit 0 |
| Original publication-blocker addendum retained in ancestry | `4119d861a207ac4d0011acbeaf8c7ec006668d29`; ancestry exit 0 |
| Actual comparison | One remediation commit; 21 changed files, including five application files and one staging-measurement harness file |
| New evidence root | `files/run-temp/p9-focused-a943a26-20261112/` |
| Git deliverable | This Markdown report only; local report commit SHA returned separately |

Read the project instructions (`AI-WORKSPACE.md`, `.ai/AGENTS.md`, `.claude/CLAUDE.md`), relevant current canonical-document records, roadmap containment/freshness and Phase 9/10 requirements, and both requested Phase 9 reports. The user's present instructions supersede the roadmap's broad review/gate and reviewer no-commit requirements. Handoff, coverage, policies and issue statuses were left unchanged.

Inspected actual changes to `scripts/tts/pdf_extractor.py`, `files/dev-work/verification-gate/scaling/staging.py`, `scripts/shared/output_paths.py`, `scripts/mp3/mp3_plan.py`, `scripts/m4b/m4b_staging.py`, and `scripts/m4b/converter/m4b_converter.py`, plus their directly associated regression changes, including the worker-host and Maker fault-injection adjustments. Claude's reported PASS results were not used as proof.

The initial index was empty. Before report creation, the before/after `git status --porcelain=v1` matched exactly: the owner's fourteen tracked deletions and five untracked top-level entries remained. `git diff --exit-code HEAD -- scripts files/tests files/dev-work/verification-gate files/dev-work/feature-map` returned 0 after execution. Production code, tracked tests, verification policies, feature-map coverage and issue status were preserved. Writes were confined to new review evidence and this report, plus normal isolated test artifacts. No existing scratch/evidence tree, environment, cache, source audiobook or output was deliberately cleaned or changed. The existing test preservation guards passed; this is not a byte census of every owner asset.

## R9-01 — FAIL: original repeated-body-word case repaired; semantic closure still fails

**Reviewed functions:** `scripts/tts/pdf_extractor.py:170` (`_edge_lines`), especially lines 226–231; `:237` (`_furniture`, numeric grouping at lines 249–261); `:317` (`extract_text_from_pdf`).

**Independent real-PDF controls:** `probes.py` creates two-page PDFs with PyMuPDF and retains both raw page text and actual narration in `probes.json`.

- Repeated `NOT`, `I`, `FBI`, and `NASA` at the original body coordinates (y=80, 96, 160): both occurrences survive for every word. The original repeated-body-word reproduction is independently closed.
- A genuine repeated `IV` head at y=30 and counting folios 12/13 at y=805 are removed while body `NOT` survives.
- An unfinished sentence at y=620 continuing into `NOT` at y=750 preserves both negations. This exercises meaningful bottom-margin content.
- A running head at y=115, outside the top eighth, is narrated twice. That is harmless extra narration, not a semantic-deletion finding.
- Non-counting meaningful numbers 1984/9001 survive in the same geometry as the failure below.

**HIGH remaining semantic-loss reproduction:** create two 595×842-point pages. On each, insert `The required access code is` at `(72, 620)`, fontsize 11; insert its required code at `(72, 750)`, same size. Page one has `1984`, page two `1985`. There are no running heads or page numbers. Save a real PDF and call the actual `extract_text_from_pdf`.

Expected: `The required access code is 1984 The required access code is 1985` (whitespace aside). Actual, exactly:

```text
The required access code is The required access code is
```

Both codes are present in the raw PDF text. `_edge_lines` recognizes that the sentence runs into the margin line, but explicitly exempts bare numbers from its continuation protection. `_furniture` then treats their coincidental progression as folios. Changing only the second code to `9001` retains both numbers, isolating the counting rule. This is meaningful content lost, not an unwanted running head narrated. It is a residual classifier defect, not evidence that the patch added new deletions.

**Focused regressions:** 8 selected PDF cases passed. They do not cover this numeric continuation case. Evidence: `meaningful-numbers-lost.pdf`, `meaningful-numbers-control.pdf`, raw text/results in `probes.json`. Testing in this area stopped after the material reproduction.

**Closure:** exact old repeated-body-word defect **closed**; R9-01's requested semantic-preservation closure **FAIL**. ACT72-070 must not be accepted as fully repaired on this review.

## R9-02 — PASS within focused scope: filename reuse fails closed

**Reviewed functions:** `files/dev-work/verification-gate/scaling/staging.py:105` (`DirectoryWatch._run`), `:253` (`StagingCensus._before`), `:343` (`read`), `:392` (`record`); unchanged judge `scaling/qualify.py:443` (`resource_checks`) and `:544` (`staging_problems`).

**Independent reproduction:** a fresh census with the real audit hook and real Windows `ReadDirectoryChangesW`; parent exclusively creates/writes/removes a 100-byte temporary. In attack cases, a separate bounded Python child creates a 200,100-byte file, stats its size and removes it, either reusing the parent's name or using a fresh name. The parent then stages/renames a separate 100-byte final output. Equal-length clean/reuse/fresh base paths avoid diagnostics-path confounding. The unmodified `resource_checks` judges T5 against the clean baseline. No FFmpeg is launched; ancillary T4 inputs are interface fixtures, not a T4 qualification claim.

| Case | Child witness | Census peak | Actual / expected T5 |
|---|---:|---:|---|
| Clean | none | 100 bytes | PASS / PASS; no problems |
| Reused filename | 200,100 bytes | 100 bytes | FAIL / FAIL; 2 endings, only 1 distinct announced file |
| Fresh unobserved filename | 200,100 bytes | 100 bytes | FAIL / FAIL; ending with no reading |

The original false PASS is independently closed. Event multiplicity is now a `Counter` per name, rather than a path set; announcements/readings use `(st_dev, st_ino)` identities per name. The retained record includes actual beginnings/endings and distinct-announcement counts. No obvious recurrence of the old permanent-name allowance was found in the bounded inspection.

Additional negative controls fail as expected: absent `unobserved` accounting, undrained watch, a lost event, sampler 101 against census 100, and a one-byte total increase (101 against the seeking budget of 100). A test-only removal of the finished watch's creation counters produces an explicit `temporaries nobody saw created` problem. That last resource-check call also reports unequal fixture-path lengths; the specific missing-creation diagnosis is independently present and is not inferred from its overall false result.

**Budget:** judge and verification-policy comparison is empty. T5 still requires peak total no higher than the seeking total, with zero increase allowance; the one-byte control proves that boundary. No polling, tolerance or policy was changed.

**Focused regressions:** 9 selected gate-contract cases passed: three real-watcher reuse/control cases, five missing-account fields and the exact-figures/completeness check. Independent records and judge results are in `probes.json`.

**Limits:** the identity/count account is conservative, not a fully ordered lifetime log. Rename-away-and-back can fail closed. The documented grow/shrink-through-an-existing-child-handle blind spot remains outside this reproduction. **T5 on real FFmpeg scaling runs is still outstanding for the changed census.** This PASS closes R9-02's reproduced filename-reuse defect, not all scaling qualification or release readiness.

## R9-03 — FAIL: forward no-clobber repaired; MP3 rollback race reproduced

**Reviewed functions:** `scripts/shared/output_paths.py:1063` (`move_without_replacing`), `:1088` (`publish_new`); `scripts/m4b/m4b_staging.py:155` (`publish_staged`); `scripts/mp3/mp3_plan.py:408` (`_identity`), `:414` (`publish_book`), specifically identity check `:452` and rollback move `:455`. Maker and Metadata publication adapters at `scripts/m4b/maker/m4b_maker_processing.py:551` and `scripts/m4b/metadata/m4b_metadata_processing.py:179` both delegate to the inspected staging helper.

**Independent forward-publication controls:** tiny owned plan-shaped fixtures invoke the real publishers. Collision injection wraps the new `move_without_replacing` boundary and then calls its real Windows `os.rename`; it does not target the obsolete `os.replace` hook. MP3 one-output and three-output cases preserve competing bytes, preserve/restore ACT staging and successfully retry once the occupied name is freed. Shared Maker/Metadata staging preserves competing bytes on both same-volume and simulated `EXDEV` paths; cross-volume final publication uses the actual temporary-sibling/no-clobber route, leaves no temporary sibling after refusal, and succeeds on retry. Maker/Metadata engine/media processing was not exercised.

**HIGH remaining data-safety defect — deterministic rollback schedule:**

1. Stage two MP3 outputs in an owned `.work/Book` layout. Publish output 0 normally.
2. Inject a failure immediately before output 1's new publication primitive, making `publish_book` enter rollback.
3. Allow actual `_identity(output_0)` to return ACT's original file identity. A wrapper only records that return; it does not change the result.
4. At entry to the rollback's `move_without_replacing(output_0, staged_0)`, after the identity comparison already passed, schedule the competing writer's real `os.replace` of output 0 with a separately created file containing `COMPETING WRITER UNIQUE BYTES`.
5. Call the real no-clobber move. It moves the file currently named by output 0, which is now the competitor's file.

**Expected:** competitor remains at its intended published pathname; rollback must not appropriate another writer's file. **Actual:** published output 0 disappears, the competitor's bytes appear at private `.work/Book/0.mp3`, the now-empty Book destination directory is removed, and the error says `publishing Book failed and was rolled back: second output publication failed`.

The trace retained in `probes.json` is:

```text
rollback identity read: ACT original
competing writer replaces first output after identity decision
real no-clobber rollback moves current first output
```

This is **HIGH**, a release-blocking data-safety defect: the competitor loses its intended pathname and ACT adopts its bytes as retry staging. The bytes surviving the immediate move does not make it safe. Source inspection of `discard_staging` (`mp3_plan.py:472`), `_remove_entries`, and `release_staging` (`:529`) shows that private staging is later eligible for deletion; retry can also publish the wrong bytes. Those later consequences were not executed. The displaced competitor remains preserved in the evidence tree. A second unlocked identity check would merely move the race; safe rollback needs identity protection covering the namespace operation or a conservative refusal strategy.

The existing replaced-output regression only replaces the file **before** rollback checks identity, so it passes while missing this interval. No further publication-area tests were added or run after the material reproduction.

**Focused regressions:** 3 staging cases and 4 MP3 cases passed, including same/cross-device collision, cross-device success, single-output collision, multi-output rollback/retry, replaced-earlier-output and move-failure rollback.

**Closure:** original competing-destination forward overwrite **closed on the exercised Windows routes**. R9-03 as a publication-and-rollback safety finding **FAIL**; ACT72-075 remains release-blocking. No unauthorized forward overwrite was observed, but rollback demonstrably removes a competing writer's file from its location.

## R9-04 — PASS within focused scope: Cancel and authorization have one order

**Reviewed functions:** `scripts/m4b/converter/m4b_converter.py:1290` (`cancel`), `:1311` (`_latch_cancel`), worker closure `:1822` (`authorize_publication`), `:2545` (`close`); controller `scripts/shared/job_control.py:1534` (`authorize_commit`).

**Independent schedules:** `closure_panel.py` uses the actual `M4BConverterUI`, actual `convert_worker`, actual controller, actual Cancel/Pause methods on the main thread and real filesystem publication. Existing fixture infrastructure isolates configuration/logging and stubs encoding. The new schedule assertions and hooks are review-owned scratch, not modifications of tracked tests. All synchronization waits and joins are bounded at five seconds.

| Schedule | Actual / expected |
|---|---|
| Cancel latch first, before controller hears Cancel | Authorization returns false with latch true; no output; CANCELLED / same |
| Authorization first; Cancel before filesystem publication | One commit in flight; `A.mp3` legitimately lands and remains; `B.mp3` never starts; CANCELLED / same |
| Cancel during controller authorization | Contention on the decision lock is witnessed; grant is `(true, latch false)`; Cancel then latches/returns; only `A.mp3` remains / same |
| Pause during final measurement, then resume | First output lands, second has not begun while PAUSED, cancellation stays false; resume finishes both, SUCCEEDED / same |

All worker threads joined, no commit remained in flight and no temporary remained. Cancel completed within the bounded schedule. The overlap intentionally waits for the active authorization decision, not filesystem I/O. Source inspection confirms the decision lock covers only event access and the controller's short condition-lock increment; neither publication nor a controller callback executes under it. No deadlock or persistent blocked cancellation was found in these interleavings.

**Focused regressions:** 8 selected publication-order cases passed. **Independent panel challenges:** 4 passed. Evidence: `panel.xml`, `panel-cancel-first.json`, `panel-authorization-first.json`, `panel-during-authorization.json`, `panel-pause.json`.

**Closure:** R9-04's event/controller interleaving is independently **closed** in the exercised actual-panel/controller scope. This does not certify native desktop interaction, latency under unrelated workload, or long narration.

## Execution record

From the repository root, using existing `.venv/Scripts/python.exe`:

```powershell
.venv/Scripts/python.exe -B -m pytest files/tests/test_pdf_text_cleaning.py files/tests/test_verification_gate_contract.py files/tests/test_m4b_staging.py files/tests/test_mp3_plan.py files/tests/test_m4b_publication_order.py -q -p no:cacheprovider --basetemp=files/run-temp/p9-focused-a943a26-20261112/pytest --junitxml=files/run-temp/p9-focused-a943a26-20261112/focused.xml -k "same_short_capitals or repeated_body_word or capitals_in_the_bottom_margin or numbers_that_count_up or number_on_a_line_of_its_own or reading_taken_for_one_file or record_that_does_not_say or t5_fails_without_exact or file_that_takes_the_name_after_the_look or cross_device_work_root_takes or file_that_takes_a_single or competitor_at_a_later or rollback_never_takes or publication_rolls_back_if or cancel_pressed_while_a_publication or cancel_latched_before_the_controller or cancel_between_the_authorization or pause_during_the_final_validation or cancel_during_a_books_final_validation"
.venv/Scripts/python.exe -B files/run-temp/p9-focused-a943a26-20261112/probes.py
.venv/Scripts/python.exe -B files/run-temp/p9-focused-a943a26-20261112/panel_runner.py
```

| Execution | Result |
|---|---|
| Selected tracked regressions | **32 passed, 415 deselected, 0 skipped**, 4.00 s; JUnit counts: PDF 8, gate-contract 9, staging 3, MP3 4, publication-order 8 |
| Independent PDF/T5/publication probes | Exit 0; assertions confirm expected repaired controls **and reproduce the two remaining defects**; this exit is not an application PASS |
| Independent actual-panel schedules | **4 passed, 0 skipped**, 1.98 s |

Both pytest runs reported only the existing pydub `audioop` deprecation warning. No run was repeated to increase confidence. The test selectors execute focused cases only; no qualification or `scripts/verify.py` was invoked. No test policy or exemption was changed.

Evidence is local/untracked and was preserved, including the displaced competitor. `manifest.json` records hashes of the probe sources, results, PDFs and JUnit. Key SHA-256 values:

| Artifact under evidence root | SHA-256 |
|---|---|
| `probes.json` | `2570debe39f55a597c2df091314b6258fe73c06f9d1068f0008f7a0e0a819a5e` |
| `focused.xml` | `2cf11c0d862c47e091017838409aa9e280909f635b1ef52faad64b4aa83c755f` |
| `panel.xml` | `91217f6d442817abfba9a1f1c555c482491013c0896c8dba8a00ae28c8cf9a3f` |

## Release blockers and separate open gates

1. **ACT72-070 / R9-01:** meaningful numeric margin content is still deleted. Needs bounded remediation and independent closure; the old repeated body capitals case alone is repaired.
2. **ACT72-075 / R9-03:** HIGH MP3 rollback identity-to-move race remains. Competitor bytes must stay at their intended location, not be taken into ACT staging. Needs remediation and independent closure.
3. **T5 real-FFmpeg qualification:** the changed census still needs applicable `m4b-scaling` qualification. No part of its 207-run qualification was run here. Historical PASS evidence on `3aa421a` does not qualify the repaired census at `a943a26`.
4. **Native Windows GUI/current-source gate:** NOT RUN. The short actual-panel tests use stubbed media and do not replace the accessible interactive-desktop native GUI gate or full applicable verification. No desktop screenshots, input journey matrix or visual-baseline approval was attempted.
5. **ACT72-064 and owner acceptance:** its five documented limits still need individual owner decisions: narrated long/mixed-case heads; unrepeated furniture narrated; compound hyphen loss; pauses around page-boundary capitals; standalone drop-capital narration. Deeper running heads and continuation-adjacent footer heads add harmless extra narration risks described by remediation. Ambiguous repeated short capitals in the margin remain a source-level deletion risk. The reproduced lost access codes are a correctness defect under R9-01, not a harmless ACT72-064 limitation to waive as a group.
6. **Other manual/release gates:** representative narration/endings listening, personal UX judgment, native Cancel/Pause observation, remaining visual baselines, applicable fresh-launch/repair and qualification freshness/compatibility/packaging checks, followed by explicit owner acceptance/integration authorization, remain outside this review. `fresh-windows`, optional-engine, low-memory and other-platform qualifications were not run. No claim is made that this review establishes those gates for this source. ACT72-030 remains an owner-deferred maintenance suggestion, not a newly asserted release blocker.

No issue statuses were edited. R9-02/R9-04's focused PASS results do not close unrelated gates. No merge, tag, release, Phase 10 or v0.8.0 work was started.

## Git disposition and stop

The execution environment has `SSH_CONNECTION` present. The prior report records broken GitHub authentication in this SSH context. Following the user's explicit instruction, this review does **not** retry pushing, inspect/repair credentials, fetch through that authentication path or change any remote. GitHub publication remains **pending**; the authenticated Claude Code desktop session can publish the exact local report-only commit later.

Only `files/dev-work/phase9-remote-review/PHASE9-CODEX-FOCUSED-CLOSURE.md` is authorized for scoped force-add and commit. Its commit SHA is returned outside the file because a commit cannot contain its own SHA. Stop after that report-only commit. **FOCUSED CLOSURE FAIL.**
