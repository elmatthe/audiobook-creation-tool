# ACT v0.7.2 — Phase 9 targeted remediation of the independent remote re-review

**TARGETED CHECKPOINT ONLY. Focused regressions were run; the full Windows gate, the qualifications and the native GUI journeys were NOT run. Full Phase 9 PASS is not claimed. Ready for a focused independent Codex re-review.**

Date: 2026-11-12. Implementer: Claude Code on HOME-PC. Branch `feature/0.7.2-windows-hardening-verification`.

| Item | Value |
|---|---|
| Review answered | `files/dev-work/phase9-remote-review/PHASE9-CODEX-REMOTE-REVIEW.md` (Codex commits `664353c`, `4119d86`; preserved unchanged in ancestry) |
| Reviewed HEAD | `dd8fb1f` (code identical to `3aa421a`) |
| Starting commit of this work | `4119d86` |
| This checkpoint | the commit that adds this report (a commit cannot carry its own SHA) |

## Reproduction before any change

Copies of Codex's three probe scripts were run unmodified on `4119d86` from a new folder, `files/run-temp/p9c-before/` (Codex's evidence root was not touched). Every finding reproduced exactly as reported:

| Finding | Before the fix (`4119d86`) |
|---|---|
| R9-01 | repeated body `NOT` on two pages: `not_count` 0, text `The next command is The signal has been checked.` ...; `NASA` control kept |
| R9-02 | reused-name child transient: witnessed 200,100 bytes, census peak 100, problems `[]`, **T5 ok: true**; fresh name: FAIL (correct) |
| R9-03 | MP3 `publish_book` and Maker `publish_staged`: returned success, destination `new output`, `competitor_preserved: false` |
| R9-04 | `event check returned false` / `actual cancel reached controller with event True` / `controller authorized True with event True` / `worker published` |

## R9-01 — PDF semantic content loss (ACT72-070, P9-01)

- **Codex finding.** A short line of capitals in the body of a page (`NOT` at y=160 on PyMuPDF's default 842-pt page) that stands clear of the line before it and repeats at the same height on another page is deleted from both pages as a running head.
- **Root cause.** `_edge_lines` called the page's lowest (or highest) written line an edge line whenever it stood clear of its neighbour by more than 1.5 line pitches, wherever that was on the page. On a short page the lowest line is simply the end of the text, and `_furniture` then deleted any one-to-four-capital edge line repeated at the same height. Nothing tied a candidate to the page's margin.
- **Changed.** `scripts/tts/pdf_extractor.py`: new `_MARGIN = 0.125`; `_edge_lines`.
- **Correction.** A furniture candidate must now stand in the page's actual margin: its baseline within the top or bottom eighth of the page's height (`layout["height"]` from the same text page; without it, nothing on the page is a candidate and all text is kept). And at the foot, a line that the sentence above it runs into (that line does not end with `. ! ? : ) " ' —`) is that sentence's word unless it is a bare number (page numbers are still decided by counting across pages). `_furniture` is unchanged. Every change only removes deletion; none adds any.
- **Regressions** (`files/tests/test_pdf_text_cleaning.py`, real PDFs through `extract_text_from_pdf`):
  - `test_the_same_short_capitals_in_the_body_of_two_pages_are_read_on_both[NOT|I|FBI|NASA]`: Codex's exact pages (positions 80, 96, 160, default page): both occurrences kept.
  - `test_a_repeated_body_word_is_read_while_the_running_head_and_page_numbers_in_the_margins_are_not`: positive control; head `IV` and folios 12/13 still removed beside a repeated body `NOT`.
  - `test_capitals_in_the_bottom_margin_that_a_sentence_runs_into_are_read_and_a_running_head_there_is_not`: bottom-margin `NOT` after `The next command is` kept; bottom-margin `IV` after a finished sentence still removed.
  - Changed expectation, stated openly: in `test_only_a_line_that_stands_clear_at_the_top_or_bottom_of_its_page_can_be_furniture`, a single body line alone on its page at y=90 of 648 is no longer even a candidate (`[]` instead of `["One line only."]`). Before, only its not repeating kept it.
- **Result: PASS.** Module 56 passed. Control: with `_edge_lines` from `4119d86` put back in-process, 6 of the 7 new/changed tests fail (all four words, the bottom-margin case, the changed geometry expectation) and the furniture positive control passes. Codex's probe on the fixed code: `not_count` 2, `NASA` control unchanged. Worker sizing and the speech extraction golden: 10 passed.
- **Remaining risks.** The margin band is a heuristic: a running head set deeper than an eighth of the page is now narrated (errs to narration). A 1–4-capital line inside the band, clear of the text, repeated at the same height and not run into by a sentence (top of the page, or under a finished sentence at the foot) is still taken for furniture, because on the page it is indistinguishable from a running head. New narration-side limit for the owner: a running head of capitals printed at the foot is now read out when the page's last sentence runs into it. These join ACT72-064's limits for the owner; no `test_limit_*` was added for them.

## R9-02 — T5 false PASS after filename reuse (ACT72-073, P9-04)

- **Codex finding.** A path whose first file was legitimately read and announced was reused by a child for a 200,100-byte transient; the census reported peak 100 and no problem, and the unchanged T5 judge passed.
- **Root cause.** The producer, not the judge. `DirectoryWatch` collapsed Windows' reports into sets of paths, and `StagingCensus` kept `_announced` (and `_may_shrink`, `_ever`) as sets of paths, permanently. `record()` compared distinct removed paths with distinct announced paths, so one announcement vouched for every later file at that name, and a second removal at a name was invisible.
- **Changed.** `files/dev-work/verification-gate/scaling/staging.py` (gate harness; T5's judge `qualify.py` unchanged).
- **Correction.** `DirectoryWatch` also counts every report per name (`began`: added or renamed-to; `ended`: removed or renamed-away). Each reading records which file each temporary is (`(st_dev, st_ino)`). An announcement, a truncation allowance and "seen by a reading" are kept per file at each name, never for the name: `_before` takes its reading and records the identity under one lock; a name holding a different file at the next reading counts as the earlier file gone; `record()` requires, for every name, as many distinct announced files as Windows reported endings, and as many reported beginnings as distinct files read. Anything that cannot be reconciled fails closed (it is an `unobserved` problem, which T5 refuses). The zero-increase budget, polling and the judge are untouched.
- **Regression.** `files/tests/test_verification_gate_contract.py::test_a_reading_taken_for_one_file_never_vouches_for_a_later_file_of_the_same_name[the-control|a-name-a-reading-was-taken-for|a-name-never-read]`: Codex's three cases on real files with the real audit hook and real `ReadDirectoryChangesW`, judged through `qualify.staging_problems`. Control PASS at the unchanged budget (96,656 against 96,656); reused name FAIL (`... removed or renamed 2 times ... a reading was taken for only 1 ...`); never-read name FAIL.
- **Result: PASS.** Whole module `test_verification_gate_contract.py`: 298 passed. Control: with `4119d86`'s `staging.py` loaded in its place, only the reused-name case fails. Codex's `staging_judge.py` on the fixed code: control `ok: true`; reuse `ok: false` (was true); fresh `ok: false`.
- **Remaining risks.** Not run: the `m4b-scaling` qualification (deliberately, by instruction), so the repaired census has not yet read a full real FFmpeg run. If real runs show a reporting pattern not exercised here (a replaced name reported once more than it was announced, for example), T5 would fail closed and the scenario would have to be rerun after review, never pass falsely. A file renamed away and back to the same name counts as two files with one reading and fails (the application does not do this). A volume without stable file ids collapses files to one identity, which can only make the endings check stricter. The documented limit is unchanged: a file grown and shortened through one handle wholly between two readings by another process cannot be seen.

## R9-03 — MP3 Tool and M4B staging overwrite a competing destination (ACT72-075)

- **Codex finding.** Both `mp3_plan.publish_book` and `m4b_staging.publish_staged` checked the destination and then moved with `os.replace`; a file created at the destination between the two was destroyed and success was reported. The cross-device route used `atomic_replace` likewise.
- **Root cause.** Look-then-replace: `exists()` followed by `os.replace` (and `output_paths.atomic_replace` on the cross-device route). The Converter's `publish_new` (P9-05) was not used by these callers, and its prefix check refuses staged names.
- **Changed.** `scripts/shared/output_paths.py`: new `move_without_replacing(source, destination)`, the primitive `publish_new` already used (Windows `os.rename` = `MoveFileExW` without `MOVEFILE_REPLACE_EXISTING`; elsewhere `os.link` then unlink), now shared, with `publish_new` delegating to it unchanged in behaviour. `scripts/m4b/m4b_staging.py`: `publish_staged` moves with it, maps a taken name to `StagingError("... already exists; nothing was published")`, and its cross-device route gives the temporary sibling its name through `publish_new` (discarding the sibling if refused). `scripts/mp3/mp3_plan.py`: `publish_book` moves each output with it; the roll-back moves back only a file that is still the very file this attempt moved (`_identity`, `(st_dev, st_ino)` recorded before the move), reports any output it could not take back, and removes the Book folder only if this attempt made it (still `rmdir` only when empty). `atomic_replace` is unchanged and stays the explicit, confirmed in-place replacement; nothing that used it for that purpose was touched.
- **Regressions.** `test_m4b_staging.py::test_a_file_that_takes_the_name_after_the_look_is_kept_and_nothing_is_published[same-device|cross-device]` (competitor planted after the look, immediately before the real operation; competitor bytes intact, staged file kept, no sibling left, and a retry publishes once the name is free). `test_mp3_plan.py`: `test_a_file_that_takes_a_single_outputs_name_after_the_look_is_kept`, `test_a_competitor_at_a_later_outputs_name_rolls_back_only_this_attempts_outputs_and_a_retry_then_lands` (multi-output roll-back, a stranger's file in a folder the attempt did not make is kept, retry lands), `test_a_rollback_never_takes_back_a_file_that_is_no_longer_the_one_it_published`. Existing fault-injection tests that patched `os.replace` now inject at `output_paths.move_without_replacing` with the same assertions (`test_publication_rolls_back_if_a_move_fails_midway`, both cross-device tests in `test_m4b_staging.py`, `test_publication_survives_a_cross_device_work_root` in `test_m4b_maker_processing.py`); the purity test now requires the no-clobber calls and forbids `os.replace`, `os.rename`, `shutil.move` and `atomic_replace` in `m4b_staging.py`.
- **Result: PASS.** `test_m4b_staging.py` + `test_mp3_plan.py`: 60 passed, 4 skipped (this account cannot create file or directory symlinks; pre-existing). Maker/MP3/Metadata staging-release modules, the Maker cross-device test and the Converter host tests: 34 passed. Controls: with `move_without_replacing` replaced in-process by `os.replace`, all 5 collision tests fail; with `_identity` made constant, the replaced-output test fails. Codex's probe, with its injection moved to the operation the fixed code performs (`os.rename`; its original `os.replace` hook is no longer reached): MP3 `REFUSED PlanError ... was taken after the run was planned, and was not replaced`, Maker `REFUSED StagingError ... already exists; nothing was published`, both `competitor_preserved: true`, staged `new output` kept.
- **Remaining risks.** The MP3 roll-back's identity check and its move back are two steps; a writer replacing the published file in between could still be moved into private staging (never deleted, never replaced). Outside Windows the move needs hard links (FAT/exFAT have none; it fails clearly); macOS was not exercised. `mp3_plan.is_published` remains a name-only check, used by no production code.

## R9-04 — Cancel versus commit authorization in the Converter (ACT72-071, P9-02 residual)

- **Codex finding.** `cancel()` set the panel's `_cancel_event` outside any lock, and `authorize_publication` read that event and then separately called `controller.authorize_commit()`. A worker that read the event clear could be granted the commit after Cancel had latched the event but before the controller heard of it, and publish.
- **Root cause.** Two separate decisions with no shared ordering: the panel event (no lock) and the controller flag (the controller's lock). The controller ordered only its own flag against authorization.
- **Changed.** `scripts/m4b/converter/m4b_converter.py`: `self._cancel_decision = threading.Lock()`; new `_latch_cancel()` sets the event under that lock and is used by `cancel()` and `close()`; `authorize_publication` holds the same lock across its event check and `controller.authorize_commit()`, and returns before any filesystem operation.
- **Correction.** One linearization point: a Cancel whose latch is set first makes every later decision a refusal (nothing published, the run cancels); a decision under way completes first and is the legitimate commit-first case (the controller already counts it in flight, `finish_cancelled` waits for `commit_finished`, that one output stays, nothing after it starts). The lock covers only setting an event and one uncontended controller lock acquisition: Cancel stays prompt, does not wait for any saving or finalizing, and Pause is untouched.
- **Regressions** (`files/tests/test_m4b_publication_order.py`, real panel, real worker thread, real controller, Cancel pressed on the main thread, no sleeps):
  - `test_cancel_pressed_while_a_publication_is_being_authorized_waits_for_that_decision_and_the_commit_stays`: Codex's interleaving. The worker is held inside the controller's authorization after reading the latch clear, and is released only by Cancel having to wait for the decision lock. Asserts the grant happened with the latch clear (`[(True, False)]`), Cancel waited, `A.mp3` stays, run CANCELLED, no book after, no temporaries, nothing in flight.
  - `test_a_cancel_latched_before_the_controller_hears_of_it_already_refuses_the_next_authorization`: Codex's order the other way: latch set, worker decides before the controller hears; decision `[False]`, nothing published, run CANCELLED.
  - Two structural guards learned the new attribute (it is a lock, not a widget): `test_m4b_conversion_plan.py::test_the_worker_reads_no_widget` allows `_cancel_decision`; the minimal worker host `_Q` in `test_tool_output_integration.py` carries one.
- **Result: PASS.** Whole module: 30 passed (the existing Cancel-during-validation, commit-first, Pause, last-book, retry and real-FFmpeg journey tests included). Control: with `_latch_cancel` put back to setting the event without the lock, the interleaving test fails with `Cancel latched without waiting for the authorization under way`; the latch-first test passes (as it did before). Codex's `cancel_actual.py` was not re-run on the fixed code: it emulates the old lock-free `cancel()` on a stub panel, and against the fix that interleaving cannot be constructed (its Cancel would block on the decision lock).
- **Remaining risks.** Not run on the interactive native desktop or through the GUI journeys (by instruction); the panel tests drive the real panel with a stubbed encoder, and the module's real-FFmpeg journeys ran.

## Meta-guards and inventory

- `inventory.py check` reported the five changed application files as changed since review. Their features' entries and the feature map were reviewed; four sentences that described the pre-fix rules were updated (`files/dev-work/feature-map/tts-audiobook.md`, `m4b-converter.md`, `shared-workflows.md`, `mp3-tool.md`), and the five files were restamped with `inventory.py restamp <the five paths>` (5 stamp lines changed). Check afterwards: 0 problems, 273 features.
- Issue ledger (`files/dev-work/verification-gate/coverage.json`): ACT72-070, -071 and -073 set back to **open** with a `reopened` note (Codex: keep them open rather than treat passing regressions as closure); ACT72-075 stays **open** with its reproduction and a `repaired` note. All four remain open until an independent re-review confirms them.
- Source-reading guards run: `test_application_source_boundary`, `test_plan3_boundaries`, `test_plan6_boundaries`, `test_m4b_structural_authority`, `test_output_paths`, `test_chatterbox_boundaries`, `test_epub_retirement`, the MP3 one-authority test and the `test_m4b_retry` output-paths guard: 847 passed, 2 skipped. Readers of `coverage.json` and the feature map (`test_verification_coverage`, `test_surface_discovery`, `test_dev_work_isolation`, `test_release_packaging`, `test_verify_evidence`): 269 passed, 1 skipped. No changed file is in the guarded v3-planning `SOURCES` closure.

## Exact commands (repository root, `.venv/Scripts/python.exe -B -m pytest ... -q -p no:cacheprovider`, default basetemp)

| Command target | Result |
|---|---|
| `files/tests/test_pdf_text_cleaning.py` | 56 passed |
| `files/tests/test_m4b_staging.py files/tests/test_mp3_plan.py files/tests/test_m4b_conversion_plan.py::test_the_worker_reads_no_widget` | 60 passed, 4 skipped |
| `files/tests/test_m4b_publication_order.py` | 30 passed |
| three Converter-host tests in `test_tool_output_integration.py`, `test_m4b_maker_processing.py::test_publication_survives_a_cross_device_work_root`, `test_maker_staging_release.py`, `test_mp3_staging_release.py`, `test_metadata_staging_release.py` | 34 passed |
| `files/tests/test_verification_gate_contract.py` (whole) | 298 passed (323 s) |
| `files/tests/test_worker_limits.py files/tests/test_speech_characterization.py -k "pdf or PDF or extraction"` | 10 passed |
| meta-guards listed above | 847 passed, 2 skipped |
| coverage and feature-map readers listed above | 269 passed, 1 skipped |
| mutation controls (scratch runner, in-process, working tree never edited) | each new regression fails against the pre-fix behaviour as stated per finding |

Skips are environmental and pre-existing (symlink privilege). The single warning in each run is pydub's `audioop` deprecation.

Before/after evidence (untracked, disposable, owner's to remove): `files/run-temp/p9c-before/` (Codex's probes on `4119d86`), `files/run-temp/p9c-after/`, `p9c-after2/`, `p9c-after3/` (the same probes on the fixed code; `p9c-after` shows the original `os.replace` hook no longer reached, `p9c-after3` the moved injection with refusals captured).

## Deliberately not run

The full Windows verification gate; the ~15,000-test suite; the native GUI journey matrix; `m4b-scaling` (T5 on real FFmpeg runs included), `fresh-windows`, `optional-engines` and `edge-low-memory` qualifications; the guarded test groups; long real conversions; macOS. The PASS records on `3aa421a` do not cover this checkpoint's code.

## Preservation

Only the files named in this report were staged. The owner's 14 tracked deletions and untracked entries (`.ai/`, the v0.8.0 plan, `files/plans/reference-handoff-of-mc-answers/`, `files/run-temp/`, `scripts/project-status.py`) were not staged, restored or changed. Codex's report and evidence root are unchanged. No reset, clean, restore, force push or history rewrite. No merge, tag, release, Phase 10 or v0.8.0 work.

## Recommendation

Ready for a focused independent Codex re-review of R9-01 to R9-04 at this checkpoint. After it, the applicable Windows gate and the affected qualifications (at least `m4b-scaling` for T5) belong on an accessible interactive desktop, on the owner's word.
