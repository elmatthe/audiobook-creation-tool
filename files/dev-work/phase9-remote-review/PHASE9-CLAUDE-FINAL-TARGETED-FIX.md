# ACT v0.7.2 — Phase 9 final targeted fix: R9-01 numbers and R9-03 roll-back

**TARGETED CHECKPOINT ONLY. Two findings repaired with focused tests and mutation controls. No gate, no qualification, no native journey was run. ACT72-070 and ACT72-075 stay OPEN pending independent Codex confirmation. Full Phase 9 PASS is not claimed.**

Date: 2026-11-12. Implementer: Claude Code on HOME-PC. Branch `feature/0.7.2-windows-hardening-verification`.

| Item | Value |
|---|---|
| Review answered | `files/dev-work/phase9-remote-review/PHASE9-CODEX-FOCUSED-CLOSURE.md` (Codex report-only commit `3f02d4c`, unchanged, in ancestry) |
| Reviewed code | `a943a26` (code unchanged by `3f02d4c`) |
| Starting HEAD | `3f02d4c` |
| This checkpoint | the commit that adds this report |
| Out of scope, untouched | R9-02 (T5 census) and R9-04 (Converter Cancel), both PASS in the focused closure; `output_paths`, `m4b_staging`, the Converter |

## Codex's reproductions, run unchanged on `3f02d4c` before any edit

A copy of Codex's `probes.py`, limited to its PDF and publication challenges, was run from a new folder, `files/run-temp/p9g-before/` (Codex's evidence root is untouched). Both findings reproduced exactly:

| Finding | Before the fix |
|---|---|
| R9-01 | raw text holds both codes (`The required access code is \| 1984`, `... \| 1985`); narration: `The required access code is The required access code is`. Control 1984/9001: both kept. |
| R9-03 | trace `rollback identity read: ACT original` / `competing writer replaces first output after identity decision` / `real no-clobber rollback moves current first output`; competitor's bytes at `.work/Book/0.mp3`; output 0's name empty; Book folder removed; error `publishing Book failed and was rolled back: second output publication failed`. |

## R9-01 — meaningful numbers lost as page numbers (ACT72-070)

- **Codex reproduction.** Two 595x842 pages, `The required access code is` at (72, 620) and its code at (72, 750), both size 11; `1984` on page 1, `1985` on page 2; no heads, no folios. Both codes vanished.
- **Root cause.** The bare-number exception in `_edge_lines` (`if runs_into and not _PAGE_NUMBER.fullmatch(row[1]): continue`) is necessary (a real page number under an unfinished sentence must stay a candidate, as the 300-page test shows), but it threw away the evidence it had just computed: that the sentence above runs into the number. `_furniture` then judged the numbers by counting alone, and 1984 on page 0 and 1985 on page 1 count exactly like folios. Codex's 9001 control isolated the counting rule.
- **Correction** (`scripts/tts/pdf_extractor.py`):
  - `_EdgeLine` gains `in_sentence: bool = False` (line 170): a bare number at the foot that the sentence above runs into, set as large as that sentence.
  - `_edge_lines` (lines 238–239) sets it: `runs_into and not row[5] < text_size - _SIZE_SLACK`.
  - `_furniture` (line 264): a counting run is page furniture only if at least one member stands apart from the text (not `in_sentence`: under a finished sentence, alone on its page, at the top, or set smaller than the text). A run whose every member is run into by its sentence and set as the text is kept as text.
  - The bare-number exception itself stays; nothing else in extraction changed; the speech normalization pipeline was not touched.
- **Why this evidence.** Typography and sentence continuation are what the page offers. A book's run of page numbers almost always includes a page under a finished sentence or is set smaller than the text, and then the whole run, including its numbers under unfinished sentences, is still removed. Horizontal position and value were rejected: Codex's own furniture control puts folios at x=72, and journal pages run into the thousands.
- **Regressions** (`files/tests/test_pdf_text_cleaning.py`, real PDFs, text checked before speech normalization), on Codex's geometry with one thing changed per case:
  - A/B/C `test_numbers_that_sentences_run_into_are_read_even_when_they_count_with_their_pages[the-reviewers-codes|an-answer|three-pages]`: 1984/1985, 42/43, 1984/1985/1986 under `The required access code is`: all kept.
  - B `test_numbers_that_do_not_count_with_their_pages_are_read_in_the_same_place`: Codex's 1984/9001 control: kept.
  - D `test_page_numbers_in_the_same_place_are_still_taken_out[under-finished-sentences|one-page-under-a-finished-sentence|set-smaller-than-the-text]`: printed page numbers 198/199 in the same place are removed.
  - D/E/G `test_a_running_head_and_page_numbers_beside_numbers_of_the_text_are_told_apart`: head `IV` and folios 198/199 removed; `it: 1984.` in the text kept.
  - G (stated ambiguity) `test_ambiguous_a_year_alone_in_the_foot_margin_under_finished_sentences_is_taken_for_a_page_number`: a year alone in the foot margin under a finished sentence, counting with the next page's year, set as the text, is removed: it carries every mark of a page number. The same years not counting (1984/1990) are kept.
  - F, the repaired repeated-`NOT` case, and every existing furniture test (the 300-page book, sizing on a sample, the year over a page number) are unchanged and pass.
- **Old code reproduction:** FAIL as above. **Fixed code, same reproduction** (`files/run-temp/p9g-after/`): `The required access code is 1984 The required access code is 1985` (`semantic_loss: false`); 1984/9001 control unchanged; Codex's furniture control still removes `IV`, 12 and 13 and keeps `NOT`.
- **Mutation control** (`_furniture` from `3f02d4c` put back in-process): the 3 run-into cases fail; the 6 others (controls, page-number removal, ambiguity) pass on both. Restored: all pass.
- **Result: FIXED.** `test_pdf_text_cleaning.py`: 65 passed.
- **Remaining limitations.**
  - A same-size page-number run where every page ends mid-sentence, with no page under a finished sentence, is now read aloud (errs to narration). Likely only in very short excerpts.
  - Numbers that count with their pages, standing alone in the foot margin under finished sentences or set smaller than the text, are still removed when they were meant as content. This is a layout ambiguity, stated in a test.
  - In a mixed run, one member standing apart makes the whole run page numbers, including a member a sentence runs into.

## R9-03 — MP3 roll-back moves a competing writer's file (ACT72-075)

- **Codex reproduction.**
  1. Two outputs; output 0 is published, then output 1's publication fails.
  2. The roll-back reads output 0's identity by name: ACT's file.
  3. A competitor's real `os.replace` then puts its file at output 0's name.
  4. The roll-back's by-name no-clobber move takes the competitor's file into `.work/Book/0.mp3`.
- **Root cause.** `publish_book`'s roll-back made two independent decisions on a *name*: `_identity(published)` and then `move_without_replacing(published, staged)`. Nothing held the file between them, and a by-name move moves whatever the name holds at that instant. A second check just before the move only moves the gap; the control below shows it.
- **Correction** (`scripts/mp3/mp3_plan.py`):
  - `_take_back(published, staged, identity)` (line 479) replaces the by-name step in the roll-back loop (line 542).
  - On Windows (`_CAN_TAKE_BACK`, line 417):
    - `_open_held` (line 444) opens the published file with `CreateFileW(DELETE | FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE, FILE_FLAG_OPEN_REPARSE_POINT)`: delete-sharing is denied, so while held, no other program can rename, replace or delete it, and a link is never followed.
    - Its identity is read from that hold (`os.fstat`, the same `(st_dev, st_ino)` as the `os.lstat` recorded before the forward move).
    - `_rename_held` (line 463) renames the held file itself with `SetFileInformationByHandle(FileRenameInfo, ReplaceIfExists=0)`. That rename moves that file and nothing else, and refuses a taken staging name; the name is passed as UTF-16 bytes, so non-BMP characters size correctly.
    - A name replaced before the hold opens the other program's file; its identity is not ACT's, so it is left exactly where it is.
  - Elsewhere no operating-system rename can be bound to a file rather than a name, so `_take_back` returns False: the roll-back moves nothing.
  - Every output not taken back is named in the failure (`... could not be taken back and were left where they are`, line 556).
  - Forward publication (`move_without_replacing`), occupied-destination refusal, the folder rule (removed only if this attempt made it and it is empty), retry and frozen paths are unchanged. `output_paths`, `m4b_staging` and the Converter are untouched.
- **Primitive behaviour, measured before any production edit** (scratch probe, folder `files/run-temp/p9g-handle/`):
  - `os.lstat` and `os.fstat` on the hold report the same identity.
  - A competitor's `os.replace` onto the held file is refused (WinError 5), and a by-name rename of it is refused (WinError 32).
  - A handle rename onto a taken name is refused (183); onto a free name it succeeds, moving only the held file.
  - A name replaced before opening yields a different identity.
- **Regressions** (`files/tests/test_mp3_plan.py`; deterministic hooks, no sleeps):
  - A: `test_publish_moves_every_staged_output_into_the_book_folder` (existing).
  - B: `test_publication_rolls_back_if_a_move_fails_midway`. Existing; it now states the off-Windows outcome too.
  - C: `test_publish_never_overwrites_an_existing_published_file`, `test_a_file_that_takes_a_single_outputs_name_after_the_look_is_kept` (existing).
  - D: `test_a_rollback_never_takes_back_a_file_that_is_no_longer_the_one_it_published` (existing; the replacement happens before the roll-back).
  - E (new): `test_a_competitor_acting_after_the_rollbacks_identity_check_keeps_its_file_and_only_ours_comes_back`. This is Codex's schedule. The competitor's real `os.replace` runs after the identity decision and before the move, at whichever seam the implementation has: a by-name move (`move_without_replacing` from the published name) or `_rename_held`. It asserts:
    - the competitor acted once and was refused;
    - its file is still at its own path, byte for byte;
    - only ACT's own bytes came back to staging;
    - an unrelated file in the Book folder is untouched;
    - the retry then lands at the same planned names.
  - F/G: `test_a_competitor_at_a_later_outputs_name_rolls_back_only_this_attempts_outputs_and_a_retry_then_lands` (existing; unrelated file preserved; retry). Windows-only now, since elsewhere nothing is rolled back.
  - Off Windows (new, forced on any platform): `test_where_a_rollback_cannot_be_bound_to_the_file_it_moves_nothing`. What was published stays and is named; unmoved outputs stay staged.
- **Old code reproduction:** FAIL as above. **Fixed code, same reproduction** (`files/run-temp/p9g-after/`):
  - Setup: Codex's fixtures and its original hooks, plus its competitor placed at the fixed code's decision-to-move point. Its original by-name hook is no longer reached, because the roll-back no longer moves by name.
  - Trace: `rollback identity read on the held file: ACT original` / `competing writer replaces first output after identity decision` / `competitor replace refused: PermissionError winerror 5`.
  - The competitor's file is at its own path with `COMPETING WRITER UNIQUE BYTES`. `.work/Book/0.mp3` holds `ACT original 0.mp3`, ACT's own file; the probe's legacy keys `competitor_now_at` / `competitor_bytes` now label that file. The error reads `... rolled back: second output publication failed`.
  - All of Codex's forward-collision cases (MP3 1 and 3 outputs, Maker and Metadata same- and cross-device) still pass.
- **Mutation controls** (in-process, working tree never edited):
  1. `_take_back` replaced by the exact pre-fix step (identity by name, then a by-name move): test E fails (the competitor's replacement succeeds and its file is moved), and the off-Windows test fails. The other three roll-back tests pass on both.
  2. `_take_back` replaced by "read the identity on a hold, release it, then move by name", the recheck-just-before-the-move idea: test E fails. A recheck does not close the gap.
  3. No mutation: all 14 selected tests pass.
- **Result: FIXED on Windows.** `test_mp3_plan.py`: 47 passed, 2 skipped (this account cannot create symlinks; pre-existing). Off Windows the finding is closed by refusal, not repair (below).
- **Remaining limitations.**
  - **Off Windows (macOS, Linux)** no rename is bound to a file, so a failed publication there leaves its already-published outputs visible and names them in the error, instead of rolling back. A retry of that Book is then refused until they are removed. No partial publication is silent and nothing of anyone else's is moved; macOS was not run.
  - **While a roll-back holds a file**, a program trying to replace or delete it is refused for that moment.
  - **A file another program holds open without sharing deletion** cannot be held: it is left in place and reported.

## Exact commands (repository root, default basetemp)

| Command | Result |
|---|---|
| `.venv/Scripts/python.exe -B files/run-temp/p9g-before/probes.py` | both defects reproduced (above) |
| `.venv/Scripts/python.exe -B <scratch>/handle_probe.py <repo>/files/run-temp/p9g-handle` | primitive behaviour as above |
| `.venv/Scripts/python.exe -B -m pytest files/tests/test_pdf_text_cleaning.py -q -p no:cacheprovider` | 65 passed |
| `.venv/Scripts/python.exe -B -m pytest files/tests/test_mp3_plan.py -q -p no:cacheprovider` | 47 passed, 2 skipped |
| `.venv/Scripts/python.exe -B files/run-temp/p9g-after/probes.py` | both repaired (above) |
| scratch control runner, modes `pdf`, `rollback-by-name`, `hold-released-before-move`, `no-mutation` | 3 failed / 6 passed; 2 failed / 3 passed; 1 failed; 14 passed |

The single warning per pytest run is pydub's `audioop` deprecation. `files/run-temp/p9g-*` are untracked, disposable evidence.

Inventory: the two changed application files' feature-map sentences were updated (`files/dev-work/feature-map/tts-audiobook.md`, `mp3-tool.md`) and the two files restamped with `inventory.py restamp scripts/tts/pdf_extractor.py scripts/mp3/mp3_plan.py`; `inventory.py check` was not run (no sweep). Ledger: ACT72-070 and ACT72-075 notes extended; both stay open. ACT72-071 and ACT72-073 untouched.

## Deliberately not run

`scripts/verify.py` and the full gate; the full suite; the native GUI journeys; the M4B scaling benchmarks and every qualification; the T5, Converter and structural suites from the previous checkpoint; the shared `output_paths` tests (that primitive is unchanged); PDF worker-sizing tests outside `test_pdf_text_cleaning.py` (its two sizing tests ran); macOS.

## Preservation

Only the files named here were staged. The owner's 14 tracked deletions and untracked entries were not staged or touched. Codex's report and both evidence roots are unchanged. No reset, clean, restore, force push or history rewrite; no merge, tag, release, Phase 10 or v0.8.0 work.

## Recommendation

Ready for a focused independent Codex closure check of R9-01 and R9-03 at this checkpoint.
