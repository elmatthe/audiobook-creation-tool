# ACT v0.7.2 — Final focused independent closure

**FOCUSED CLOSURE PASS. R9-01 PASS; R9-03 PASS within the reviewed Windows scope.** The two previously reproduced defects are closed by the independently exercised behavior below. This closes only these findings within this scope; it is not full Phase 9 acceptance or release approval. R9-02 and R9-04 were not reopened or retested.

Review date: 2026-11-12. Role: independent Codex verifier. No implementation changes, installs, media conversions, qualification runs or full gate. Existing `.venv/Scripts/python.exe`: Python 3.12.10, Windows 11 build 26300, PyMuPDF 1.27.2.3.

## Source identity and scope

| Item | Verified result |
|---|---|
| Branch | `feature/0.7.2-windows-hardening-verification` |
| Exact reviewed HEAD | `a00f0a2b73068dae33b06fb1ae95083cc4251b4b` |
| Previous reviewed remediation | `a943a26f9c5592e05631e27f21019d0250aa28c4` |
| Prior Codex report-only commit preserved | `3f02d4c3feb3137c7ab6f6e735d14782d91b6c39`; ancestry exit 0; only the prior closure Markdown in that commit |
| Prior report unchanged thereafter | `git diff --exit-code 3f02d4c HEAD -- files/dev-work/phase9-remote-review/PHASE9-CODEX-FOCUSED-CLOSURE.md`: exit 0 |
| Comparison | Two commits, ten paths: prior report-only commit, then the final targeted remediation |
| Production changes | Only `scripts/tts/pdf_extractor.py` and `scripts/mp3/mp3_plan.py` |
| Other comparison paths | Their two tracked test modules, two feature-map descriptions, coverage notes/two source hashes, Handoff, and the two reports |
| Accepted code unchanged | Diff against `a943a26` for scaling/T5, Converter, shared `output_paths.py` and `m4b_staging.py`: empty, exit 0 |
| New evidence root | `files/run-temp/p9-final-a00f0a2-20261112-codex/` |

Read applicable `AI-WORKSPACE.md`, agent guidance, the current Handoff block, and both requested reports completely. No root/ancestor `AGENTS.md` was found; `.ai/AGENTS.md` and the Claude entrypoint were inspected. No active instruction drop exists. The current user instruction takes precedence over generic full-gate, Handoff-edit, implementation/delegation and publication workflows. The review stayed independent and local; no authentication or remote operation was attempted.

The initial index was empty. Owner state comprised fourteen tracked deletions and five untracked top-level entries. Before report creation, the before/after `git status --porcelain=v1` matched exactly. `git diff --exit-code HEAD -- scripts files/tests files/dev-work/verification-gate files/dev-work/feature-map` returned 0, and `git diff --check` was clean. The prior reports/evidence, deletions and untracked work were preserved. Writes were limited to this new evidence directory, normal isolated test artifacts, and this report. Existing production-state test guards passed; this is not a byte census of owner libraries and caches. No application code, tracked tests, rules, issue statuses, Handoff or other project documentation was edited by this review.

## R9-01 — PASS: numerical continuation preserved before normalization

Source: `scripts/tts/pdf_extractor.py:160` (`_EdgeLine`; `in_sentence` at line 170), `:173` (`_edge_lines`, assignment at `:238`), `:243` (`_furniture`, counting decision at `:264`), and `:327` (`extract_text_from_pdf`).

The geometry pass now retains evidence that the preceding sentence runs into a same-size number at the foot. The sequence pass groups numbers by `int(text) - page_index`, requires multiple distinct pages, and removes a run only when at least one member is not marked `in_sentence`. Repeated short-capital running heads still require repeated height. No speech normalization code changed or was invoked by the probes.

**Exact previous failure, independently recreated:** `challenges.py` writes two real 595×842-point PyMuPDF pages. Each has `The required access code is` at `(72, 620)`, size 11, and a standalone number at `(72, 750)`, size 11: `1984` then `1985`. There are no headers or folios. The reopened PDF's raw text is checked against every inserted line, then the actual extractor is called.

Expected and actual, whitespace normalized, are identical:

```text
The required access code is 1984 The required access code is 1985
```

Both numbers occur in the source and narration. Both candidate records have `in_sentence: true`; neither is dropped. Evidence: `exact-prior-1984-1985.pdf` and its raw text, edge records, expected and actual narration in `challenges.json`.

| Independent real-PDF control | Expected and actual |
|---|---|
| Meaningful `1984` / `1985` | Both preserved |
| Meaningful `42` / `43` | Both preserved |
| Three-page meaningful `1984` / `1985` / `1986` | All preserved |
| Printed `198` / `199` below finished sentences | Both removed; sentences preserved |
| Printed `198` / `199`, one page ending mid-sentence | Both removed; text preserved |
| Printed `198` / `199`, size 9 below size-11 body | Both removed |
| Repeated `IV` running headers with real folios | Headers/folios removed; body `NOT` preserved |
| Repeated body `NOT`, `I`, `FBI`, `NASA` | Both occurrences preserved in each of four PDFs |
| Non-counting `1984` / `9001` | Both preserved |

There were **14 independent PDF cases**, including the four separate body-word PDFs and two explicit ambiguity controls. All matched their stated expectations. The tracked focused PDF regressions contributed **20 passed** cases, including all three new continuation parameters, three folio parameters, non-counting and mixed-content controls, explicit ambiguity, repeated capitals, established sequence and running-head controls. Their exact node IDs are retained in `focused.xml`.

**Limitations under ACT72-064 / ACT72-070, not new release failures:**

- A bare meaningful year under a finished sentence, in the same font and position as counting folios, remains observationally indistinguishable from those folios. The independent `ambiguous-finished-years.pdf` deliberately loses `1984` / `1985` under `The vault was sealed.`; the tracked ambiguity test agrees. This is not the repaired unfinished-sentence reproduction.
- Conversely, counting printed folios of body size under unfinished sentences on every observed page are narrated. `ambiguous-all-unfinished-folios-narrated.pdf` confirms this conservative, harmless extra narration.
- In a mixed run, one member with folio evidence makes the whole run furniture, including a same-size member below an unfinished sentence. The one-unfinished-page positive control exercises that rule. Such an isolated continuation-number layout is also possible for genuine folios; layout alone cannot promise perfect semantic classification. Smaller meaningful numbers in folio layout have the same ambiguity.

No material semantic-loss defect distinguishable under the approved rules was independently demonstrated. These limitations do not authorize a blanket claim that all possible PDF content is preserved or change any issue status.

## R9-03 — PASS: rollback move is bound to the held Windows file

Source: `scripts/mp3/mp3_plan.py:444` (`_open_held`), `:463` (`_rename_held`), `:479` (`_take_back`, identity comparison at `:495`, descriptor cleanup at `:499`), `:502` (`publish_book`, rollback at `:538–557`).

`CreateFileW` requests DELETE and FILE_READ_ATTRIBUTES, shares read/write but not deletion, and opens reparse points themselves. The returned handle is transferred to a descriptor. `_take_back` compares the actual `os.fstat` identity to the prepublication identity, then `_rename_held` uses that same descriptor's handle for `SetFileInformationByHandle(FileRenameInfo)`, with replacement disabled. The held file stays held through both operations. This is a file-bound namespace operation, not a checked pathname subsequently renamed by name. Microsoft's [handle-operation documentation](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle) and [FILE_RENAME_INFO contract](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_rename_info) support the handle and no-replacement interpretation; actual Windows operations below supply the execution evidence.

**Exact previous race, independently scheduled:** stage two tiny ID3-prefixed placeholder files under a new owned `.work/Book`. Let real publication move output 0, then raise an injected `OSError` immediately before output 1's publication. At entry to `_rename_held`, after `_take_back`'s real held identity check passed and before the real handle rename, execute a competitor's real `os.replace(competitor_source, output_0)`. The hook then delegates to the real `_rename_held`; it does not fake filesystem success.

Expected: the competitor retains its own source and bytes, ACT takes back only its own file, and legitimate retry succeeds. Actual trace:

```text
after real held identity comparison; before real handle rename
competitor refused: PermissionError, winerror=5
```

Actual error: `publishing Book failed and was rolled back: second output publication failed`. Both staged files contain ACT's original bytes, output names are empty, and the competitor remains at its own pathname with `COMPETING WRITER UNIQUE BYTES`. An unrelated writer's file and nonempty subdirectory remain intact. The rollback descriptor is closed. Retry publishes exactly the two original ACT payloads at the planned names; competitor bytes remain intact. Evidence: `challenges.json` (`exact-prior-race`) and the retained real files under `mp3/exact-race/`.

| Additional independent bounded challenge | Expected and actual |
|---|---|
| Competitor replaces output before the hold opens | Real `os.replace` succeeds first; identity mismatch refuses rollback; competitor stays; second ACT output stays staged; incomplete rollback names `0.mp3` |
| Competitor attempts replacement while handle is held | Refused with WinError 5 in the exact race above |
| Staging destination already occupied by a file | Handle rename refuses; both ACT published file and competitor staging bytes survive; incomplete rollback reported |
| Staging destination occupied by a nonempty directory | Directory and child survive; ACT file survives; incomplete rollback reported |
| Different expected identity | Real file held/stat'ed, mismatch refuses move and releases descriptor |
| Normal partial publication failure | Own output restored, newly created empty Book directory removed; retry succeeds |
| Windows handle acquisition refused | A real open reader denying deletion prevents the DELETE hold; ACT file stays published and incomplete rollback is reported; after reader closes, legitimate take-back succeeds |
| Unicode destination | Tiny `Book-音-🎧` fixture rolls back and retries, exercising UTF-16 byte length including a non-BMP character |
| Forced off-Windows branch | Already-published output stays, unmoved output stays staged, explicit incomplete-rollback error, retry refuses incomplete staging |

The main probe reports **9 MP3 scenario groups**; the held-competitor attempt is included in the exact-race group. Occupied-file and occupied-directory probes preserve ACT's output, then deliberately move that owned file to `own-after-refusal.mp3` to verify no hold leaked. The pre-hold-replacement probe likewise performs a subsequent real replacement to verify the mismatch hold was released. These later probe actions are recorded, not application behavior or data loss. All files remain in the new evidence tree.

**Cleanup:** source inspection confirms `finally: os.close(descriptor)` on success, mismatch, rename refusal and `fstat` failure; descriptor-conversion `OSError` closes the raw handle. Two additional independent negative checks exercise actual handle creation with injected Python-layer errors: failed `open_osfhandle` leaves `GetHandleInformation` reporting ERROR_INVALID_HANDLE (6), and failed `fstat` leaves a closed descriptor and an immediately movable file. Both report incomplete rollback and preserve ACT's bytes. `cleanup.json`: **2 passed**. The real sharing-conflict case exercises failed `CreateFileW`, which returns no acquired handle.

The tracked focused MP3 regressions contributed **8 passed** cases: ordinary publication; partial failure; single-output collision; later-output collision with rollback/retry; replaced earlier output; the exact post-check competitor schedule; forced fallback; existing destination refusal. No symlink tests or unrelated planning groups were selected.

**Off-Windows limitation:** `_CAN_TAKE_BACK` is false on macOS/Linux, so rollback deliberately leaves partial publication in place. The error explicitly names what could not be taken back and says it was left where it is; the call raises, never silently returns atomic success. Retry refuses until state is reconciled. This branch was forced on Windows, not executed on another OS. Existing introductory module/function prose still uses broader whole-Book/atomic language; that wording must be read with the explicit failure behavior and is not an established cross-platform guarantee. No unsupported cross-platform atomicity is accepted by this PASS. Holds can also be refused on Windows, and while a hold exists competing rename/delete operations are temporarily refused.

## Exact focused execution

From the repository root, existing `.venv` only:

```powershell
.venv/Scripts/python.exe -B files/run-temp/p9-final-a00f0a2-20261112-codex/challenges.py
.venv/Scripts/python.exe -B -m pytest files/tests/test_pdf_text_cleaning.py files/tests/test_mp3_plan.py -q -p no:cacheprovider --basetemp=files/run-temp/p9-final-a00f0a2-20261112-codex/pytest --junitxml=files/run-temp/p9-final-a00f0a2-20261112-codex/focused.xml -k "numbers_that_sentences_run_into or numbers_that_do_not_count or page_numbers_in_the_same_place or running_head_and_page_numbers_beside or ambiguous_a_year or same_short_capitals_in_the_body or repeated_body_word or capitals_in_the_bottom_margin or bare_number_is_a_page_number or short_capitals_are_a_running_head or short_running_head_in_capitals or numbers_that_count_up_across_pages or a_year_that_ends_a_page_is_read or publish_moves_every_staged_output or publication_rolls_back_if_a_move or file_that_takes_a_single_outputs_name or competitor_at_a_later_outputs_name or rollback_never_takes_back_a_file or competitor_acting_after_the_rollbacks_identity or where_a_rollback_cannot_be_bound or publish_never_overwrites_an_existing"
.venv/Scripts/python.exe -B files/run-temp/p9-final-a00f0a2-20261112-codex/cleanup_checks.py
```

| Execution | Result |
|---|---|
| Selected tracked regressions | **28 passed, 86 deselected, 0 skipped**, 2.00 s; PDF 20, MP3 8 |
| Independent real-PDF challenges | **14 passed**; raw source text and actual extraction recorded |
| Independent real-Windows filesystem challenges | **9 scenario groups passed**; real publication, replacement attempts, handle renames and retries |
| Additional handle failure cleanup | **2 passed** |

Each command ran once and exited 0. Pytest emitted the existing pydub `audioop` deprecation warning only. Console logs, JUnit node IDs, JSON records, source probes, and all fixture files are retained locally. `manifest.json` hashes the probe sources, results, logs, PDFs and identity/state records. Key SHA-256 values:

| Artifact under evidence root | SHA-256 |
|---|---|
| `challenges.json` | `477c8f3b57d86b82f140fc1f926ec339ddfba565266e804ae3905352f270e556` |
| `focused.xml` | `62cc31cc279ca8944e859754775c8f4e426372967652aeae7628f83de6d763fc` |
| `cleanup.json` | `c8d05aaffdc184b39be35875b20174f6184e05338cab5204cbd22db722ee6d39` |

## Verdict, remaining release gates and Git disposition

**FOCUSED CLOSURE PASS:** R9-01's reproduced counting-code loss is closed; R9-03's reproduced Windows rollback appropriation race is closed. No remaining release blocker was reproduced in these two areas under the approved scope and ambiguity rules. Issue statuses remain owner-controlled and unchanged.

Separate release work remains as recorded previously: current-source Windows gate/native GUI evidence; applicable real-FFmpeg T5/scaling qualification freshness; owner decisions on ACT72-064 PDF limits; representative narration/endings listening and UX/manual acceptance; other applicable release, compatibility, packaging and qualification gates. None was executed, refreshed or waived here. The prior focused PASS verdicts for R9-02/R9-04 stand without retesting. This report does not establish full Phase 9 acceptance, fresh-Windows, optional-engine, low-memory, other-platform, long-book or performance qualification.

Only this Markdown report is to be scoped force-added and committed locally. Evidence remains untracked. No push, credential repair, token operation, merge, tag, release, Phase 10 or v0.8.0 work. The exact report-only commit SHA is returned separately because a commit cannot contain its own SHA; the existing authenticated Claude session may publish that unchanged commit. Stop after that commit.
