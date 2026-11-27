# Audiobook Creation Tool — Decisions archive: v0.6.7 to v0.7.3 (October to 12 November 2026)

Archived unchanged from `md-instructions/Decisions.md` by DOC-1 (v0.8.2 Phase 2, 2026-11-27). Everything below the line is the original
text, byte for byte and in its original order (newest first, from 2026-11-12 down to the first October entries, then the eight late entries described below). Nothing here is rewritten or superseded by being moved; the
index at the top of `md-instructions/Decisions.md` still names the entries that govern. The whole file as it was before the
archival: `git show dabb02d:md-instructions/Decisions.md`.

---

## 2026-11-12 — v0.7.3 owner PASS authorizes merge and Windows packaging, not GitHub publication (owner; recorded by Codex)

The owner accepts application commit `a2cc65d3f498b5d5fd886c0c01c8780d1e1d6d3b` after
personally using the verified candidate window, recognizing all 33 recovered Nero chapters,
completing the full-book GUI conversion and successfully converting multiple additional
audiobooks to chapterized MP3s. These are owner-reported outcomes, not newly executed
automated conversions or an unrecorded listening/timing qualification. The earlier failed
attempt selected the original v0.7.2 launcher; the private verified launch workflow resolved
that selection problem without another production fix. Bounded GUI preflight and private
runtime checks independently proved the intended worker imports/configuration and plan.

The recorded narrow automated evidence and this manual acceptance suffice for this hotfix.
The owner explicitly waives a repeat full gate, M4B scaling benchmark and unrelated
qualifications; no historical gate result changes and no new full-gate PASS is claimed.
Authorized now: documentation-only acceptance closeout on PR #15's feature branch, ready
and merge PR #15 into master, commit the v0.7.3 README/download instructions, build and
audit the Windows ZIP from final committed origin/master. Application and tests remain
identical to the owner-tested candidate. No extra PR, history rewrite or branch deletion.

Publication is a separate manual owner action: Codex must not create the v0.7.3 tag/release,
upload an asset or enable publishing. The new README download URL is preparatory until
that publication. Preserve the v0.7.2 release/tag/archive and all owner data/evidence.

## 2026-11-12 — v0.7.3 candidate: independently validated Nero chapter recovery (Codex)

The owner explicitly chose application-level recovery for conflicting QuickTime/Nero chapters.
Normal validation runs first and is unchanged. Only an invalid primary list permits a bounded read
of exactly one `moov/udta/chpl` v1 table, with a unique sound-track chapter reference to a distinct
QuickTime text track. The linked sound track must match FFprobe's single audio stream ID. Unsupported,
truncated, duplicate or ambiguous boxes and malformed UTF-8 fail closed. Nero entries retain stored
order/titles and pass `validate_chapters`; recovery additionally requires explicit start zero, a
zero-based audio stream with matching duration, and a positive sample count for each existing cut.
No timestamps are sorted, dropped, deduplicated or nudged; no new tolerance or dependency is introduced.

`SourceReport.original_probe` retains the contradictory answer and `chapter_recovery` records the
selection/refusal. Split uses the existing planner/executor. Whole suppresses the contradictory input
chapter map and writes the frozen recovered spans as ID3 CHAP/CTOC on its private staged MP3 using
the already pinned Mutagen dependency; tags/artwork and the existing Strip policy remain in force.
ID3 navigation has its normal millisecond precision; audio boundaries keep the Nero starts. This
bounded execution integration is necessary so Whole does not copy the map that preflight rejected.
A bounded preallocated ID3 header prevents moving the audio payload while adding navigation.
Cancel checks, measurement and no-clobber publication still surround the staged output.

Private owner media/excerpts and local evidence are never tracked or uploaded. Focused tests replace
the broad gate for this explicitly bounded session. Owner full-book acceptance is mandatory before
any merge, final release ZIP, tag or publication; candidate identity alone is not a released version.

---

## 2026-11-12 — ACT v0.7.2 — owner-approved composite verification acceptance

The full Windows gate at `c4a9853a9fadca77320e576c618d14395dd2191c` reported three failures in structural
tests made stale by approved Phase 9 changes. The test-only correction
`5978e88f8c62f7f1c1c31dc0ed0a663ddfece5c0` passed the affected regressions, negative controls and focused
verification. No production code was changed by that correction. The owner explicitly accepts the combined evidence
and waives another complete full-Windows-gate execution for this v0.7.2 release only. The historical full-gate FAIL
remains unchanged. This supersedes the preceding closeout's requirement for another full run and draft status; it is
a release-specific exception to the roadmap's clean-final-full-gate requirement, not a policy for future releases.

**Accepted evidence, with execution identities preserved:**

- Full gate `2026-11-12_135000_full_85b2` at `c4a9853`: **FAIL**, 15,034 executed, 14,966 passed, 3 failed,
  65 authorized policy skips; 56/56 native journeys and 262/262 required coverage; other required checks passed.
- Correction `5978e88`: exactly three test modules, four affected tests and seven negative controls passed;
  focused `2026-11-12_153553_focused_531d`: 921 passed, 1 policy skip; package audit PASS.
- Independent Codex full gate PASS at `85960252c7e2873b1e83875a759b1dfcd501c747`;
  R9-02/R9-04 focused PASS at `a943a26f9c5592e05631e27f21019d0250aa28c4`, report `3f02d4c`;
  R9-01/R9-03 final focused PASS at `a00f0a2b73068dae33b06fb1ae95083cc4251b4b`, published report `11fa574`.
  No remaining reproduced material defect from those reviews; their original scope limits remain.
- At `c4a9853`: `m4b-scaling` `2026-11-12_112630_qualification_1476`, PASS 79/79 checks, 207 runs;
  `edge-low-memory` `2026-11-12_134404_qualification_a6dd`, PASS 61/61 checks. Accepted carry-forward to this closeout.
- At `3aa421a288a11587ad7078a5a949c05dae5f6e17`: `optional-engines`
  `2026-11-12_030349_qualification_f77a`, PASS 76/76; `fresh-windows`
  `2026-11-12_025238_qualification_25cd`, PASS 43/43. Historical, mechanically stale; accepted carry-forward
  on the existing readiness assessment that relevant inputs are unchanged. No new platform qualification is implied.

**Administrative closure:** close ACT72-073 on the independent R9-02 PASS and real-FFmpeg scaling PASS above.
Updating `coverage.json` changes the evidence/policy digest; earlier executions remain valid historical records for
their actual tested sources, not mechanically current evidence. No gate record, threshold, skip or policy is altered.

**Visuals and remaining acceptance:** 89 visual candidates remain unapproved; formal baseline approval is deferred
for this release, supported by native geometry checks, 56 journeys and prior owner UX acceptance. `approved.json`
is unchanged. Prior listening/UX approvals carry forward where behavior is unchanged. Only two owner decisions
remain: ACT72-064's five presentation limits and three classification ambiguities (including genuine number loss),
and the Windows-focused release scope plus final PR review/manual merge. ACT72-030 stays open/deferred;
ACT72-064 stays open. Windows 11 HOME-PC at 100% scaling is qualified; Windows 10 is not separately qualified,
and macOS/Linux are not qualified. Off-Windows MP3 rollback leaves partial published outputs visible and reports
them; retry may need reconciliation. The cross-platform no-clobber path may require filesystem hard-link support.

No new verification execution, tests or qualifications in this administrative checkpoint. No final-source clean
full-gate PASS is claimed. No merge, auto-merge, tag, release or archive publication is authorized or performed.
Details and the exact two-decision checklist: `files/dev-work/phase9-remote-review/ACT-v0.7.2-FINAL-PR-READINESS.md`.

Signed: Codex, recording the owner's explicit 2026-11-12 final administrative closeout instruction.

## 2026-11-12 - Release readiness: issues close on the independent closures, the ledger is frozen before any run, a failed gate is corrected but not rerun, and the PR stays a draft (v0.7.2 release closeout)

**Context.** The owner's final-release instruction authorized publishing Codex's final closure, closing the ledger,
fresh qualifications where needed, ONE full Windows gate, packaging checks and a PR. It did not authorize a merge, a
tag, a release or a second full gate. Record: `files/dev-work/phase9-remote-review/ACT-v0.7.2-FINAL-PR-READINESS.md`.

**Decision 1 (issues close on their own contract).** ACT72-070, -071 and -075 said "open until an independent re-review
confirms the repair", and Codex's focused closures did confirm them (`3f02d4c` at `a943a26`, `11fa574` at `a00f0a2`), so
they close. Each closure cites the report, the reviewed SHA, the tests and the limits the reviewer stated.

ACT72-073 stays open, because its census still had to run on real FFmpeg. `m4b-scaling` on `c4a9853` has now done that,
so it is closure-ready. ACT72-064 gains the three layout ambiguities of the final closure; no deferral of it is recorded
as approved. Rejected: closing all four on the review headline.

**Decision 2 (the ledger changes before the runs, not after).** Every run's identity includes the policy digest, and
`coverage.json` is policy. A status changed after a run makes that run `stale`. So the ledger was committed (`c4a9853`)
before any run, and ACT72-073 is not flipped after its own evidence.

**Decision 3 (freshness by relevant input).** `m4b-scaling` and `edge-low-memory` ran again, because the Converter, the
T5 census and the PDF extractor changed. `optional-engines` and `fresh-windows` are carried forward from `3aa421a`, because
no code on their paths changed. The gate's reader still calls them `stale`, and that is said, not hidden.

`m4b-scaling` has no legitimate partial route: `qualify.py` refuses `--rehearse` outside `--smoke`, and `pass_requires`
wants 79 checks over 207 runs. So it ran whole, once, after a smoke rehearsal that is never a verdict.

**Decision 4 (a failed full gate is corrected, not rerun).** The gate on `c4a9853` failed three structural tests that
Phase 9 changes had left stale. The correction (`5978e88`) changes tests only:

- the Converter worker's guards allow the R9-04 decision lock and pin it to `threading.Lock()`;
- the review reports in `files/dev-work/phase9-remote-review/` count as history for the retired-path check.

It was checked by negative controls and a focused gate. The full gate counts as consumed: another needs the owner. No
assertion was weakened. The allowed set grew by one threading primitive, which the new pin holds to being one; the
exemption is limited to top-level Markdown in that one folder, and a new test pins that.

**Decision 5 (the PR is a draft).** No full gate passed on the current source, so the PR is not presented as ready. Its
blockers are named in it. The independence distinction is left to the owner: Codex ran the full gate independently on
`8596025`, and after the remediation its reviews were focused.

Signed: Claude Code (implementation agent), under the owner's 2026-11-12 final-release instruction.

## 2026-11-12 - Phase 9 remediation: uncertain PDF text is narrated; a new output takes its name only if nothing holds it and only once Cancel has lost; a qualification PASS is judged where it is produced; T5 is the approved sentence, read exactly and failed when it cannot be read (v0.7.2 Phase 9, ACT72-070 to ACT72-075)

**Context.** The independent Codex review of `8596025` (Phase 9) failed the candidate on five findings, P9-01 to P9-05. Each was reproduced on that commit before any tracked file changed, and every fix has a control that fails without it. Evidence: `files/dev-work/verification-gate/outputs/2026-11-11_phase9_remediation_e7b2` (ignored): the before and after records, `negative-controls.md`, `controls.md`, `LEDGER.md` and the remediation report. The review's own package is `outputs/2026-11-11_phase9_codex_6a91`.

**Decision 1 (P9-01, ACT72-070: a line of a PDF is removed only on evidence, and otherwise narrated).** `tts/pdf_extractor.py` deleted any line of digits that was a page's first or last line and any line of one to four capitals anywhere, so a count that ended a page, "NOT", "NASA" and "I" were dropped from sentences without a word in the log. Both deletions are gone. A line is page furniture only on two kinds of evidence together. From the page's geometry: it is the top or bottom row, clear of the other text by more than one and a half line pitches (or alone on the page), and not set larger than the body text. From another page: a number is a folio only when another page's edge number counts with it page for page, and a short heading only when the same word stands at the same height on another page. Without the page's geometry nothing is removed. Rejected: another pattern-only rule (shorter lists, "numbers under four digits", a stop-list of words); removing on geometry alone (a chapter numeral stands clear at the top of one page and is content); asking the listener.

**Decision 2 (P9-01: line ends).** A hyphen at a line or page end is dropped only when a letter carries on in a small letter ("exam-" / "ple"). Between two letters or digits otherwise it is kept ("1939-" / "1945", "Ancient-" / "Class"). A heading-looking line inside a running sentence is joined to it. Sizing and narration read through the same cleaning, the PyMuPDF lock is unchanged, and one text page per page serves both the text and its geometry; the raw text is byte-identical to before on every page of the 23 real PDFs under `files/test-files`.

**Decision 3 (P9-01: what is still imperfect is pinned, not hidden; ACT72-064 stays open).** Five limits remain, each held by a test named `test_limit_*` so that it cannot change unnoticed: a running head longer than four capitals or in mixed case is narrated; a true compound broken at a line end before a small letter loses its hyphen ("well-" / "known"); a page number or head that nothing repeats is narrated; a drop capital set on a line of its own is read as a letter by itself; capitals at the very end or start of a page keep a line break inside their sentence. Every one errs towards narrating. They are for the owner to accept or schedule one by one; ACT72-064 is not closed and not deferred as a block.

**Decision 3a (P9-01: one A0 speech golden changes, on purpose).** `files/tests/golden/speech/extraction.json` pinned the old loss: its sample page has the chapter numeral "IV" on a line of its own, and the golden's cleaned text had no "IV". With no geometry and nothing repeating it, that line is now narrated. The golden was edited by hand, not regenerated: "IV" stands again in `clean_page_text`, and the entry for the removed helper `_strip_noise_lines` is gone, with its call in `files/dev-tools/speech_characterization.py`. The tool's own output is byte-identical to the edited file, and the other five goldens (Edge direct, Edge folder, Kokoro, Chatterbox, Qwen3) are unchanged.

**Decision 4 (P9-05, ACT72-074: giving a new file its name is its own operation).** `output_paths.publish_new` gives a plan-owned temporary a name only if nothing holds it: one `MoveFileEx` without replacement on Windows, a hard link elsewhere, no fallback to looking first. It raises `DestinationOccupied`, a refusal with the other file untouched. `atomic_replace` is unchanged and is still what an intended replacement calls; the choice is made by name at the call site. Rejected: changing `atomic_replace` for everyone; a look followed by a replace (the control shows it loses the other writer's file); a lock file.

**Decision 5 (P9-02, ACT72-071: one question decides between Cancel and the commit).** `convert_segment` looks at Cancel after the last pass and again after the finished file is measured, then asks the job once, `authorize_commit`, which cannot succeed after Cancel is requested and which holds a cancellation's settlement until the publication it allowed has finished (`commit_finished`). Either Cancel won and nothing has that output's name, or the publication was authorized first, the output stands, and the job's end says so. The Converter hands the segment this as a `CommitGate`; the execution module still knows nothing of the job controller. A Pause during the last measurement is not a Cancel: the output in hand is published and the run then waits before the next book.

**Decision 6 (ACT72-075: the same look-then-replace elsewhere is recorded, not changed here).** `mp3_plan.publish_book` (MP3 Tool) and `m4b_staging.publish_staged` (M4B Maker) decide by looking and then replace. They were read from source, not reproduced, and are outside the five findings; ACT72-075 is open for the owner.

**Decision 7 (P9-03, ACT72-072: a PASS is judged where it is produced).** `verify.py` sealed PASS with exit 0 on a verdict with a failed check, on one that executed nothing and on another scenario's verdict; only the reader objected, afterwards. The producer now judges before any PASS is recorded: the scenario's own verdict, exit 0, a non-empty list of checks that all passed, at least one run, an identity naming the commit under test, as many saved runs as the verdict claims, and the checks the policy requires of that scenario (`verification.json` `pass_requires`: how many, which names, how many of each family, written from the four runners themselves). Anything else seals FAIL with exit 1 and satisfies nothing. The reader's independent validation is kept and reads the same rule from one place; it was not weakened. The 31 sealed runs on disk read the same status as before, and no saved result was rewritten.

**Decision 8 (P9-04, ACT72-073: every decrease is read, by whoever makes it, and what cannot be read fails).** T5 read staged bytes inside two wrapped helpers only, so a copy made and unlinked directly was never seen (200,100 bytes witnessed, 100 read). `scaling/staging.py` reads the real size of every owned temporary before each removal, rename, truncation and writing-open this process makes, whichever function makes it (an audit hook), and holds that account to Windows' own report of every removal and rename under the output base by any process (`ReadDirectoryChangesW`). A temporary that went away without a reading, one nobody saw created, a report Windows dropped, a watch that was not live, a link among the temporaries: each fails the check. A file is diagnostics only because it was handed to a child as its output, recognised by its identity on the volume, never by its name. Links and junctions are recorded and never entered. A shortening through an already open handle cannot be heard; an open that would allow it is recorded as unobserved, and a test holds the Converter's own code to never doing it.

**Decision 9 (P9-04: the approved budget, to the letter).** T5 is "peak staged bytes no higher than production's": the total, media and diagnostics together, against the largest seeking run, with no allowance. The 1.05 x on diagnostics that Phase 8 introduced is withdrawn. Beside it staged media must match exactly, the seeking runs must agree on their media, and the compared runs' output paths must be equally long (FFmpeg's diagnostics name the output, two bytes a character). No throughput budget, no C1 threshold and nothing of T4 changed. What is left of chance: FFmpeg's own status line varies by up to 3 bytes, always downward from the usual figure (14 of the 172 retained runs), so T5 could fail a good run only if every seeking run of a book read low while a one-decode run did not; it can never pass a bad one. A scenario is not repeated until it passes.

**Decision 10 (planted defects through the tracked harness).** Eleven copies of the application, each with one defect in the one-decode route, were measured with `qualify.py --smoke --rehearse resources --code <copy>`: the reviewer's transient extra copy and 4 KiB copy, a copy truncated first, renamed away, written under a `.log` name, written or removed by a child, discarded through the helper, and a temporary forgotten inside and outside the run folder. Each fails T5 for its own reason (one is stopped by T8 first and is counted as that); the unchanged copy passes with equal totals. T4's result in the same runs is recorded beside and never counted as T5's.

**Decision 11 (freshness is not argued; a failed gate is corrected at its cause and run again).** The remediation changes application, gate, policy and test files. Its changed-area selection is the whole suite (`scripts/shared/` is under `full_on`), so the full Windows gate is also the changed-area gate. The gate on `7272eb9` failed on one thing: `coverage.json` still named a test id whose parameter that commit had renamed (15,007 tests executed, none failed). The line was corrected in `3aa421a`, every id the inventory names was held against the collected ids, and nothing of `7272eb9` was carried forward: all four qualification scenarios and the full gate ran on `3aa421a`, the scenarios first and the gate last so that no gate run was spent before they had answered. Before a full gate the inventory's ids are compared with the collected ids; only the end of a full run does it otherwise. Results are in the Handoff.

**Decision 11a (a blocked gate counts for nothing, and its cause is removed before the next run).** The first full gate on `3aa421a` was BLOCKED: every test passed, and one native journey was refused its largest picture because another window covered its window at one point for a moment. The gate was right to refuse. What covered it could not be proved: the point is where a notification pop-up stands on this screen, nothing stands there afterwards, Windows logged no notification for that minute, and the refusal came at the second this session's turn ended, when its own client can raise one. That is recorded as an inference. The run is kept and counts for nothing; the gate was run again with the session kept still until the journeys had finished. No notification setting of the owner's was touched.

**Decision 12 (a Windows limit met on the way).** One control's long name made its run's own `TEMP` 262 characters, and Windows then spun for good inside `CreateProcess` (`BasepQueryAppCompat` to `GetTempPathW`, read from the thread's stack three times) with FFprobe created and never started. `bench_run.py` now refuses a run folder that deep before making anything in it. A gate qualification's folders are about 40 characters shorter and were never affected. Nothing was cleaned up: the stalled attempt's folder, the control copies and the gate's scratch are left for the owner.

**Decision 13 (the legacy `epub2tts_*` folders: Windows empties them, and that is reported, not acted on).** The protected-state comparison at the end found seven of the 31 folders under `%TEMP%` emptied during the session (25 files), all seven in the same second, 2026-11-12 02:35:23, four minutes after Windows' Storage Sense task started; all seven were a week old, the younger ones were untouched, and the August folders show the same mark. Nothing of the application or the gate reaches them. No Storage Sense setting was changed and nothing was copied out: both are the owner's. "The folder is still there" does not say its files are, so a census of what is protected has to look inside.

**For the owner (proposals, not decisions).** The 18 legacy folders that still hold a file pass seven days from 2026-11-12 12:46 (Decision 13). Accept or schedule each of the five PDF limits (Decision 3). Decide ACT72-075 (Decision 6). T4's console host is still the owner's from Phase 8. `publish_new` outside Windows needs hard links, which FAT and exFAT volumes do not have: a new output there would be refused with a message; macOS was not exercised in this phase. ACT72-030 stays open and deferred.

## 2026-11-11 - Phase 8 remediation: a failed check is taken apart before it is touched; the scaling harness reads what it compares (no held handles, the decoder's console host, staged bytes read exactly); a qualification PASS is read through its scenario's verdict; no budget moved (v0.7.2 Phase 8, ACT72-067, ACT72-068, ACT72-069)

**Context.** The recovery checkpoint left Phase 8 blocked: on `75436ee` the full gate and three scenarios passed, `m4b-scaling` had one unfinished run with a failed T4 check and one finished run that failed T5, and `verify.py --status` could not read a qualification PASS. The owner asked for the measurement to be repaired, not the budgets. Evidence: `files/dev-work/verification-gate/outputs/2026-11-11_phase8_remediation_7c3e` (ignored), `02-forensic-findings.md` written before any tracked file changed.

**Decision 1 (the figures first).** Both failed checks were traced to what they had actually compared, from the saved runs' own records and three experiments, before any code changed. T4's job peak: Windows charges a job about 77.5 KB for each exited process someone still holds a handle to (300 children: nothing once let go, 23.3 MB while their process objects are kept), and the harness kept every child's, 155 MB of 236 MB on the 1,000-chapter book. T5's staged bytes: half-second samples of a total that peaks for milliseconds, with FFmpeg's diagnostics file counted in. Two hypotheses were tested and dropped on the way and are recorded as dropped. Nothing in the Converter differed between a passing and a failing session.

**Decision 2 (the instrument is corrected at its source).** The harness reads a child's figures when it ends and lets it go. No tolerance was added to absorb the harness's own residue.

**Decision 3 (one more FFmpeg is two processes on Windows).** The approved budget is "job peak commit no higher than production's plus one more open of the book by FFmpeg" (Phase 7A record, section 8). Windows starts a console host for a hidden console child; the decoder's lives as long as the decoder. The harness finds it among the job's processes and T4 allows for the decoder and that one console host, each at its own measured peak, and 1 MiB for the audio. A console host that was not found, a second one, or any other child of the decoder is not allowed for. This changes the harness's own formula after failed runs, so it is listed for the owner. Rejected: taking the seeking route's own FFmpeg as the yardstick (a larger figure, chosen after a failure); comparing medians with a measured noise term (the corrected readings do not need it: 0.21 MB between one-decode runs in the calibration, 1.95 MB inside at the least in the qualification).

**Decision 4 (no PCM on disk, directly).** The total comparison stays; it never failed and is the same to the byte across runs. Beside it: every byte the decoder wrote is its stream or its measured diagnostics file, and the application wrote nothing beyond its feed to the encoders but what it writes on the seeking route (within 1.05 x).

**Decision 5 (staged bytes are read, not sampled).** The real size of every owned temporary is read just before each discard and each publication; between those moments the total can only grow, so the largest reading is the peak. Staged media is compared with zero allowance, the seeking route's own runs must agree to the byte, every publication must have been read, and nothing may be left behind. FFmpeg's diagnostics text is not deterministic (it differs by a few bytes between identical runs), so it is read apart and held to the scenario's existing 1.05 x for writes. The sampler stays as a witness. Rejected: adding 68 bytes or any margin to the sampled comparison; dropping the diagnostics from view.

**Decision 6 (a planted defect must fail the check that names it).** `qualify.py --smoke --rehearse resources --code <copy>` measures a copy of the application; its verdict is SMOKE and can never be PASS, and `--code` is refused without `--smoke`. Nine copies were measured; a control that was stopped by another check first (a spool written among the outputs trips T8) was split in two rather than counted as a catch.

**Decision 7 (the reader judges a qualification by its scenario).** The scenario's verdict must be sealed evidence, readable, about that scenario, and it and the runner's recorded exit must lead to the sealed result in both directions; a PASS needs checks that all passed and at least one run. The "no executed tests" rule stands for every other mode. Saved runs are read, never rewritten.

**Decision 8 (freshness is not argued).** The candidate changes gate and test files, and the only carry-forward rule is for a documents-only commit. So the full gate and all four scenarios were run on `f38cd61`: `m4b-scaling` once, the other three again although their own code digest had not moved.

**Decision 9 (one run, and its limits said).** The qualification ran once on the committed candidate after a calibration, the controls and a smoke rehearsal. The job-peak comparison resolves megabytes, not kilobytes: the measuring process itself grows by about 3 KB per second of run, so the seeking route's longer runs read up to about 1 MB higher on the 1,000-chapter book than the same route would in the one-decode route's time. The fine detail is in the exact parts (audio held, bytes written, staged media). The run's T1 ratio is higher than in earlier sessions because decode-heavy FFmpeg work ran slower on the computer that morning, with the old harness as much as with the corrected one; the cause was not found and none is claimed.

**Decision 10 (nothing cleaned up).** Scratch under `%TEMP%\act-gate` and the copies under `files/dev-work/verification-gate/outputs/2026-11-11_phase8_remediation_7c3e/controls` are left for the owner. Copying those 1,288 source files into the workspace made VS Code and Defender busy for a quarter of an hour and doubled the wall time of one calibration run; nothing of the kind was done while the qualification or the gate ran.

**For the owner (proposals, not decisions).** Accept or refuse the console host in T4's envelope (Decision 3). ACT72-064 stays open with its deferral proposal. Listening, the visual candidates and the unqualified platforms are unchanged.

## 2026-11-11 - Phase 8 checkpoint after a Windows Update restart: a blocked gate is fixed at its cause, not rerun; a picture is of a whole window inside the desktop; a result is what is on disk; a scenario is not repeated until it passes; a checkpoint changes nothing in the tested state (v0.7.2 Phase 8, ACT72-066)

**Context.** The one planned full gate on `052bef1` ended BLOCKED: one journey refused a picture because the taskbar lay over the window. The first `fresh-windows` run then ended FAIL on five checks. After both were corrected and the final gate had passed on `75436ee`, Windows Update restarted the computer at 00:29 on 2026-11-11, one to two minutes before the end of the `m4b-scaling` run; that run's log already held one failed check, and the run made in its place ended FAIL on another. Results and identities are in the Handoff's Phase 8 checkpoint block. Phase 8 is not closed.

**Decision 1 (a blocked gate is fixed at its cause).** The refusal was right, so the gate was not rerun in the hope of a better placement. The cause was in the gate (ACT72-066): a window enlarged where Windows had put it, and a cover test of 25 points that a 48-pixel taskbar passed between, and that looked below the screen without knowing. In Phase 7B the same refusal was taken for a stranger's window and rerun; that was wrong, and two Phase 7B runs kept pictures with the owner's taskbar in them. Those runs' other results stand; their six 1400x900 pictures are not fit to be baselines.

**Decision 2 (what a journey may do to a window, and what a picture is).** A journey may move the window it owns inside its monitor's work area before enlarging it, as a person would; it may not enlarge it past the work area, and a size the work area cannot hold is BLOCKED. A picture is taken only when every point of a four-pixel grid over the client area, and its far edges, is on a monitor and is the pictured window's own. Tightening was chosen over a rule about the taskbar by name, because the taskbar is one case of "something else is there". Nothing was relaxed: a refusal and a required control were added.

**Decision 3 (the order of the final verification).** A scenario runner that has never run is run before the final full gate, because any correction to a tracked file makes a new commit and the gate must be on the final one. So the order was: `fresh-windows`, `optional-engines`, `edge-low-memory`, then the full gate, then `m4b-scaling`, all on `75436ee`. A runner correction is rehearsed first on the scratch a failed run keeps, which is never a verdict.

**Decision 4 (`fresh-windows` asks the application, and a check must have looked).** `--venv-check` answers whether the environment's Python runs, nothing more; whether the installation is finished is the launch path's question (`requirements_are_current`, `required_modules_present`, then `ensure_requirements_current`). The scenario's offline case therefore asks the next start itself and then proves the recovery with the network back, by calling those functions in the launch path's order; the two repair dialogs and the warning box around them are not driven, and the scenario says so. A check that reads a list fails when the list was never written.

**Decision 5 (a result is what is on disk).** After the restart nothing was taken from memory. The task notice for the `m4b-scaling` run had said "completed (exit code 0)"; that was the exit code of the wrapper's last `echo`. On disk the run had its unfinished marker, no result and no verdict, and its log already held one failed check. So: a run's result is its sealed `results.json` and, for a scenario, its `verdict.json`, read back; a notice or a wrapper's exit code is not evidence. And before a run of more than a few minutes the two pending-restart registry keys are read; with a restart owed, an unattended long run is not started and the owner is told. No Windows Update setting was changed.

**Decision 6 (the interrupted scenario was run once more, and not a third time).** `m4b-scaling` was run again on `75436ee` because no complete verdict existed for the candidate, after the event log showed a planned, clean restart and no restart pending. It was not run again to make the first run's failed check go away (`T4:scale1000:tput-scale1000-181`, 0.21 MB over), and it ended FAIL on a different check of the same book (`T5:scale1000:tput-scale1000-180`, 68 bytes over). It was not run a third time. The evidence is complete; both failures are of comparisons whose room is smaller than the spread of what they measure, so a further run would pass or fail by chance; and a scenario repeated until it passes proves nothing. No limit was touched after either run. Phase 8 is therefore not closed, and what is done about the scenario is the owner's decision.

**Decision 7 (a checkpoint changes nothing in the tested state).** Three defects of the gate were found in the recovery: `verify.py --status` calls every qualification PASS invalid; T4's third part has no allowance for the spread of what it measures; and T5, for a book of very many small files, compares chance samples of the same quantity on both routes with no allowance. None is fixed here, and none is entered in the inventory here, because the reader, the scenario and the inventory are all part of the state the gate ran on: any of those changes would make a commit that no gate has run on, and section 13.3 carries evidence forward over documents only. They are recorded in the Handoff and the review package and are to be entered and fixed with the next change of the tested state, as the owner decides.

**Decision 8 (carry-forward).** The checkpoint changes the four documents only. Under plan section 13.3 the full gate and the qualification results of `75436ee` are carried forward to it, the failed and the unfinished `m4b-scaling` runs as much as the passes; both commits are named wherever a result is, and the documents' own checks are rerun on the checkpoint. One thing section 13.3 does not cover is stated instead: the second `m4b-scaling` run was made on Windows build 10.0.26300.9974, everything else on 10.0.26300.9818.

**Decision 9 (nothing is cleaned up in a recovery).** The scratch of runs that did not pass is evidence of why they did not, and after an interruption nothing is removed because it looks finished with. It is listed for the owner. Windows' own Disk Cleanup task removed some files from that scratch at 01:46 on 2026-11-11; that is recorded, and nothing was done about it.

**For the owner (proposals, not decisions).** `m4b-scaling`: restate the two comparisons for a book of very many small files with the spread accounted for, or judge that book by the exact parts, or accept the evidence with both failures named. ACT72-064: defer the four PDF cleaning limits to a later maintenance release; it stays open until the owner rules. The gate reader: fix with the next change of the tested state. Then: all listening (the application marked four endings itself); the visual candidates; whether Phase 9 is opened.

— Recorded by Claude Code under the owner's Phase 8 recovery instruction, 2026-11-11.

---

## 2026-11-10 - Phase 8: a folder is shown without waiting for Explorer; a number at a page's edge is its page number; the Windows decoder answers for the bytes it delivers; identity 0.7.2; the qualification scenarios exist and the network is granted by name (v0.7.2 Phase 8, ACT72-040, 048, 049, 055, 057, 062-065)

**Authority.** The owner's Phase 8 prompt: resolve the five remaining issues, address the Converter's Explorer freeze as a bounded readiness defect, freeze the v0.7.2 identity, complete the real-engine and fresh-Windows qualification, run one final full gate, prepare the Codex handoff, stop.

**Decision 1 (the reveal is fixed in the shared helper, by a thread, with one request at a time).** The freeze was `os.startfile` called by a window's own thread. The fix is in `shared/subprocess_utils.reveal_in_file_manager`, not in the Converter, because every caller had the same wait and the harnesses already replace that one function. It returns at once and makes the call on one background daemon thread that nothing joins, so neither a window nor closing the application waits for Explorer. A folder already waiting is not asked for twice and at most four wait: a refused request says so instead of piling up. `explorer.exe <path>` in place of `os.startfile` was rejected (it misreads a path with a comma and leaves a process to own). The function returns the request so the Converter can say in its log when a folder could not be opened; the listener holds a queue and a string and never the panel, because a Tk object released on that thread ends the program. Nothing kills, restarts or closes Explorer. The first-run window's own "Open log folder" (`bootstrap._open_folder`) is unchanged: it must work before the environment exists and is pressed on a failure screen.

**Decision 2 (a digit-only first or last line of a page is its page number).** PyMuPDF hands a page number over as one more line, and lines were joined before number-only lines were removed, so a number under a sentence that ran on was read aloud. Removing every digit-only line first was rejected: a number that wraps onto a line of its own inside a page is text. The edge rule costs one case, stated as a limit: a sentence whose last line on a page without a printed number is a bare number loses it. Three other limits are stated, not fixed, as ACT72-064 for the owner: recognising a long running head or telling an acronym from a numeral is new cleaning behaviour, not a repair.

**Decision 3 (the Windows decoder's reader answers for the bytes it delivers).** What the reader negotiates before decoding is the decoder's promise; Media Foundation corrected it after the first buffer for a mono 22.05 kHz book. The reader now decodes its first buffer before it reports a format, and refuses a format changed after that, since everything downstream was told the first one. The routine tests use AAC-LC because no tool available here can make an xHE-AAC file, and they say so. The owner's real xHE-AAC book is a recorded qualification: read only, never copied into evidence, its converted audio deleted after measuring.

**Decision 4 (a first-run journey fails for the product's own reason).** The journey gets a failed setup by putting the disposable copy in a folder whose path is too long for Windows, which the real `run_setup` refuses before installing anything. No outcome is scripted. Opening the log folder and starting the application afterwards are recorded instead of performed. A real base installation downloads gigabytes and belongs to the `fresh-windows` qualification.

**Decision 5 (Clear Downloaded Data is driven on a copy of the application).** The application takes its folders from where its code is, and the helper is the file beside that code, so the journey runs the committed `scripts/` tree from its scratch (`app_launcher.py`, `app_root`). The copy is then the only installation it can reach; a second copy beside it and the real runtime data must be unchanged.

**Decision 6 (qualification scenarios, and the network by name).** The three Phase 8 scenarios are runners under `verification-gate/qualification/` on the contract `scaling/qualify.py` set. `verify.py` hands a granted `--network` policy to the runner and nothing else; `edge-low-memory` needs `online-edge`, `fresh-windows` needs the new `online-setup`, and each is BLOCKED without it. A scenario that needs no network keeps its panel processes offline with an audit hook that refuses and records any non-loopback connection. A missing engine, model or application is BLOCKED, never a download and never a pass. `fresh-windows` works only in the gate's own scratch and never writes an archive to `dist/`. Because `m4b-scaling` identifies its code by every tracked byte of `scripts/`, Phase 8's source changes mean the Phase 7B PASS does not describe this candidate, so the scenario is run again on it; no budget or threshold is touched.

**Decision 7 (identity).** `version.py`, `config.toml` and the nine identity tests move to 0.7.2 together in the candidate commit. The README keeps describing the published v0.7.0. No tag, archive or release is made.

**For the owner.** ACT72-064 (decide or defer). The visual baseline candidates are not approved by any green run. Listening to the engine samples, the real xHE-AAC book and the Edge narrations is the owner's. Windows 10, another computer, a new Windows installation and macOS are not qualified by anything here.

— Recorded by Claude Code under the owner's Phase 8 authority, 2026-11-10.

---

## 2026-11-10 - Phase 7B qualified: m4b-scaling PASSED on its second attempt after a harness-only correction; ACT72-012 closed; budgets, threshold and envelope unchanged (v0.7.2 Phase 7B, ACT72-012)

**Authority.** The Phase 7B prompt: implement, test, document, commit and push C1; close ACT72-012 only after the
qualification passes; never move a budget or the threshold after a failing run.

**Decision 1 (attempt 1 is a harness failure, and the fix is harness-only).** Attempt 1 on `6a92e03` failed 25 of 90
checks with every output identical to its reference. All 25 trace to the benchmark: it left the Converter's end-of-run
reveal live (Explorer windows, six Explorer crashes, the Tk loop held up to 36.9 s in `os.startfile`), its encoder kill
fired after the encoder had finished, and T4 counted pipe writes as disk writes. `90fcb3d` corrects those three and
nothing in `scripts/`; the qualification was then run again in full on it.

**Decision 2 (a benchmark run may not reach the owner's shell).** Every benchmark run replaces the reveal and
`os.startfile` with recorders and refuses to start unless the panel can reach only them (`bench_run.neutralize_shell`,
pinned by a test), alongside the output-base containment; the scenario counts file-manager windows before and after.

**Decision 3 (T4 measures disk, not pipes).** Windows counts pipe writes as writes, so T4 subtracts the pipe bytes the
harness counts exactly before the unchanged 1.05x comparison. The memory envelope (seeking peak + decoder peak + 1 MiB),
the harness's own and stricter than the approved T4, stays as frozen.

**Decision 4 (the threshold stands).** Calibration-3 ran under the same Explorer load, which in attempt 1 slowed the
continuous route about 3.0x and the seeking route about 1.6x, so any skew is against the continuous route; the threshold
is the 600 s floor, unchanged by any break-even up to 300 s. Not recalibrated; a quiet recalibration is the owner's
option.

**Decision 5 (closure).** Attempt 2 (`2026-11-10_124457_qualification_c208`, `90fcb3d`, application code identical to
`6a92e03`) PASSED 79 of 79 checks over 207 runs on a quiet machine. ACT72-012 is closed in the coverage ledger; the
`m4b-scaling` qualification entry stays on `ACT.CONVERTER.SCALING` for any future build, machine or route change.

**Left for the owner.** The Converter's `os.startfile` reveal on the Tk thread (pre-existing, both routes) can freeze the
window while Explorer is slow; it explains Phase 7A's 25.7 s stall. Not changed here.

— Recorded by Claude Code under the owner's Phase 7B authority, 2026-11-10.

---

## 2026-11-10 - Phase 7B: the Converter decodes an eligible split book once; every output stays byte-identical; the route is chosen at preflight, per qualified FFmpeg build, only where it saves work (v0.7.2 Phase 7B, ACT72-012)

**Authority.** The owner/ChatGPT review accepted Phase 7A and authorized 7B: implement C1; amend
`ACT.CONVERTER.PRIMING` only for the new route; byte identity is the oracle; C2 is not approved; budgets T1-T8 and T1b
are approved; implement the reserved `m4b-scaling` scenario; HE-AAC, xHE-AAC and Media Foundation keep their routes.

**Decision 1 (the route).** `scripts/m4b/m4b_continuous.py`. One FFmpeg decodes the book to `pcm_f32le`; chapter k is
decoded samples `[half_up(S*rate), +half_up(D*rate))` from the same `-ss`/`-t` strings the seeking route writes (one
renderer, `m4b_commands.segment_times`), at absolute positions; it is encoded by `pcm_argv` through `run_argv_streaming`;
the cover pass, measurement, drift guard and publication are the seeking route's. FFmpeg's own output-side seek was
checked at exact half-sample ties (neighbours overlap or gap by one sample) and follows the rule.

**Decision 2 (eligibility, frozen at preflight).** Split; chaptered; FFmpeg's own decoder; one AAC-LC `fltp` stream; a
LAME rate; mono or stereo with that layout; time base 1/rate; `start_pts` 0; priming 0 or one AAC frame; a packet scan
proving every timestamp is the running sample count with the declared total; a qualified FFmpeg build; and enough to
gain. Anything unproven keeps the seeking route. The choice never changes mid-book or on a retry.

**Decision 3 (per-build identity).** Byte identity between the routes is established per FFmpeg build, so the route runs
only on a build in `QUALIFIED_BUILDS`, named by a fingerprint (SHA-256 of each executable's size and first and last MiB;
2.8 ms, where hashing both 222 MB files cost 0.32 s per process). Today that is gyan.dev 9.0.1 full_build, the portable
pin and the winget package (one archive). Another build keeps every book on the seeking route until it is qualified:
regenerate the books, pin `204c33b`'s outputs on it, run `m4b-scaling`.

**Decision 4 (enough to gain, and the threshold).** The route saves the repeated prefix (P, every chapter's start added
up) and costs a pipe for the whole book, measured at 1.9-2.4 decodes per second of book. So a book takes it only when
`S = P - 2.0 x D >= MIN_SAVED_PREFIX_SECONDS`. Calibrated by the rule fixed in `scaling/calibrate.py` before its data:
break-even 241 s, threshold max(600, 540) = 600 s, frozen with its test before qualification (record section 13.4). The
prefix-only metric of the first design was dropped because its own calibration showed a 3-chapter 10-minute book 24 %
slower above it.

**Decision 5 (strictness).** End of stream counts only if the decoder exited 0 with exactly the declared samples. So a
book whose damaged frames FFmpeg skips with exit 0 (measured: 16,384 of 784,980 samples) fails on the continuous route,
where the seeking route had no such check and published shifted audio. A failed book stays failed; nothing falls back
part-way. A Cancel that stops the feed is reported as a Cancel, not as a decode failure.

**Decision 6 (the scenario).** `verify.py --mode qualification --scenario m4b-scaling` supervises
`files/dev-work/verification-gate/scaling/qualify.py` under the gate's job and budgets and reports its verdict; the
runner's exit status must agree with the verdict. Fixtures come only from the recipe into the ignored
`files/dev-work/m4b-scaling-cache/`, accepted by pinned hash; every benchmark run proves its output base is inside its own
folder before converting; the owner's Downloads output tree is compared before and after.

— Implemented by Claude Code under the owner's Phase 7B authority, 2026-11-10.

---

## 2026-11-10 - Phase 7A: the Converter's split slowdown is measured; one decode per book is proposed, byte identity is the oracle; nothing in the app changed (v0.7.2 Phase 7A, ACT72-012)

**Measured, not assumed** (`files/plans/ACT-v0.7.2-Phase7A-M4B-Converter-Baseline-and-Design.md`). Through the real Converter panel, headless, on validated synthetic books, against
`204c33b` and the working tree with the same FFmpeg 9.0.1: every production chapter costs about 1.3-1.6 s per hour of book
before it, spent decoding audio that the output-side seek throws away. That is most of a long split run (about 200 s of a
337 s run on a 6-hour 48-chapter book) and grows with every chapter (per-chapter time 4.1 s in the first quarter, 10.3 s in the
last). Per-chapter process starts and the cover pass are the rest; one preflight probe per book is not repeated.

**Decision 1 (the oracle):** production output is byte-stable: repeated runs give byte-identical MP3s on every book
measured, and `204c33b` matches the working tree byte for byte on the four books compared (10 to 500 chapters). So the compatibility classification for any faster route is byte identity
wherever the route applies, and today's route, unchanged, everywhere else (plan section 9.2).

**Decision 2 (what a chapter is):** the output-side `-ss S -t D` selects exactly decoded samples
`[half_up(S*rate), +half_up(D*rate))`, with S and D the microseconds FFmpeg parses from the "{:.6f}" strings (226 of 226
chapters on six books, exact sample equality). A one-decode route must reproduce that, at absolute positions, not "fix" it.

**Proposed for review, not decided:** candidate C1, one continuous FFmpeg decode per eligible book cut into those samples and
encoded through the existing `pcm_argv` / `run_argv_streaming` seams, with the cover pass, measurement and publication
unchanged. Its benchmark prototype was byte-identical to production on every eligible book and 1.7-2.6x faster on long or
many-chapter books (no growth with position, no extra disk, about 0.6 MB of audio buffered). C2 (cover in the same encode) is
faster still on short chapters but changes the leading Xing frame, so it is the owner's call. Eligibility, budgets and the
owner decisions are in the record (sections 7, 8, 10). The `-ss`-after-`-i` contract (`ACT.CONVERTER.PRIMING`) stays for
today's route; the new route would need the owner to approve its own contract.

**Method kept for 7B:** the fixture recipe, the headless panel harness with Job Object accounting, the selection probe and
the analysis stay in the ignored evidence folder for this checkpoint (several standing tests police files under the gate
folder, and no gate ran); 7B should promote them, with tests, into the reserved `m4b-scaling` qualification scenario.

— Implemented by Claude Code under the owner's Phase 7A authority, 2026-11-10.

---

## 2026-11-09 - The owner accepts v0.7.2 Phase 6 at 721c323; ACT72-030 waits for a later maintenance release; Phase 7A opens

**Accepted.** The owner accepted Phase 6 at `721c323`, in their words: "I accept ACT v0.7.2 Phase 6 at 721c323, including the
narrow work_area.py cleanup-guard exception. I approve deferring ACT72-030 until a later maintenance release while keeping it
open and tracked. The five documented cross-tool differences remain unchanged. Phase 7A is authorized."

- **Evidence carried forward (roadmap §13.3).** The full Windows gate ran on the final candidate `35de76a`
  (`2026-11-09_170309_full_7178`, PASS). `721c323` changed only `Briefing.md` and `Handoff.md`, so it carries that evidence;
  no gate ran on `721c323`, and none was rerun for this acceptance record, which is documentation only as well.
- **The cleanup-guard exception is accepted:** `test_cleanup_worker` names `work_area.py` for `os.rmdir` and `rmtree` and holds
  it to the catalog assertions (the final-candidate entry, Decision 2, near the end of this file).
- **ACT72-030 is deferred to a later maintenance release.** It stays open in the ledger with its removal proposal (the batch E
  entry, Decision 2); it is no longer Phase 6 work and blocks nothing in v0.7.2.
- **The five cross-tool differences stay as they are** (`files/dev-work/feature-map/consistency-matrix.md`).
- **crimson-audiobooks.** The owner confirmed that the `.gitignore` line it gained during Phase 6 is intentional. ACT never
  cleans or modifies that repository.
- **Next.** Phase 7A only: profile the M4B Converter's chapter split (ACT72-012), freeze a compatibility manifest and a
  performance baseline against `204c33b`, compare candidate designs and propose budgets. No production change to the split;
  stop for the architecture review before Phase 7B.

The Phase 6 batch A-E and final-candidate entries were appended at the end of this file instead of on top; being
append-only, they stay where they are.

— Recorded by Claude Code from the owner's message, 2026-11-09.

---

## 2026-11-09 - The Edge command line's M4B steps run through Phase 6C's supervisor with a deadline from the book's playing time; Ctrl+C stops the running step and the command line exits 130 (v0.7.2 Phase 6E, ACT72-010)

**Why.** ACT72-010: `epub2tts_edge.make_m4b`, reached only from the `epub2tts-edge --format m4b` command line, ran its two FFmpeg steps (the concat into FLAC-in-MP4, the AAC encode with the chapters) as blocking `subprocess_utils.run(check=True)` calls with no deadline. FFmpeg has its own hidden console, so Ctrl+C reached only Python, whose main thread waited uninterruptibly. Measured at `5a87ec3` with the real command line in a console of its own: Ctrl+C waited 28.6 s for a step slowed to a 30-second book's playing time, then ended with a traceback and `0xC000013A`; a suspended FFmpeg hung it for good.

**Reuse, and one opt-in addition.** `_run_ffmpeg` calls `subprocess_utils.run_supervised` and keeps its own rule (a non-zero exit raises `CalledProcessError`). The supervisor gains `deadline_seconds`, keyword-only, default `None`; no other caller passes it (a test holds that), so the MP3 Tool, the Maker and the Metadata Editor are exactly as Phases 6C and 6D left them. At the deadline the child is stopped and reaped by the same terminate-then-kill ladder and `subprocess.TimeoutExpired` is raised, the standard library's own contract for a timed-out child, distinct from a failure (`CalledProcessError`) and a Cancel (`ConversionCancelled`); a Cancel seen at the same look wins.

**How Ctrl+C reaches the step: recorded, not raised, while a step runs.** Raising `KeyboardInterrupt` in the supervisor's wait loop would also stop the child (its `finally`), but a second press during the stop could land between terminate and kill and leave a child that ignored terminate running; a negative control shows it. So `make_m4b` runs both steps inside `_ctrl_c_stops_the_step()`: on the main thread, with Python's own handler in place, SIGINT sets a flag; the steps run in a `cancellable` scope on that flag; the supervisor stops that very child within one look and starts no further step; on the way out the press is raised as the `KeyboardInterrupt` it was (also for a press after the last step, so nothing is published), and the handler is restored. A worker thread, or a program with its own SIGINT handling, is left alone. The rest of the command line still receives Ctrl+C as Python delivers it.

**The command line's endings.** `main()` prints one line and exits 130 for an interruption (128 + SIGINT, what shells report; Python's own uncaught ending on Windows was a traceback and `0xC000013A`) and 124 for a step past its deadline (GNU `timeout`'s status); a failed step still raises with exit 1, as before; `--help` lists them. Unpublished work is removed by the established owner, the conversion's work folder; publication is untouched, so nothing unfinished can reach the output folder.

**The deadline: the book's playing time plus ten minutes.** Measured on HOME-PC with the production arguments, the concat runs at about 2,600 times and the AAC encode at about 380 times the playing rate, linearly from 1 to 6 hours and the same on one CPU, so a working step would need a computer several hundred times slower to reach it, and a longer book gets a longer deadline. The playing time is read from the parts' headers (nothing decoded); an unreadable part counts from its size at 8 kbit/s, only ever longer. A progress-based limit, as `tts.ffmpeg_watch` uses for pydub, would end a stalled step sooner, but it needs a progress signal that these unchanged arguments do not promise (the output's growth or FFmpeg's statistics); the playing-time deadline needs only the headers. Ctrl+C remains the prompt way out.

**Not changed.** The M4B arguments, chapters, text track, audio, cover (`add_cover` after assembly), FFMETADATA escaping, publication, overwrite and refusal rules, output names; the narration part of the command line; Ctrl+Break and closing the console window; `batch_convert`.

**Verified.** The canonical changed-area gate PASSED on `6ef00fe` (`2026-11-09_081707_changed_17f9`): 49 of 49 journeys passed, 13,869 + 457 + 75 tests passed and 65 were skipped with policy-named reasons, and the inventory is current. `scripts/shared/subprocess_utils.py` (a `full_on` path) widened it to every test and journey. A changed run does not judge coverage satisfaction; the one full gate is reserved for the end of Phase 6. Not accepted until the checkpoint review and the owner say so.

— Implemented by Claude Code under the owner's Phase 6E prompt.

---

## 2026-11-08 - The Metadata Editor's chapter-title remux runs through Phase 6C's supervisor; Cancel stops it, Pause still lets it finish (v0.7.2 Phase 6D, ACT72-033)

**Why.** ACT72-033: both FFmpeg steps of the Editor's chapter-title remux (`shared/metadata._run_chapter_remux_step`) were a blocking `subprocess_utils.run`, so Cancel was seen only after the remux, its validation and the read-backs. Measured at `88451ec` with the Editor's own rebuild slowed to a 60-second Book's playing time: Cancel waited 58.6 s for FFmpeg to finish, and a Cancel latched between the two steps still started the 59.5 s rebuild.

**Reuse, not a second supervisor.** `_run_chapter_remux_step` calls `subprocess_utils.run_supervised` (v0.7.2 Phase 6C) for both steps and keeps every historical guard of its own: a non-zero exit raises `CalledProcessError` (the supervisor returns the code; `check=True` used to raise it), any output at `-loglevel error` raises `ChapterRemuxError` even with exit 0 (the 2026-09-20 truncated-chapter-track defect), and the argument vectors, `CHAPTER_REMUX_MOVIE_TIMESCALE = "1000"`, the stream copy and the freeform-atom restore are untouched. Outside a `cancellable` block a step runs to its end, so a caller without one keeps the established behaviour; the differences there are that stdin is the null device and each stream keeps its last 1 MiB (the remux writes nothing to stdout and, at `-loglevel error`, at most a few lines to stderr).

**The scope is the attempt; the predicate never blocks.** `m4b_metadata_batch.Attempt.run` enters `subprocess_utils.cancellable(controller.cancel_check, controller.checkpoint)` around the attempt's Books, exactly as the Maker's `Attempt.run`. `stage_book`'s own `cancel_check` closure is not used: it calls the checkpoint, which waits while paused, so it would claim PAUSED in the middle of a rebuild and hold FFmpeg's step open (a planted defect shows the tests see that). The runner's structural guard (`test_m4b_metadata_batch`) now admits `shared.subprocess_utils` for `cancellable` alone: the runner still starts no process.

**A Cancel is never a failure.** `ConversionCancelled` passes `_step` (as it already did), `stage_book` returns a cancelled outcome and discards the Book's staging, and the batch settles CANCELLED with the Book Not attempted and nothing offered to Retry Failed. `apply_chapter_titles`' existing `except Exception` removes the half-written `.retitle.tmp` sibling (the stopped child has been waited for, so the file is closed) and its `finally` removes the `chaptitles_` folder, so the remux leaves nothing even without the Editor's staging around it. Genuine FFmpeg failures stay ordinary retryable `chapters` failures.

**Pause** is never consulted while a step runs: the rename finishes, the copy is validated, and the run pauses at `stage_book`'s checkpoint before publication.

**Not changed.** The Editor's validation probes and `shared/metadata.py`'s chapter readers (short ffprobes; a Cancel during one is honoured at the next checkpoint), the command line's M4B step (ACT72-010), staging retention (ACT72-019, 031, 034, 037).

**Verified.** The canonical changed-area gate PASSED on `0e35ee5` (`2026-11-08_213207_changed_b535`): 49 of 49 journeys passed, 13,849 + 457 + 75 tests passed and 65 were skipped with policy-named reasons, and the inventory is current. `scripts/shared/metadata.py` (a `full_on` path) widened it to every test and journey. A changed run does not judge coverage satisfaction; the one full gate is reserved for the end of Phase 6. Not accepted until the checkpoint review and the owner say so.

— Implemented by Claude Code under the owner's Phase 6D prompt.

---

## 2026-11-08 - Cancel stops a running FFmpeg step in the MP3 Tool and the M4B Maker through one small supervisor; Pause still lets the step finish (v0.7.2 Phase 6C, ACT72-023)

**Why.** ACT72-023: both tools ran every FFmpeg and ffprobe step through a blocking `subprocess.run`, so Cancel was seen only at the next checkpoint. Measured at `56c3b55` on a one-hour source: Cancel waited 9.1 s (MP3 Write ID3), 9.0 s (MP3 Combine) and 27.0 s (Maker) for FFmpeg to finish on its own, and a Write ID3 run whose only Book was encoding when Cancel was pressed published that Book and settled SUCCEEDED.

**One supervisor, `shared/subprocess_utils.run_supervised`, in the module every child already goes through.**

- Small on purpose: no process-management framework and no patching of `subprocess`. Only the two tools' own FFmpeg wrappers call it (`mp3_processing.run_ff`; `m4b_maker_processing.run_ffmpeg`, `decoded_duration_us`, `ffprobe_duration_ms`). The M4B Converter keeps `m4b_execution.run_argv`, TTS keeps `ffmpeg_watch`; the Metadata Editor's remux (ACT72-033) and the command line's M4B step (ACT72-010) are separate slices.
- Output to two delete-on-close temporary files, not pipes: nothing can block on a full pipe and there is no reader thread (v0.7.1's low-memory lesson); each stream keeps its last 1 MiB, enough for a probe's output and a failure's reason. stdin is the null device; the child is started through `popen`, so it gets no console window.
- Ownership is the `Popen` handle: a stopped step is `terminate`d, then `kill`ed, through that handle only, with at most 2 s of waiting after each; never a name or a bare process id, so an FFmpeg this same process started for anything else survives. FFmpeg and ffprobe start no children, so the handle is the whole tree; no Job Object. An exception while watching also stops and collects the child.
- `subprocess_utils` must import alone: `ffmpeg_health` imports it bare before the venv exists, and the optional-setup planning worker runs on a reviewed source closure (`optional_setup_planning_bridge_v3.SOURCES`) that carries it without `shared/cancellation.py`. Its module-level imports therefore stay standard-library only, and `ConversionCancelled` is imported only where a Cancel is raised, which neither ever reaches. The first candidate imported it at module level and every planning run failed in its gate (Handoff); the closure was not widened instead. `shared/cancellation.py` itself is unchanged (its names are pinned).

**Cancel reaches it through the worker: `subprocess_utils.cancellable(cancel_check, acknowledge)`.**

- A context variable on the worker thread. The MP3 run functions take a new `cancel_check` (the panel passes the controller's) and enter the block; the Maker's `Attempt.run` enters it around the whole attempt, so the batch's own checks of a kept candidate and of a numbered one are covered too.
- The predicate is the controller's non-blocking `cancel_check`, never its `checkpoint`: the checkpoint waits while paused and would claim PAUSED in the middle of an encode (a planted defect proves the tests see that). So Pause still lets the running step finish and takes hold at the next checkpoint, as the feature contracts approve.
- `acknowledge` is the controller's `checkpoint`: once the child is gone it records that the worker observed the Cancel and raises `ConversionCancelled`, so `finish_cancelled` can settle the run. A Cancel already latched starts nothing, which matters where no checkpoint lies between two steps (a track's duration probe and its encode).

**A Cancel is never a failure.** `run_ff` lets `ConversionCancelled` through before its broad `except` (it would otherwise have become the 999 launch-failure code and a retryable track); the Maker's `run_ffmpeg` raises it, never `CalledProcessError`, so a Cancel never falls back from FAST to Safe; `validate_staged_m4b` and the batch's numbering check let it through instead of reporting an unreadable file or a numbering failure.

**What a stopped step leaves.** The MP3 Tool removes the half-written staged track or combined file of the step it stopped, as it already did for a failed one; the rest of `.work` stays (ACT72-037, unchanged). The Maker removes the Book's staging as before, and a candidate kept from an earlier attempt when Cancel arrives while it is checked or numbered (Cancel at the checkpoint after it already did). Nothing of a cancelled step is ever published.

**Closing the window.** A panel's close-time Cancel now reaches its running step too, but `close()` does not wait for it, so the launcher's stop of its own FFmpeg children stays the guarantee. The gate's orphan control (`control.act-orphan-seen-without-the-stop`) therefore takes both stops away: with only the launcher's switched off, the supervisor stopped FFmpeg first in the first candidate's gate and the control saw no orphan.

**`run_ff`'s text.** FFmpeg's bytes are decoded as UTF-8 with replacement, universal newlines kept. Before, `text=True` used the locale code page, where one undecodable byte would have turned a whole call into the 999 failure (read from code, not observed).

**Verified.** The canonical changed-area gate PASSED on `9c4a93e` (`2026-11-08_184018_changed_a931`): 49 of 49 journeys passed (the orphan control saw the FFmpeg left running with both stops disabled), 13,835 + 457 + 75 tests passed and 65 were skipped with policy-named reasons, and the inventory is current. The change to `scripts/shared/` widened it to every test and journey. The first run, on `765d4fd`, failed the `v3-planning` guarded group and the orphan control (`2026-11-08_164449_changed_42b3`); see the Handoff. A changed run does not judge coverage satisfaction; the one full gate is reserved for the end of Phase 6. This is not accepted until the checkpoint review and the owner say so.

— Implemented by Claude Code under the owner's Phase 6C prompt.

---

## 2026-11-08 - The TTS routes' temporary files live in an owned work area, and a run's start removes only what is provably a dead owner's (v0.7.2 Phase 6B, ACT72-009)

**Why.** ACT72-009 (Major): a killed program's `epub2tts_*`, `tts_direct_*`, `tts_local_*` folders, pydub temporaries and encode WAVs lay loose in `%TEMP%` under names any program could have chosen, so nothing could ever safely remove them (31 such folders were found in HOME-PC's TEMP at entry). Plan §11.5 and §13.1.

**Where: `%TEMP%\act-tts\<16-hex token>\<n>`, in the system temp folder.**

- Not the app folder: a narration WAV can be gigabytes, and the app may sit on a synced Desktop or a small drive; the temp folder is where these files always went. The gate's and the tests' redirected TEMP contains it.
- Short names on purpose: a book's own name is used inside an entry. 9 to 11 characters more than the old layout.

**Ownership is a manifest, never a name, an age or a process id alone.**

- `owner.json`: schema, token (the folder's name), the workspace's own path, the owner as process id **and** creation time, and every entry with kind, retention (`disposable`) and state (`active`, `finished`).
- An entry is in the manifest, fsynced and replaced in one operation, before its folder exists; a process killed at any instant leaves nothing of its own unlisted.
- An owner is gone only when no process has its id, the one that has it was created at another moment, or it exited. Anything unverifiable keeps its files. Nothing of TTS scratch is resumable; any other retention is kept.
- A workspace lasts while it has entries. One process, one workspace: no cross-process sharing.

**Recovery: at each run's start, bounded, quiet about the normal case.**

- The panel's run start (worker thread) and `run_batch_convert`. 5 s and Cancel bound it; the rest waits for a later start. No launch-time sweep.
- A running owner is counted, not reported. Everything else left is named in Detailed with its reason.
- Another process's leftovers are recovered on Windows only (creation time is read only there); elsewhere they are left, and only a process's own entries are removed.

**Removal is handle-based and never follows a link.**

- The temp folder, `act-tts`, the workspace and every folder being emptied are held without delete sharing, so none can be renamed or replaced meanwhile. A pin needs `FILE_LIST_DIRECTORY`: a handle with attribute access only takes no part in sharing checks (found in review before any test ran; a planted defect proves the test sees it).
- Each entry is opened without following a reparse point, judged by that handle and deleted through it. A link is left and reported; a hard link loses only this name. Measured on HOME-PC NTFS (`act72-009/probe-pinning.txt`).
- Another look (at most three, under a second) only when everything in the way is momentarily held; never for a link or a refusal.

**pydub's temporaries** are made in the `controlled` block's own entry, made at the first one, and that entry is removed after `remove_temporaries` has closed them; a failed export's open handles never block the removal.

**Kept as it was.** The output-tree sweeps (exact name, process id and an hour's age; unchanged), Qwen3's job folders in `files/runtime-data`, and the other tools' staging (ACT72-019, 031, 034, 037). Legacy loose folders are never touched; they are the owner's to remove.

**Verified.** The canonical changed-area gate PASSED on `dc74a3c` (`2026-11-08_094047_changed_0e49`), its first run: 49 of 49 journeys passed, 13,795 + 457 + 75 tests passed and 65 were skipped with policy-named reasons, and the inventory is current. The README repair widened it to every test and journey (no selection rule covers that path). The first run, on `964e9a3`, failed two whole-source guards (`2026-11-08_085037_changed_6519`); see the Handoff. A changed run does not judge coverage satisfaction; the one full gate is reserved for the end of Phase 6. This is not accepted until the checkpoint review and the owner say so.

— Implemented by Claude Code under the owner's Phase 6B prompt.

---

## 2026-11-08 - A Qwen3 voice at 920x600 shows its disclosure compactly; the setup logs follow like the tools' logs (v0.7.2 Phase 6A)

**Why.** Phase 5 recorded ACT72-058 as the owner's call and ACT72-059 as a Phase 6 Minor. The owner accepted Phase 5 and authorized Phase 6, limited for this session to these two issues.

**Qwen3 at 920x600: compact only where the full disclosure cannot fit (owner-approved).**

- The owner approved a compact presentation of the hardware and speed disclosure (Q3/Q7) at the minimum size, with the complete text available through an accessible, clearly labelled details control. The minimum size, the queue and log floors, the model's state line and Install / repair all stay; no whole-panel scrollbar.
- The compact form is one **Hardware and speed...** button on the Install / repair row, which shows the complete text in a message box. Measured at 920x600: Voice & Audio may be 241 px tall there, and an absent Qwen3 voice already needs 236 px for the engine line, the 3-line state line and the Install row. No separate short summary line fits beside that, so the button's own label is the compact presentation. Its label is short enough to share the row (127 px; "Hardware and speed details..." at 164 px would not).
- The choice is measured, never a pixel constant or a window size: the layout measures Voice & Audio both ways and uses the compact form only when the split arrangement fits with it and not with the full text. Every arrangement is measured from the full presentation, so re-measuring while compact cannot mistake the compact height for the full one. "wide" and "stacked" always show the full text.
- The details button is information, not a processing control, so it is not locked during a run (like Clear Log and Open Output Folder).

**Setup logs: the tools' follow rule, written where setup can use it.**

- The first-run and repair windows (`shared/bootstrap.py`) and the optional-voices panel follow a reader at the bottom (the newest line on screen, even partly) and hold a reader who scrolled up, the rule ACT72-005 gave every tool's log. Tk keeps the top line through an insert below the view, so holding needs no anchor of its own.
- `bootstrap.py` runs before the app's environment exists and imports only standard-library-only modules, so it cannot import `shared/job_ui.py`. The rule is one helper there, `_append_following`, for its two windows, and the same three lines in `OptionalSetupPanel._append`; no shared module and no framework were added.
- The optional-voices panel was not named in ACT72-059 but is the step the first-run window shows next and had the same defect. It was fixed under the same issue rather than left as a new one.

**Verified.** The canonical changed-area gate passed on `69514f9` (`2026-11-08_022917_changed_6d03`), its first run. The shared setup modules widened its selection to every test and journey:
- 49 of 49 journeys passed;
- 13,747 + 457 + 75 tests passed and 65 were skipped;
- the inventory is current (273 features, every source file reviewed as it is now).

A changed run does not judge coverage satisfaction; the one full gate is reserved for the end of Phase 6. This is not accepted until the checkpoint review and the owner say so.

— The compact presentation approved by the owner; implemented by Claude Code under the owner's Phase 6A prompt.

---

## 2026-11-07 - Unset is an absent key; a log pane follows only while its newest line is on screen; a Qwen3 voice at 920x600 is the owner's call (v0.7.2 Phase 5)

**Why.** Phase 5 corrects the known log, metadata and optional-state defects (plan §11.2 to §11.4, Phase 5) found by Phase 0 and the Phase 4 inventory: ACT72-005, 006, 007, 008, 020, 044, 045 and the `models_status` half of 057. Each was reproduced on `fa9d3c3` before it was fixed, and each new test was seen failing under a planted defect after a no-change control passed.

**MP3 metadata: unset means an absent key, never an empty string.**

- A Book's first files fill a field only when the Book has no value for it at all. A value typed before the import, a field cleared (stored as `""` by `set_book_field`), a duplicate's carried values and the values an emptied Book kept are the session's own.
- No provenance or "dirty" framework was added: key presence already said what the contract needs (plan §11.3). Any edit is an explicit value, so typing into a field and deleting it again is a deliberate blank.
- An emptied and refilled Book keeps the values it held, including ones its earlier files suggested. They are existing session values, which outrank an import's suggestion.
- Import Folder still replaces every Book after its confirmation, by design. Shared values survive it and still win the output.
- The M4B Maker (no prefill) and the M4B Metadata Editor (prefill is display only) already behaved this way; only the MP3 Tool wrote over the session.

**Log panes: follow while the newest line shows, otherwise hold.**

- "At the bottom" means the newest line is on screen, even partly: a tolerance under one line. One wheel notch hides it and holds the view; a scrollbar thumb dragged to within a line of the end follows.
- Each pane keeps its own answer. It is read from the screen whenever the pane has been laid out, and kept for the two moments the screen cannot answer: an unopened tab (one pixel high) and a resize, where a following pane is put back at the bottom before it is redrawn.
- A render changes only the lines that changed: an append, the lines trimmed off the front, or the tail from the first differing line. Tk then keeps a held reader's top line itself, to the pixel. The pane is only moved back explicitly when a rewritten tail reaches the reader's own line.
- Clear Log leaves a pane following. Everything runs on the thread that owns Tk; the guard is unchanged.
- The setup windows' progress logs in `shared/bootstrap.py` always jump to the newest line. They are not the tools' log view and were left alone: ACT72-059, Phase 6.

**Optional voices at 920x600.**

- The Kokoro notice steps aside while the setup line ("not installed ... Install & Continue") shows, so one message is shown at a time. Its wording no longer promises a first-run download, which stopped being true in v0.7.0.
- Every Kokoro and Chatterbox state now keeps Start and Cancel on screen at 920x600.
- **A Qwen3 voice at 920x600 is not fixed here (ACT72-058, Phase 6).** Measured: both columns of the split layout have 8 to 26 px to spare at their floors, and the Qwen3 messages need 10 px more installed and 63 px more absent. Making room means giving something up at that size: the owner-required hardware and speed disclosure (Q3/Q7), the Install / repair button's own row, or a floor that keeps the queue or the log usable. That choice is the owner's. The minimum size was not raised, and nothing else was squeezed to pass.

**Tests state the machine they assume.** The Qwen3 panel tests now say whether the engine is installed or this is a fresh install, through the panel's own `installable` and `install_dialog` seams. They no longer read the real machine, so they pass the same way on a fresh checkout and here. `voice_install.models_status` is tested unreplaced against real stand-in files. Both are asset health only, never engine qualification.

**Smaller fixes.**

- **Artwork buttons:** they take their label's natural width (`width=0`) instead of a fixed 7 or 5 characters, which cut "Choose…" to "Choose." in the MP3 Tool, M4B Maker and Metadata Editor at every size. The MP3 Tool's artwork gap is now the fields' own 6 px, since its 920x600 row had no pixel to spare. Aqua keeps 8.
- **Edge rate:** Start refuses an Edge rate the Edge library refuses (`^[+-]\d+%$`, the pinned `edge_tts` 7.3.1's own check), before anything is frozen or reserved, and only when folder-imported files would send it.
- **Button wording:** every "try again" message names the button the person sees, Start, not "Create".

**The inventory moves on.** `coverage_model.INVENTORY_PHASE` is now 5, so a planned gap must belong to Phase 6 or later. Two planned entries still marked Phase 5, ACT72-053 and 054, were set to 6, which their ledger already said. ACT72-057's PDF half stays open, as Phase 8, the phase the feature map already gave it.

**Native evidence.** A new journey, `mp3.typed-values-survive-first-import`, types and clears with real keys before a real Add Files, then reads the published tags. It also turns the real wheel over the Summary pane across three runs. The gate gained a guarded `wheel` verb, and its channel reports a Text pane's top line and whether the newest line shows. Run against `fa9d3c3`'s two source files, the journey failed on both defects.

**Verified.** The full gate passed on `607ae39` (`2026-11-07_205607_full_5196`), its first run:
- 49 of 49 journeys passed, the new one included;
- 13,730 + 457 + 75 tests passed and 65 were skipped;
- 262 of 262 required features are mapped and were satisfied by routine evidence;
- release-pending: owner checks on 19 features, planned gaps on 60, qualification on 27;
- `release_ready` is false.

This is not accepted until the owner says so.

— Decided and implemented by Claude Code under the owner's Phase 5 prompt; ACT72-058 awaits the owner.

---

## 2026-11-07 - The coverage inventory is reviewed and the gate keeps it current; release-pending evidence is kept apart from routine evidence (v0.7.2 Phase 4)

**Why.** Phase 4 completes the feature map (plan §7 and §14, Phase 4). The inventory had to become complete enough to trust and hard to let drift. The owner's Phase 4 prompt names the defects it must detect: an unmapped control or workflow, a deleted or renamed test, a missing scenario, a dangling feature id, required verification that did not run, an unapproved exception, and a source change without mapping review.

**One inventory, schema 2.** `coverage.json` holds:

- 273 features, 262 of them release-required, with their source symbols, contracts, `--feature` selection and verification;
- the reviewed index of 298 static and 246 live surfaces, each mapped to a feature;
- a review stamp for each of the 144 reviewed source files: the application's Python by the suite's registry, the two Setup_and_Run launchers and `bootstrap_host.ps1`;
- the issue ledger.

The eight documents in `files/dev-work/feature-map/` describe features by id and hold no test ids, so nothing in prose can drift from the inventory.

**Routine and release evidence are kept apart.**

- **Routine kinds** are what a routine full run executes and must satisfy: `behavior` (an exact test id), `native`, `media`, `control` (a gate negative-control journey) and `discovery` (the live scan).
- **Release kinds** are never satisfied by a routine run. They keep `release_ready` false without failing the run:
  - `qualification`: one of the four named scenarios;
  - `owner`: a check only the owner can make;
  - `planned`: a known gap, which must name an open issue in the ledger and a phase after 4.

This keeps missing behaviour visible without turning the routine gate red. A full run fails on a mapped routine verification that did not pass, never on a planned gap.

An agent cannot approve an exception. An exception needs `approved_by: owner` and evidence of where the owner approved it, and the real inventory has none.

**Discovery is static and live.**

- **Static discovery** reads the application's own files, found by `source_probe`'s registry, never by walking `scripts/`. It lists every control constructed directly, every standard dialog raised, every event or window protocol bound and every tool registered. Keys are file, class or function, control class and label, never line numbers.
- **Live discovery** covers what static discovery cannot see: controls a helper builds or a loop multiplies. The `inventory.live-surfaces` journey opens a real isolated instance and, by real input, visits the shell, the six tools, Preferences & Data and one voice of each of the four engines. It names each interactive widget by the attribute path its panel keeps it under. The walk reads `__dict__`, `__slots__` and containers only, and runs no property or method. Every one of the 246 live controls got a key; none was anonymous.
- **Its negative control.** The `control.unmapped-live-control-is-caught` journey adds one unplaced button to a real panel and must see exactly that one reported.

**A source change cannot pass without review.** Each reviewed file carries the digest it had when its features were last reviewed. Any of these fails the `coverage-inventory` check, and with it a full or changed run:

- a file that changed since its stamp;
- a new or removed file;
- a file no feature names.

The check is required in full and changed runs and reported in focused ones. `test_verification_coverage.py`, which every changed run now selects, runs the same check.

`helpers/inventory.py restamp <paths>` records a review by name only; nothing restamps wholesale. Every later phase that changes source will restamp. That is the maintenance decision 23A asks for.

**Gaps found, and what was done with them.**

- **Tests added.** Four required features had no routine evidence, and each now has tests, seen failing under a mutant first:
  - Open log folder;
  - the no-window guard, tested in a child interpreter so the test process is untouched;
  - the Metadata Editor's Open Output Folder;
  - the Metadata Editor's Cancel Import, with its scan confirmations.
- **Recorded, not fixed.** 25 new findings (ACT72-025 to 049) and 8 groups of untested branches (ACT72-050 to 057) are in the ledger, each tied to its features as a planned gap. Phases 5 to 8 own them.
- **Tests corrected.** A Maker test that asserted nothing (`or True`) now checks what its name says. Two weak Maker tests remain on the ledger as ACT72-032.
- **Fixed or corrected here.** ACT72-024 is fixed. ACT72-035 was a wrong statement in the Briefing, now corrected.

**How the slices were drafted.** Nine read-only agents drafted the slices from the source and the tests. Every test id, scenario layer, symbol, file and surface key was then checked mechanically against the collection at `118058c`, the journey registry and the source's AST, and the maintenance check runs on the result. Two of the drafts' claims were re-read in the source before they were used: the vacuous Maker test and the Metadata Editor's missing subfolders option.

**Routine evidence must run where the gate judges it.**
- The first full gate failed `coverage`: `927df46`, run `2026-11-07_152200_full_9f54`.
- The cause: two required features were mapped to tests that the skip policy always skips on Windows (`native-macos-only`, `no-symlink-privilege`). A skipped test is not a passed one, so it never satisfies.
- The fix was a Windows test of each contract, not a weaker requirement: an overlap check in the real shell for `ACT.MP3.LAYOUT`, and a junction source for `ACT.SHARED.OUTPUT-PATHS.REPLACE` (`7987503`).
- Changed runs do not judge satisfaction. So a new mapping is re-judged against a full run's real outcomes before the next full gate.

**Verified.** The full gate passed on `7987503` (`2026-11-07_170231_full_b8a6`):
- 48 of 48 journeys passed;
- 13,655 + 457 + 75 tests passed and 65 were skipped;
- 262 of 262 required features are mapped and were satisfied by routine evidence;
- release-pending: owner checks on 19 features, planned gaps on 70, qualification on 27;
- `release_ready` is false.

This is not accepted until the owner says so.

## 2026-11-07 - The journeys' application runs at Low integrity so its file dialogs cannot write the owner's history, and the launcher owns its Tk root (v0.7.2 Phase 3 acceptance closeout)

**Why.** The checkpoint reviewer withheld Phase 3 acceptance for two issues: the native file-dialog journeys modified the owner's Windows recent-file history, and real ACT still crashed with `Tcl_AsyncDelete` once the two accidental holders of its closed Tk root were removed.

**The owner's dialog history is protected by Windows itself, not by restoring it.** Measured read-only on 2026-11-07, the Phase 3 gate left 94 values naming `act-gate` in the owner's hive: 92 in `ComDlg32\OpenSavePidlMRU`, 1 in `ComDlg32\LastVisitedPidlMRU` and 1 in the Shell `BagMRU`. The Recent folder (809 links) and the jump lists held none, so Tk's dialog does not add to Recent documents. The gate now starts the application under test at Low integrity from its first instruction (`adapters/windows/containment.py`, `CreateProcessAsUser` with the gate's own token duplicated and lowered; no privilege, no administrator, no account, no system setting). Windows then refuses that process and its children write access to everything labelled above Low, which is all of the owner's per-user registry except `Software\AppDataLow`, and the owner's profile folders except `LocalLow`. Only the scenario's own scratch under `%TEMP%\act-gate` is labelled Low, so the application can write there and nowhere else. Nothing in the owner's registry is written, snapshotted or restored, so an interrupted run, a crash, or the owner using a file dialog during the run leaves nothing to undo and nothing of theirs can be overwritten. The dialogs stay the real Windows dialogs, driven by the same real keystrokes.

**Refusal.** Before any scenario the runner's preflight starts a Low child exactly as a session does; it must be refused write access (an open, which writes nothing) to every dialog-state key and both hive roots, opened through `HKEY_USERS\<sid>`. Otherwise no scenario runs and the stage is BLOCKED. Each session checks from outside that every process in its job is Low, and checks the dialog's owner again before typing into any file or folder dialog. The runner reads the history (KEY_READ) before and after; the judge fails a run that lacks the contained preflight or the reading after, or that added a value naming `act-gate`.

**Alternatives rejected, on evidence.** A process that starts at Medium and lowers itself keeps the handles it already had: its cached `HKEY_CURRENT_USER` handle still granted write access (measured), so the process must start Low. Opening the root through the `HKEY_CURRENT_USER` handle returns that cached handle without a fresh access check, even in a process born Low, so the preflight opens through `HKEY_USERS\<sid>`. A separate Windows account needs an administrator, a new account on the machine and access to the owner's profile: system changes. Snapshot and restore writes the owner's registry, can overwrite a change the owner makes meanwhile, and cannot run after a crash. Redirecting `HKEY_CURRENT_USER` to a private hive was tried as a positive control and could not be used: Windows refused to label a private app hive Low (access denied, even at Medium).

**What is and is not proven.** Proven: born Low, every dialog-state key and both hive roots refuse write access (5), and the same probe at Medium is granted every one (0); a real Tk file dialog in a Low process, driven by real keystrokes, opened and returned the typed file, and a whole-hive read found no value naming its sentinel, the watched keys' values and last-write times unchanged. That the dialog writes this history at Medium rests on Phase 3's own 94 values. Not proven by a direct trace: that the Low dialog attempted its write and was refused (no in-process capture was possible without writing the owner's registry). A backup taken now cannot restore what Phase 3's values pushed out of the owner's lists, and nothing was removed: those 94 values remain, and clearing them is the owner's decision.

**Task B: the launcher owns its Tk root.** `launcher.main()` keeps the root in a module global, `launcher._ROOT`, in the statement that creates it. Before this, only `shared.output_paths._HINT_DISPLAYS` and `shared.appearance._listeners` happened to keep the closed root reachable. Held deliberately, the Tcl interpreter is deleted only when Python shuts down, on the main thread, once it no longer runs daemon workers. Nothing else changed in the application: no exception is caught or hidden, Cancel and the Phase 2 contracts are untouched, and closing stays prompt: in the full run the plain closes took 0.09 to 0.28 s at Low, against Phase 3's 0.08 to 0.27 s. The forced arms on all six tools now empty both accidental lists first, so the application's holder alone is tested, and each records that the surviving root is `launcher._ROOT`. `control.act-crash-seen-with-the-root-released` removes that holder too and must still crash. This supersedes "guarded rather than changed" in the 2026-11-06 entry: the root is no longer held by accident. `files/tests/test_root_lifetime.py` runs the real `launcher.main()`. On `f0e2d47`, with both lists emptied, it crashed `0x80000003`. On `118058c` it exits 0, with a full collection proven to run on a worker.

**Verified.** The full gate passed on `118058c` (`2026-11-07_092441_full_3470`): 46 of 46 journeys at Low, 13,609 + 457 + 75 tests passed and 65 skipped. Values naming `act-gate` in the owner's history numbered 94 before the journeys and 94 after, with 0 added. All six forced arms exited `0x0`, and `Tcl_AsyncDelete` appeared only in the two crash controls.

**Remains, not fixed here.** With the root held, a worker's collection of a leftover `tkinter.Variable` or `Image` still prints `RuntimeError: main thread is not in main loop` (ignored, visible on stderr, exit 0), as Phase 3's Metadata and TTS forced arms already did. Each one waits about a second, which is why the TTS and Cover forced arms took 23.0 s and 17.5 s to exit after the window had gone. It is not a crash and is not hidden. Finalising those objects on the main thread would be a separate, owner-approved change. — Claude Code, 2026-11-07; owner acceptance pending.

## 2026-11-06 - The owner approves %TEMP%\act-gate; Phase 3 builds the native and real-media stage, and closing a window while a tool works now ends its FFmpeg (v0.7.2 Phase 3)

**Phase 2 is formally accepted for progression, and the owner approves `%TEMP%\act-gate` as a narrowly scoped exception to repository-only scratch.** The conditions are the owner's: only uniquely identified ACT-owned scratch may be created or cleaned; another application's files and an active process's workspace are never deleted; meaningful failed-run diagnostics are preserved inside repository evidence; exact ownership and inactivity are verified before abandoned ACT scratch is removed; historical verification evidence is preserved; there is no general TEMP sweep and no system-wide configuration change. This replaces plan section 13.1's "all inside the repository" for this one root only. `helpers/scratch.py` keeps the conditions: each child carries `act-gate-owner.json`, naming its run and the exact process; `--audit-scratch` reports and removes nothing; a failed run copies its failing tests' temp folders into `failed-scratch/`, with a limit, and says what it left out. The positively identified leftovers named in the Phase 2 report were cleared the same day, 26 paths and 11.1 GiB with failure evidence copied first. `%TEMP%\act-espeak-ng` belongs to the application (`shared/espeak_data.py`) and was left alone. — Approved by the owner on 2026-11-06.

**The native adapter is the Phase 0 choice, with three corrections from measuring it.** Standard-library `ctypes` input, Pillow and a test-only observation channel. `PrintWindow` is rejected: a second call left Tk's main thread unresponsive for over 30 s, and a test tool must not disturb what it tests. Screenshots therefore take the client area only, and only when nothing covers it, because the frame's invisible border and rounded corners show whatever lies behind, which was the owner's other windows. The ALT tap is rejected for taking the foreground, because it lands on whatever has the foreground at that moment; a zero key event unlocks `SetForegroundWindow` and means nothing to anyone.

**Revealing a folder is recorded in the isolated instance, not performed.** A finished Converter run opens Explorer, which left windows on the owner's desktop and took the foreground from the journey. The guard refused correctly; that is how it was found. The journey checks that the application asked and for which folder, so what Explorer does with that request is not verified here.

**TTS's real-output journeys replay speech at `edge_tts.Communicate`, with real MP3 frames; the requests, assembly, encoding and publication after that point are production's.** The routine gate has no network, so this cannot be Microsoft's engine, and the evidence says "replayed" and claims no engine qualification. `tts.kokoro-local` is the one real engine, from a real click to real speech, applicable only where the package and model are present, and one sample is not the `optional-engines` qualification.

**Closing a real window while a tool worked was a measured defect, now fixed in production.** Closing M4B Maker mid-build left FFmpeg running after the application had exited, with nobody to publish its result. `MP3ToolUI`, `M4BMakerUI` and `M4BMetadataEditorUI` had no `destroy()`, so a closing window never reached `close()`; and FFmpeg under the blocking `sp.run` cannot be cancelled once started. Each panel now has the `destroy()` the other three had, and `launcher.main()` calls `sp.stop_media_children()` after the main loop. That ends only processes whose parent is this very process and whose image is FFmpeg or ffprobe, so a sentinel FFmpeg elsewhere and the deliberately detached repair and cleanup helpers are never touched. It does not make Cancel prompt in Maker or MP3 Tool: a running FFmpeg step still has to finish before their Cancel settles, read from the code and unmeasured, and cross-tool Cancel is Phase 6's.

**The Phase 2 Tk crash is reachable shape, kept away by two accidents, and now guarded rather than changed.** With one full collection forced onto a worker after a real Alt+F4, the real application exits 0 on all six tools, because its closed root stays reachable from two module-level lists: `shared.output_paths._HINT_DISPLAYS` and the `shared.appearance` listeners. Emptying both makes the real application crash with `0x80000003` and `Tcl_AsyncDelete` (`control.act-crash-seen-with-the-root-released`). So a clean exit here depends on those two lists, and the forced arms fail once both stop holding the root; either one alone is enough to keep it. The crash with both emptied was measured on Cover Image. The TTS forced arm's recorded holder is a frame of `launcher.py`'s `__init__`, unresolved, so the lists are not shown to be the only route with TTS open. Holding the root deliberately for the process's lifetime would be one line and is left for the owner to decide, because nothing observed in production needs it today. The same arm shows `Variable.__del__` on a worker waiting about 1 s per variable, 22 s for the TTS panel; a real close does not wait for that, exiting in about 0.2 s, because the interpreter ends its daemon threads.

**A focused run can now be journeys alone, and the gate runs them first.** The stage needs the desktop while someone is at it, and an 85-minute suite first could find the session locked. A locked desktop is BLOCKED and the rest of the run still happens. A full run now takes over the mouse and keyboard for about six minutes at its start. `requirement:native-journeys` and `requirement:real-media-journeys` are gone from `later_phase_requirements` because they are now enforced checks.

**The oracle measures what decodes, never what a header claims.** Its own negative control found this: a truncated MP3 keeps its Xing header, so ffprobe reads the full length and the decoder has no complaint.

— Directed by the owner on 2026-11-06; implemented by Claude Code.

---

## 2026-11-06 - Phase 2 closeout: verification is targeted first, four lost test requirements are back, and the Tk warning was a crash held off by accident (v0.7.2 Phase 2; corrects the entry below and the Handoff)

**Verification is targeted first, with one planned full gate per phase. This is the owner's standing rule for the rest of Phase 2 and every later phase.** Individual affected tests after each small change; focused mode for affected modules and shared invariants; changed mode near the end of a slice, with its selection reviewed for omissions; full mode once, on a committed candidate, when the whole authorized phase is stable. If that gate fails, the defect is fixed with targeted tests and the gate reruns only when the corrected candidate is ready. A documentation-only closeout carries the evidence forward under plan §13.3. A PASS is never claimed from partial evidence.

**Four test requirements had been lost; the identity map's "nothing lost" was wrong.** An independent audit of the 38 retired ids (`2026-11-06_phase2_closeout_0466/retired-ids-audit.md`, which supersedes `removed-ids-map.md`) classed them as 2 obsolete, 23 renamed with equivalent coverage, 9 strengthened and 4 real losses. None made the gate report a false result. All four are restored: a repeated option is refused again (the old action had not been carried over, so `--status <missing> --status <good>` read PASS and `--platform macos --platform windows` stepped around the platform refusal); an empty value is refused (the empty case of the label test was never sending an empty label); a failing static gate stops nothing and the report says so (nothing asserted `RESULT: FAIL`); and a file holding a drawn run name is left alone.

**A run is current only where the gate wrote it (plan §10).** A copy normally keeps its folder name, and its id, nonce and manifest travel with it, so `--status --require-current` read a copy, or a run reached through a junction or `..`, as `current: exact`. It now reads `current: elsewhere` and exits 3. An artifact reached through a link makes the run INVALID. This catches accidents and stale copies, not forgery: a result rewritten and resealed in place still reads PASS, which is the documented non-goal of the seal.

**The Tk warning was a crash held off by accident. This corrects the guess in the Handoff that the session probe and JUnit report caused it.** The cause was measured, not inferred. `TkPlanningHarness` opens its own root and leaves it in a cycle when it closes, and `tk_gate`'s rule that no worker starts while a Tk object waits to be collected applied only inside shared-root scopes. So the next collection decided. On the main thread nothing happens. On a worker, the interpreter is deleted on the wrong thread: `Tcl_AsyncDelete: async handler deleted by the wrong thread`, and the process ends with `0x80000003`. A variable in the same cycle raises `RuntimeError: main thread is not in main loop` first, and pytest's unraisable hook keeps that exception, whose traceback happens to keep the root alive until the main thread releases it. That is the warning in the logs. Forcing a collection onto a worker at each test of the real guarded group crashed it within a minute, and disarming the harness's variables crashed it sooner, by removing the accident. Where a collection lands follows allocation history: in a controlled comparison the old arrangement warned in 3 of 3 runs and the new one in 1 of 3, the reverse of the rate that prompted the question, so the probe and report only moved the landing. `tk_gate` now collects on the main thread at `Thread.start` whenever a non-shared root still exists, and closing a root reopens that boundary within the test. Nothing is filtered, and no production code changed.

**Open for Phase 3, not fixed here.** The crash needs a closed root collected on a worker. Production's tools run `mainloop()` with daemon workers, so closing a window while a worker runs is the shape to test: measured acceptance is a clean exit code from that journey. Nothing suggests a mid-session path, because `bootstrap.py`'s dialogs run in a separate process (the launcher cannot import it), but this is from reading the code, not from a run. `TkPlanningHarness` is imported only by tests today. Its `close()` must not simply disarm its variables, for the reason above.

**What the settings redirect cannot reach, a guard now sees.** The session redirects `shared.paths` for its own process, once conftest has run, so a literal path, a child interpreter or an import-time write goes past it, and on a disposable checkout such a write to `settings.json` passed with nothing said. `conftest.py` now guards the real settings file around every test and all the real runtime data once per session, measured from `pytest_configure`, before collection imports anything. This detects after the fact and names the test; it does not prevent the write. It is still not the per-child-environment redirection plan §13.1 words, because production reads no such variable and adding one would be a production change for a test's benefit. Collection and startup on the real tree changed none of 842 observed entries.

**A refused write ends the refused call.** On Windows `tempfile` takes a `PermissionError` from the OS call to mean a folder holds that name and tries the next, up to `TMP_MAX`, 2**31 - 1. So a tripwire refusal inside `mkstemp` or `mkdtemp` never returned: it was still going after 300 s and reached 2.8 GB. It could not produce a false PASS, but a regression that wrote a protected path that way stalled its whole group instead of failing the test that did it. The tripwire now refuses at `tempfile._sanitize_params`, before the loop.

**The guarded basetemp is a compatibility exception with exact limits.** It stays under `files/dev-work/p05b-stage4c`, because six production modules pin that root and its prefixes (the entry below names them), and those six are unchanged since `0c1ef43`. It holds only each run's `verify-<stamp>` folder and `stage4d2d-m1-v<stamp>0` and `stage4d2b-v<stamp>1` basetemps. It is inside the repository, so it does not depart from §13.1. It is not a sign that every gate path was relocated to the target layout, and Phase 2 does not claim that.

**The scratch location is not decided here.** `%TEMP%\act-gate` still departs from plan §13.1 and §13.4, and nothing in this entry approves that. The evidence and a narrow proposal are in `2026-11-06_phase2_closeout_0466/scratch-location-decision.md`, for the owner.

Signed: Claude Code (Opus 5.5), under the owner's Phase 2 closeout instructions of 2026-11-06.

## 2026-11-06 - A bare gate command is invalid, 38 test identities changed with the gate, and a later read must match the environment (v0.7.2 Phase 2)

**A bare command runs nothing.** `verify.py` with no arguments now exits 64. It used to start the whole gate, which takes about 80 minutes. The plan's command list always names a mode but never says what a bare command does, so this was the implementer's choice, and it is the owner's to overrule. The cost is that any note still saying "run verify.py" fails at once instead of running, which is the better way for it to be wrong.

**Test identities.** The owner asked for existing identities to be preserved. Of the 13,366 ordinary identities in the accepted Phase 1 gate, 13,328 are kept and 38 are gone, because they drove an option (`--evidence-dir`), an exit code (2 for bad arguments) or a file (`scripts/verify.py`) that no longer exists. Keeping a name over changed behaviour would claim a continuity that is not there, so each one is mapped to its replacements instead: 18 stricter, 4 the same, 15 whose premise is gone because the caller no longer supplies a directory, and 1 the change above. The mapping is `removed-ids-map.md` in the Phase 2 audit evidence, and it fails if a replacement was not collected.

**A later read compares the environment as well as the source.** Plan §13.3 lets evidence carry forward only where the digests "and environment match". The first version compared digests only, so a PASS would have gone on reading current after FFmpeg, pytest or the interpreter was replaced. `--status --require-current` now also compares the operating system build, machine, interpreter, its prefixes, Tk, pytest and the FFmpeg hash, and a reader that brings no environment cannot read current. The error mode and the desktop are recorded but not compared, because they describe whichever session is reading, so comparing them could only raise false alarms. A documents-only difference exits 3, never 0: the evidence carries forward with the docs checks rerun and both SHAs recorded, and it is not the same source. This fix is why the full gate ran a third time, after a run that had passed.

Signed: Claude Code (Opus 5.5), under the owner's Phase 2 authorization of 2026-11-06.

## 2026-11-06 - The canonical gate moves to files/dev-work/verification-gate; a guarded basetemp stays where production pins it, and scratch stays short (v0.7.2 Phase 2)

**Decision.** `files/dev-work/verification-gate/verify.py` is the one developer gate, tracked under a narrowed ignore rule (`files/dev-work/*` with exceptions; a directory rule would make any exception dead). `scripts/verify.py` is removed with no forwarding script. Status and exit codes follow plan §6.1. Every invocation past its arguments owns one new child of `outputs/`, and a run reads PASS only through `read_run_status`.

**Guarded basetemps stay below `files/dev-work/p05b-stage4c`.** Six production modules pin that root and its prefixes (`optional_setup_planning_bridge_v3`, `optional_setup_readonly_context_v3`, `optional_setup_supervisor_v3`, `optional_setup_planning_worker_v3`, `optional_setup_readonly_worker_v3`, `spacy_consumer`), and the plan allows a runtime change in this phase only to remove a dependency on the gate. These are fixture authorities for disposable qualification, and they refuse anything else on purpose: a per-run capability would mean production code reading a caller-supplied root, which is exactly what they exist to prevent. So no production behaviour changed. What did change: the guard reports, JUnit and session records are copied into the run's evidence, a basetemp or report that already exists is refused (pytest would clear the first), and a guarded run can no longer write to an earlier run's tree, the gate or its outputs. Moving the root stays possible as its own audited change. Phase 0's inventory recommended this.

**The ordinary suite's scratch stays in the system temp folder, as one named per-run child (`%TEMP%\act-gate\<4 hex>`). This departs from plan §13.1's containment, on evidence, and is the owner's to overrule.** It is where the suite's scratch has always been: the old gate passed no basetemp, so pytest used `%TEMP%\pytest-of-<user>`. Two attempts to bring it inside the repository failed, measured on HOME-PC on 2026-11-06. Below `outputs/<run>/`, git runs out of path: it is not long-path aware by default, and `git add` exits 128 once a test's repository leaves no room for `.git/objects/xx/<38 hex>`. Below a short `files/dev-work/vg/`, something outside the process briefly holds directories just created under the repository, so renaming one fails with WinError 5: 7, 9 and 18 of 1,500 at three repository locations against 0 of 1,500 in `%TEMP%`, and `test_venv_recovery` failed 2 of 6 runs. Turning off content indexing for the folder made no difference, so it is not the Search indexer; the holder is not attributed (VS Code, OneDrive and Defender were all running). Retrying around the code under test would hide the failure those tests exist to see, and rerunning a flaky gate until it passes is not verification. Per-run isolation holds: the child is unique, `TEMP`/`TMP`/`TMPDIR` and pytest's cache point inside it, it goes on PASS and stays on failure, and `results.json` names it. The gate's own records do retry for about a second (`runstore.settled`), because a finished run must not be lost to a millisecond's hold; that never wraps code under test.

**A skip must match a named reason.** `verification.json` lists each accepted reason with a ceiling for Windows, from the 65 skips of the accepted Phase 1 gate. Anything else fails the run. A skip on another platform is recorded, not judged, until a policy exists for it.

**Later phases are visible, never silently satisfied.** `native-journeys`, `real-media-journeys` and `coverage-inventory` appear in every full result as NOT RUN and not required; `full_acceptance` and `release_ready` stay false. Making one required is one flag, and the run then stops at NOT RUN until the check exists. Each qualification scenario reports NOT RUN and names its owning phase. `coverage.json` is a seed of identities for `--feature`, explicitly not the reviewed inventory.

**Left alone on purpose.** The comment on line 106 of `scripts/requirements.txt` still names the old path: that file's bytes are hashed into the lock and the setup state, so editing a comment would make every installed environment look stale. It goes with the next dependency change. The ignored local instructions (`.claude/CLAUDE.md`, `.codex/CODEX.md`, `AI-WORKSPACE.md`) still name old commands and are the owner's to change; none is read by the gate. `test_a_missing_file_is_probe_failed` stays as the invalid-executable test it really is, documented as such, beside a new test of a real missing file.

Signed: Claude Code (Opus 5.5), under the owner's Phase 2 authorization of 2026-11-06.

## 2026-11-06 - The gate owns its Windows error mode, and why a run can lose a flag (v0.7.2 Phase 2; corrects two details of the entry below)

**Decision.** The gate raises `0x8003` on itself first thing in `main`, before it parses an argument. Preflight then proves it on a real child: the child must read the flags, and starting a 14-byte invalid executable must fail with WinError 216 inside a bounded job, or the run is BLOCKED. The ignored Phase 1 launcher is no longer needed and remains only as evidence. `gate_session_probe` re-raises the flags at every test boundary and records each drift. Losing `SEM_FAILCRITICALERRORS` fails the run; losing a lesser flag is repaired and recorded. A stall limit bounds anything that still holds a child.

**The `0x8003` to `0x8001` transition is identified.** A watcher polling `GetErrorMode` with every thread's stack saw about 10,000 changes over 14 runs of the eight-worker assembly test. Process creation itself takes the mode through `0x8001` (stacks in `subprocess._execute_child`, reproduced with one worker), and CPython's extension-module loader takes it through `0x1`. Each saves and restores a process-wide word with no atomic update, so overlapping calls can restore each other's transient value, and it then stays: 7 of the 14 runs ended their process at `0x8001`. None of the 10,000 cleared `SEM_FAILCRITICALERRORS`, so the invalid executable stays harmless. The flag lost is crash-dialog suppression: a native crash in a child then goes through Windows Error Reporting, 1.5 to 2 s against 0.03 s, without holding the run on HOME-PC. `JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION` was tried and is not used: it changed neither the mode a child reads nor the time a crash took.

**Corrections to the entry below.** `cmd.exe` does not reset the mode here: a child of `cmd /c` read the same mode as its parent at each of `0x8003`, `0x8001`, `0x1` and `0`, so the mode 0 seen earlier came from how that shell was launched. And `gate_watch` and `run_gate` are not needed for a gate any more; only the harness's own background-shell limits still apply.

Signed: Claude Code (Opus 5.5), under the owner's Phase 2 authorization of 2026-11-06.

## 2026-11-05 - The full gate runs with Windows error dialogs off; nothing tracked changed for it (v0.7.2 Phase 1, attempts on `0c1ef43`)

**Decision.** A full gate on Windows runs `scripts/verify.py` in a process whose error mode is `0x8003` (no critical-error, crash or open-file dialogs), set before its first child starts and proved to reach a child. It is never launched through `Start-Process`, which gives it mode 0. Until the canonical gate of Phase 2 takes this over, a local helper outside the tested source does it: `files/dev-work/act070-remediation/rca/ACT072-P1-launch-correction/run_gate.py`. The command it runs, the tests selected, every limit and the acceptance criteria are unchanged. This records how a gate is started; it is not an acceptance policy.

**Why.** The test fixture's `ffmpeg.exe` and `ffprobe.exe` are deliberately invalid and two tests really try to start them. In mode 0 Windows answers with a modal "Unsupported 16-Bit Application" dialog and the test waits for a person, 2,343.6 s and 441.9 s in `ACT072-P1-0c1ef43-full1`. With the mode set the start fails at once with WinError 216, the failure those tests expect. Removing the fixture or changing those tests would have hidden the launch problem and lost the negative test; the product's handling of invalid media is untouched.

**Limits.** `verify.py` inherits its mode, so a hand launch from a mode-0 parent can still block. The helper is untracked, so it is not among the inputs a tree fingerprint covers. A pytest process does not always keep the mode it was given: it can fall to `0x8001` during a test, losing crash-dialog suppression and keeping what stops the dialog above; what sets it is not established. Phase 2's gate should own the launch, and check the mode rather than assume it. Watching for a dialog stays necessary until it does.

**Evidence.** `Handoff.md`, the top block; `files/dev-work/act070-remediation/rca/ACT072-P1-launch-correction/`; `files/dev-work/act070-remediation/verify/ACT072-P1-0c1ef43-full3`.

Signed: Claude Code (Opus 5.5) under the owner's prompts of 2026-11-05, which directed the dialog-suppressed launch. Phase 1 acceptance stays with the owner.

## 2026-11-05 - A dropped request's collection is shared, runs on its own thread and never on the cancelling one (v0.7.2 Phase 1, full gate failure on `43568ac`)

**Context.** The full gate on `43568ac` failed one test of 13,351: eight workers cancelled inside refusing requests took 5.27 s against a 5.25 s limit. `_shut_down` ran one full `gc.collect()` per dropped request. A collection holds up every other thread, so they ran in a row, and the cost scales with the heap: 0.03 s on one test's 174 K objects, 0.45 s on a full run's 1.61 M (`rca/ACT072-P1-43568ac-full1`). Targeted runs cannot see this. Separately, a `gc.collect()` made during another thread's collection returns 0 at once and does nothing, so a request dropped during one was left open with nothing said. This entry refines "a collection closes sockets held in reference cycles" in the entry below.

**Decision.**
- *The collection stays.* With it a no-op, a connection held in a reference cycle stays open, which is how a real client's objects hold one; two existing tests see that from the far end of a real socket. The 5.25 s limit stays too.
- *Requests dropped together share.* Each drop takes a number under one lock. One daemon thread runs full collections until nothing is owed, then goes, and a later drop starts another, so no thread stays and no queue can grow. The decision to go and the clearing of its running flag are one step under that lock.
- *A collection covers only what was dropped before it began.* It chose its garbage when it began, so the covered number is read before it starts, and a later drop waits for the next one. Only a `gc.callbacks` "start" on that thread proves one began; `gc.collect()`'s return value cannot tell "found nothing" from "did nothing". If such a report is missed the error is one extra collection, never a number marked covered with nothing behind it.
- *It stands aside for 0.1 s after each collection.* The workers a collection held up have not yet had a turn to say they were dropped. Measured on the final logic: on a heap like a full run's, 3 collections and 3.62–3.70 s without the pause, 2 and 2.73–2.80 s with it. This buys sharing, never correctness.
- *No collection ever runs on the cancelling thread, even if the thread cannot be started.* A collection has no deadline and cannot be stopped, so one there could hold Cancel for as long as a finalizer liked. A probe showed exactly that in the first version of this correction. When memory or shutdown refuses a thread, both promises cannot be kept, and Cancel comes first: the number stays owed, the next drop that gets a thread covers it, and the log says the connection may stay open.
- *Nothing here replaces the outcome or hides a failure.* The driver's wait is bounded by its existing deadline, and one that cannot be set up is skipped. A collector failing at any step gives up its place and reaches `threading.excepthook`. Only the two refusals named above are absorbed, each with a defined result.

**Rejected.** Deleting the collection (connections stay open). Raising the limit (it would hide a real multiplication). A shared lock around one collection per request (still eight in a row, measured). Skipping when a collection is running (that one chose its garbage too early, so the connection is never released). `gc.freeze` or disabling collection (process-wide side effects on every tool). Marshalling collections to the Tk thread (`edge_requests` has no business knowing Tk, it would freeze the window for each, and no route but the GUI has that thread). A permanent collector thread with a queue (a thread and a structure to own for a rare case). Starting a process for the collection (it cannot see this heap).

**Limits.** Finalizers run on the collector thread, as they did on the worker and do under the interpreter's automatic collections on any thread. Python cannot exclude any, including a Tk variable's. Real Tk probes found no new failure and one removed: main and worker no longer wait for each other during the panel's bounded join (6 s to 0.19 s). A collection already running cannot be shortened and holds every thread for its cost. `run_request` can return before the connection has closed. A finalizer that blocks for good keeps the one collector thread and, by the interpreter's own rule, stops later collections; later drops wait only their bound and the process still exits. An automatic collection landing inside a short section holding this lock, with a finalizer that blocks, would hold other workers at that lock, as with every Python lock; not fixed. Not exercised: the real GUI on a production heap, the real Edge service, macOS.

**Evidence.** `files/tests/test_cancel_semantics.py` (87 tests). Results and controls: `Handoff.md`, the top block; `files/dev-work/act070-remediation/rca/ACT072-P1-gc-remediation/`. Targeted only: a full gate on the corrected commit is required and Phase 1 is not accepted.

Signed: Claude Code (Opus 5.5) under the owner's bounded prompts of 2026-11-05. Phase 1 acceptance stays with the owner.

## 2026-11-05 - Cancel and the commit are ordered on the latch's own lock; a cancelled request has a bounded end (v0.7.2 Phase 1, independent review P1-R01 and P1-R02)

**Context.** Independent review of the review candidate `112d8a0`, relayed by the owner, did not approve Phase 1. P1-R01: the check before the rename was not synchronized with the cancellation latch, and `test_a_cancel_that_arrives_after_the_commit_check_leaves_the_published_file_whole` accepted the wrong ordering. P1-R02: `await_unless_cancelled` awaited a cancelled task without a bound. Both were confirmed on that tree. A third defect turned up during the work: the candidate fails an existing guard (below). This entry supersedes the bullet "The commit boundary is the rename" in the entry below, and that entry's naming of `shared.cancellation.wait_unless_cancelled` and `await_unless_cancelled`. The remediation was committed after `112d8a0` under the owner's closeout instruction of the same day, with the full gate still outstanding.

**Decision.**
- *The logical commit boundary is an authorization, not the rename.* `JobController.authorize_commit` decides under the same `Condition` lock `request_cancel` latches under, and records a win in `commits_in_flight` before releasing it. Whichever takes the lock first wins, and both know. A Cancel that came first denies the commit: nothing is published, what was at the destination is untouched, the staging file goes. A commit that came first finishes whole. After the latch nothing new is authorized, so `commits_in_flight` read after `request_cancel` is the complete answer to what can still appear.
- *Why a record and not another check.* `JobController.cancel_check` already read under that lock, so the read was ordered. What was missing was the other half: it left nothing behind, so a commit about to land could not be told from none at all, and Cancel could answer and a file appear afterwards with nothing anywhere saying it could.
- *The lock is never held across anything that can block.* The fsync and the rename run with no lock held. `request_cancel` runs on the GUI thread, so holding it across the rename would freeze the window behind a slow disk.
- *Each attempt asks.* An attempt the OS refused published nothing, so its authorization is given back; the retry after a locked destination asks again, and a Cancel during the back-off stops it.
- *A cancelled run has actually stopped.* `finish_cancelled` refuses while a commit is in flight. The panel settles only after its workers have returned, so this guards the contract and does not fire in the normal path.
- *Compatibility.* The seam stays `cancel_check`. `tts.publication.authorized_commit` finds the latch through the bound method's owner, so no route's signature changed. `None` and a bare predicate keep working and get a last look, having no latch to be ordered against. Every Cancel button passes the controller's own bound check, and a guard pins that and every publication call. That guard exists because the Qwen3 route was found calling publication without the check at all.
- *A cancelled request has a bounded end.* `asyncio.run` waits with no limit for tasks left on its loop and up to 300 s for its executor's threads, so bounding the helper alone was not enough. `tts.edge_requests.run_request` owns the loop at both Edge request sites: `await_unless_cancelled` cancels and waits up to `REQUEST_STOP_SECONDS` (1 s), the shutdown cancels again and waits up to 1 s more, then anything still going is dropped and its coroutine closed. The second cancellation is what aborts aiohttp's 10 s polite close. Worst case about 2.25 s including the 0.25 s poll.
- *No detached task.* A dropped request does not go on running somewhere: a coroutine runs only when its loop runs it, and that loop is closed. Closing the coroutine releases its partial file, and a collection closes sockets held in reference cycles, which a real client's objects are. Tests see both from the far end of a real socket. `note` (the log) is told about anything dropped and about any blocking call still under way; nothing is claimed that was not seen.
- *A generator's cleanup shares that deadline (confirmed at closeout).* `loop.shutdown_asyncgens()` was waited for within the deadline, but a cleanup that outlasted it stayed pending on the closed loop, with nothing said until asyncio's own "Task was destroyed" at collection. It is now ended like anything else left on the loop: cancelled, given what is left of the deadline, then dropped, and `note` says the cleanup was cut short. The request's own result or exception is unchanged.
- *`shared/cancellation.py` is back to its `204c33b` bytes.* `112d8a0` added two functions and the imports `asyncio` and `time` to it, which fails `test_plan3_boundaries.py::test_the_existing_cancellation_api_is_unchanged_and_unwrapped`, the gate that pins what that module may define and import because every tool imports it. The full gate was interrupted at 43 % before reaching it, and the Phase 1 selection did not include it. Everything added is used only by the TTS routes, so the guard stays as it is and the code moved: requests and waits to the new `tts/edge_requests.py`, `authorized_commit` to `tts/publication.py`, its one user. `test_epub_retirement`'s list of production modules gains the new file, which extends that guard's reach.
- *Per-item status is retained.* A file stopped by Cancel stays `NOT_ATTEMPTED`. Limitation: the result object cannot tell it from a file that never started, and only the log line does ("stopped (cancelled); nothing unfinished was saved" against "skipped (cancelled)"). Neither is offered by Retry Failed. No targeted test showed a user-visible or retry-contract defect, and a new status would change the shared job model of all six tools. A file that won the commit is `SUCCEEDED` while the run is `CANCELLED`, which is what happened.

**Rejected.** Holding the latch's lock across the rename (freezes the GUI behind a disk). Cancel waiting for commits in flight (the same freeze with extra steps). Deleting a file that landed after Cancel (under Overwrite the old output is already gone, and nothing here ever removes a destination). A thread per request so it can be abandoned (a detached thread goes on running and could write or request; a closed loop cannot). A second lock for commits (two locks can disagree; the job module's whole concurrency budget is one `Condition`). Widening the `shared/cancellation.py` guard to admit the additions (it would loosen a guard to let the change through, when nothing outside the TTS routes needs them).

**Limits.** A blocking call on an executor thread, in practice a name lookup, cannot be interrupted: Cancel does not wait for it, the log says so, its answer goes nowhere and its thread ends when the OS answers, and closing the application waits for that thread. A coroutine blocking its own loop synchronously cannot be interrupted by anything cooperative; in `edge_tts` that is `audio.write` to a local temporary file, so a hung disk. A Cancel that loses to the last file's commit still ends the run `CANCELLED` with that item a success, behaviour since v0.6.5 and now pinned by a test. `commits_in_flight` is an upper bound, since the direct route's private scratch rename counts for its instant. A coroutine that swallows `GeneratorExit` as well can still produce one unraisable report when collected, and a cleanup that raises is logged by asyncio's own handler, as under `asyncio.run`; neither changes the outcome. `finish_cancelled` refuses while a commit is in flight; `succeed`, `complete_with_failures` and `fail` do not check, because the panel reaches them only after its pool has finished, which tests hold on both the normal and the fatal path. Not exercised: the real Edge service, real DNS, macOS, the native button.

**Evidence.** `files/tests/test_cancel_semantics.py` (65 tests) and three new tests in `test_tts_worker_concurrency.py`, ordered by events and barriers: both orderings under no-clobber and overwrite, seven losers and one winner, a latch held mid-way, retries, the name taken after authorization, forty unscripted races. 238 passed with `test_job_controller`; 1,647 in suite order with `test_epub_retirement` in place, the guard above unchanged among them; 18 Cancel scenarios of `test_low_memory` under real limits. Negative controls: no-change control passed, 22 of 22 caught (`…/phase1-runs/review-remediation/mutation-review-all.txt`). `publication.py` as committed in `112d8a0` fails with "a file is about to appear after Cancel returned and Cancel's answer does not name it" while the Cancel-first ordering still passes (`old-implementation-reasons.txt`). The first pass was weaker and is kept: 17 of 21 clean, two hangs and two survivors (`mutation-review-first-pass.txt`), and a real-client test whose server was not really silent passed on the old path until corrected. Real `edge_tts` + `aiohttp` on loopback (`real-client-timings.txt`): sending to a peer that never answers the close went from 10.04 s to 1.13 s with the connection seen to end. The full gate has not been run on this; the one started on `112d8a0` was interrupted and reads INCOMPLETE. Closeout (`…/phase1-runs/closeout/`): `test_cancel_semantics` now 72 tests, six more cases in `test_tts_worker_concurrency.py`; 321 passed with `test_job_controller`; 3,023 passed and 2 environmental skips across 32 suites in suite order; the same 18 under real limits; the no-change control passed and 38 of 38 mutants were caught, after a first pass with one survivor and one hang, both corrected (`mutation-review-first-pass.txt`). Signed: Claude Code, under the owner's remediation and closeout instructions of 2026-11-05.

## 2026-11-05 - Cancel stops active work promptly, finished narration included; only Pause drains active files (v0.7.2 Phase 1)

**Context.** The owner's v0.7.2 instruction (2026-11-04; plan §1.1, §3.1, §11.1) supersedes the rulings of 2026-11-03/04 below that a narration past its last synthesis checkpoint is finished work a Cancel does not discard. Those rulings gave Cancel a finishing allowance: 30 s without progress or 600 s in all for an FFmpeg of finished narration (`ffmpeg_watch`), 30 s for finished narration to find room on disk (`worker_limits.CANCEL_FINISH_WAIT_SECONDS`), a disk fallback after an allocation failure even after Cancel, two more Edge requests and up to 9 s of back-off after Cancel in the direct request loop, and no cancel check at all at publication. Phase 0 reproduced the allowance at the seam (a supervised FFmpeg still running, output growing, 3 s after Cancel under the default control) and traced every site (`files/dev-work/verification-gate/outputs/2026-11-04_233658_phase0_2b7d/cancel-pause-trace.md`).

**Decision.**
- *Cancel means stop, at once, everywhere.* `ffmpeg_watch` kills a cancelled child within one look whatever stage of the conversion it belongs to; `abort_on_cancel`, `CANCEL_STALL_SECONDS` and `CANCEL_FINISH_SECONDS` are gone. `worker_limits` has no `finishing_check` and no `CANCEL_FINISH_WAIT_SECONDS`: a cancelled waiter leaves the gate within the poll, and `assemble` reads the cancel check before the gate, before any fall back to disk and before each disk attempt. The Edge request loops read the conversion's cancel check through the `controlled` context (`ffmpeg_watch.current_cancel_check()`), so the seams the offline test doubles stand in for keep their shape; no attempt, back-off or in-flight request outlives a Cancel (`shared.cancellation.wait_unless_cancelled` and `await_unless_cancelled`, polled at 0.25 s). The chapter join checks before it starts. The local engines check before their one encode and run it under the same control, so pydub's FFmpeg is killable there too.
- *The commit boundary is the rename.* `publication.Stage.publish(cancel_check)` reads the check immediately before the one atomic operation; a Cancel seen there, or during the copy into staging, publishes nothing and removes only its own staging file; a Cancel after that last look has lost, and the whole file stays. The GUI never waits on encoding or copying to acquire this boundary, and no partial file ever carries the final name. Already-published files are never touched.
- *Waking.* The panel's Cancel wakes the FFmpeg watchdog and the memory gate (`ffmpeg_watch.wake`, `AssemblyGate.wake`) so the kill and the leave do not wait for the next poll.
- *Pause is unchanged.* `JobController.checkpoint` between source files is the one graceful boundary: active files finish, nothing new starts, Resume continues, and Cancel outranks a pause immediately. The tests that pin this (no sleep or poll in the panel, a condition wait and never a poll) are kept.
- *Reporting.* A file stopped by Cancel stays `NOT_ATTEMPTED` at the item level (neither SUCCEEDED nor FAILED; Retry Failed never offers it) and the run is `CANCELLED`; the log tells "stopped (cancelled); nothing unfinished was saved" from "skipped (cancelled)". No per-item CANCELLED status: it would change the shared job model of all six tools for a distinction the log already makes.

**Why not keep the allowance.** The person asked for the work to stop; a narration that is finished and saved anyway is work they did not ask for, and ten minutes is not "stop". Hours of synthesis lost to a Cancel is the cost the owner chose over a Cancel that is not one. Rejected: a confirmation dialog on Cancel (not asked for; a modal over a running conversion); the allowance behind a setting (two contracts to explain and test); a per-item CANCELLED status (above).

**Evidence.** `files/tests/test_cancel_semantics.py` (31 tests; barriers, never sleeps: the gate, `assemble`, publication's boundary from both sides, the request loops, eight workers parked at a barrier making no request after the latch, the local engines, the panel's wakes); twelve tests that encoded the old semantics rewritten under this ruling (`test_low_memory.py` 8, `test_assembly_on_disk.py` 1, `test_edge_publication.py` 3) and one in `test_tts_worker_concurrency.py`; the AST guard now requires `cancel_check` on every `assemble` call. Under a real Job Object limit with the real FFmpeg: Cancel-to-end 0.02–0.28 s in seven scenarios, nothing published, no survivor, no reservation left (`…/phase0_2b7d/phase1-runs/cancel-measurements.json`); mutation controls: seven mutants that reinstate a piece of the old policy (watchdog ignoring Cancel; fall back and retry after Cancel; the gate admitting a cancelled waiter; publication committing after Cancel; the request loop retrying after Cancel; the chapter join ignoring Cancel) each fail the new tests, the no-change control passes (`…/phase1-runs/mutation-control*.txt`). Signed: Claude Code (Fable 5.1), under the owner's v0.7.2 kickoff of 2026-11-04.

## 2026-11-04 - No low-memory path can hang: every FFmpeg on the Edge routes has no threads of its own and can be stopped; memory running out after admission falls back to disk; Cancel and failure have stated deadlines (v0.7.1 R2 remediation)

**Context.** The independent R2 review of `e0aab03` passed publication, sizing and the disk route's bytes, and blocked on one finding: a real allocation failure while pydub read FFmpeg's output hung the whole run for ever, with its gate reservation held and Cancel powerless. The owner ruled it in scope and blocking, not pre-existing, though plain Python and FFmpeg hang the same way. This supersedes, in the entry below: "a finished narration still ignores Cancel during this wait", and every-admission "reads what is free" as physical memory alone.

**Decision.**
- *Supervise the process, at the seam pydub already has.* `communicate` on Windows puts each pipe on a thread, and the thread that dies of `MemoryError` tells nobody. `tts/ffmpeg_watch.py` reads output on the asking thread, sends stderr to a file and has one watchdog that can kill. pydub is pointed at it by replacing the `subprocess` name in its modules, because that leaves its commands and audio unchanged and no call site to miss; `test_what_pydub_uses_is_what_was_replaced` holds the pinned version to it. Rejected: catching `MemoryError` (it is raised on another thread); a timeout on a thread (the process stays blocked); only checking memory better (it can go after the check); replacing every pydub call with our own decode and export (a bigger change for the same effect, and it would have had to rebuild the byte-identity proof at every site).
- *An answer from the gate is not a promise.* `worker_limits.assemble` takes both routes. An allocation failure in memory gives back the reservation and assembles the same parts on disk, with no new request. At most two disk attempts, the second after those holding memory have finished; then a named failure. Fixed attempts, because after that the same machine in the same state would only fail again, and the person has a better next move than a loop.
- *Read commit and limits too.* Commit is what an allocation actually needs, physical free says nothing about it, and on HOME-PC it was at times the tighter of the two. Windows can grow a page file, so commit can read low: then a narration goes to disk, which is the same bytes, so erring that way costs nothing that matters.
- *Do not count allocated memory twice.* What counts against a reading is what is reserved less what this process has allocated since. Its known errors are small and either way below the margins; if it is ever wrong, allocation failure is handled now.
- *One starvation deadline for a queue.* Per file it reached 40 minutes on 8 workers and hours on 32, with Cancel ignored throughout.
- *Cancel keeps finished narration if it can, and says so if it cannot.* Speech still to come stops at once. Finished narration stops waiting for its turn or anybody's memory and goes to disk at once, with limits: 30 s to find the memory, 30 s without progress, 600 s in all. Past those it is reported as not saved. Rejected: no limit (Cancel might never end) and stopping at once (hours of synthesis lost for no reason).
- *Clean what is provably ours, and only that.* A run removes an interrupted run's stale `.tmp_chunks/<ours>`. `%TEMP%` after a kill is left for the planned hardening: it needs its own ownership design.

**Why:** a person with a low-memory computer must get an output or a reason, and Cancel must work, whatever the memory is doing. No reading of memory can promise that: only being able to stop every process, and having somewhere to go when an allocation fails, can.

— Directed by the owner on 2026-11-04; implemented by Claude Code. Awaiting a fresh independent Codex review, then owner acceptance.

---

## 2026-11-04 - A narration that does not fit in memory is assembled on disk, to the same bytes; no assembly enters memory for being first; what a file holds while it is synthesised has a limit (v0.7.1 second review remediation)

**Context.** The fresh independent review of `e19527e` passed publication and blocked memory. A fully read PDF was sized by its pages while a
conversion joins prose across them (HIGH-002A), audio built up before any gate was asked, and `AssemblyGate` let the first assembly in with zero bytes free,
with a warning (HIGH-002B). This supersedes two choices in the entry below: "a lone assembly always runs" and "Rejected: flushing long paragraphs to disk,
because it changes the assembly". The reason for the second no longer holds: it is proved not to.

**Decision.**
- *Sizing reads pages through one function with conversion (`pdf_extractor._join_pages`).* A second copy of the rule is how they came to disagree.
  The join was quadratic in a block's length, which is a whole book of continuous prose, so it was made linear; a differential test holds it to the old rule's output.
- *The plan stays conservative and is not what keeps memory safe.* The admission formula is unchanged, so that PDF gets 1 worker though synthesis would now fit more.
  Rejected: raising a duration constant (the review had already refused that), and crediting the new limits to the plan (a change of worker counts with no owner request behind it).
- *Synthesis holds at most `SYNTHESIS_HELD_PCM_BYTES` (16 MiB).* A paragraph writes lossless FLAC as it grows and a clip that long never comes into memory. This removes hold-and-wait:
  nothing waits at the gate while holding audio, so there is no deadlock to reason about. Rejected: growing reservations during synthesis, which is exactly that deadlock.
- *Every admission reads what is free, and the answer has three outcomes:* in memory; wait for what is assembling in memory, whose memory comes back; or on disk. A caller must honour it, and an
  AST test checks each one reads it. Below 64 MiB free, with nothing to wait for, a file waits up to 300 s and then fails: `AssemblyMemoryError`, classified local, so it is not
  re-synthesised by itself, and Retry Failed runs it again. A finished narration still ignores Cancel during this wait (bounded), per the entry below.
- *The disk route, not refusal.* Rejected: refusing what does not fit, which fails a book that v0.7.0 finished, after hours of synthesis, on a machine where closing programs may never be enough.
  Rejected: admitting it when commit charge allows, which is safe from `MemoryError` but not from paging the machine to a standstill, and is the warning again in other words. Rejected: the disk route always,
  which would change a correct route with no need; it remains the rule for what does not fit.
- *The same bytes, by construction, then by test.* Parts decode by pydub's command; the WAV file is the one pydub writes; the final tail is `audio_tail` over a mapping of it; trimming is the engine's own
  function over a small stand-in; FFmpeg gets pydub's arguments. Nothing is re-implemented that could drift. A part in another format is refused, not converted.

**Why:** a memory limit is true only if it holds when the plan is wrong and when something else has the memory, and the only way to keep a promise to finish a long book on a small machine is not to need the memory.

— Directed by the owner on 2026-11-04; implemented by Claude Code. Awaiting independent review.

---

## 2026-11-03 - TTS output is published atomically through one contract; Overwrite is off unless ticked for a run; workers are admitted by a text-based model and each assembly by its real size; a finished narration survives Cancel; the last heading stays as it is (v0.7.1 review remediation)

**Context.** The independent review of `3efbb77` was BLOCKED: partial MP3s under final names, `overwrite=False` not enforced,
`discard_partial` deleting by path, and a memory estimate that ignored inserted pauses and PDF density. A second, fresh
internal review of the fix then found planning that could hang, finished work lost to a Cancel, and two CLI runs able to
publish each other's audio.

**Decision.**
- *Overwrite is off unless the person ticks it for that run (owner ruling, 2026-11-03).* The box used to start ticked and did
  nothing; once publication obeyed it, a default run could have replaced a file. So: unticked by default; existing outputs are
  never replaced, Retry Failed included; the choice is frozen in the run's snapshot. Numbering stays where it is, at planning.
  A name taken after planning fails that item with a reason rather than taking a new number, because planned destinations
  are frozen and a retry must land where it was planned.
- *One publication contract (`tts/publication.py`), for every route and engine.* The local engines encoded straight onto their
  destination, so the ruling could not hold for them; they now get private scratch from the panel and publish the same way,
  with their engine modules unchanged. Staging is a private file beside the destination,
  created with `O_EXCL`. It is not in a subfolder, and has a 27-character stem-free name, so it fits wherever a planned
  name fits. No-clobber is the operation, never a look first: on Windows `os.rename` (`MoveFileExW` without replace or
  copy), elsewhere `os.link` then unlink, because a POSIX rename replaces silently. Rejected as primary on Windows: a hard
  link, which fails on exFAT and leaves two names for a moment. A drive that cannot do this fails with a message: there is
  no fallback. Always a copy into staging, so the output takes the destination folder's permissions, at the cost of a
  second copy of the finished file on the direct route (seconds, next to hours of synthesis).
- *Cancel does not discard a finished narration.* `test_a_success_finishing_during_cancellation_is_recorded_not_orphaned`
  was already the contract. Cancel stops synthesis at its checkpoints and stops a file waiting for memory only while it
  has more synthesis to come; past the last checkpoint the file is assembled in its turn, published and counted. A person
  who wanted it gone can delete one file; hours of synthesis cannot be got back. Qwen3's rule differs and is unchanged.
- *Attempt ownership.* `discard_partial` is gone: nothing of an attempt is ever at a destination, so there is nothing there for
  an attempt to remove. A path matching a plan proves nothing about who wrote the file.
- *Two memory layers.* The plan is a model (`estimate_text_seconds`: real text, frozen pauses, rate, the run's speech
  preparation, a PDF's extracted text; bounded at 400 pages and 5 s, checked between pages). The gate is a measurement
  (the real decoded size, from headers, before each join), and a lone assembly always runs. Rejected: modelling alone,
  because a PDF cannot be sized without reading it; flushing long paragraphs to disk, because it changes the assembly.
- *Admission = each file's synthesis memory + the largest single assembly.* Counting all files' assemblies as if they peaked
  together held eight whole novels to one worker, the very symptom v0.7.1 exists to end, although the gate keeps those
  assemblies apart and they need little until then. A source with no paragraph breaks counts whole as synthesis memory.
- *Unknown memory is an assumption, stated as one:* 4 GiB for the plan, 2 GiB for the gate. This supersedes "where free
  memory cannot be read it is not used" in the entry below: on such a machine any queue was admitted, however large.
- *The last heading stays unspoken.* A chapter exists only once text follows its heading, so `# First / Body. / # Last` does
  not speak "Last". Inherited, informational, and what a heading narrates is the owner's to change. Pinned by a test.

**Why:** a file under its final name must be the whole file, and a file nobody asked us to touch must stay; and a memory limit
is worth having only if it is true, which a model alone cannot promise and which must not cost the concurrency this
release is for.

— Directed by the owner on 2026-11-03; implemented by Claude Code.

---

## 2026-11-03 - Directly added Edge files convert side by side in private work folders; the worker count that runs is the smallest of request, queue, engine, Edge service, processors and measured memory; headings are spoken by identity (v0.7.1)

**Context.** v0.7.0 converted a queue of directly added Edge files one at a time whatever File workers said: the
vendored engine wrote bare relative scratch names, so `runner.run_conversion_job` `os.chdir`'d into a private folder
and `_CWD_ISOLATION_LOCK` serialized every direct conversion, and `resolve_effective_workers` capped an all-direct
queue at 1 (live on HOME-PC: `Requested workers: 8 | Effective workers: 1`). Owner prompt 2026-11-02: real
concurrency on every import path for every Edge voice; a hardware-aware limit (1–100 requestable, never blindly 100,
not hardcoded to 4); an audit of the word "blank" with no global word suppression. Local engines stay at 1.

**Decision.**
- *Explicit work folders, no `chdir`.* `read_book`, `generate_metadata` and `make_m4b` take `workdir=`; the runner
  passes its own `mkdtemp`, never changes the process's folder, and the lock is removed. Rejected: one subprocess per
  conversion (re-plumbs cancellation, logging and typed errors across a process boundary for a problem that is only
  the working directory); keeping the lock (it is the defect).
- *Make shared state safe instead of assuming it is.* PyMuPDF (documented as not thread-safe) behind one module lock
  for every extraction; the NLTK sentence splitter built once under a lock; per-thread whole-line logging tagged
  `[<file>]`; tqdm bars fixed at `position=0`; the ETA divided by the files in flight; direct retries jittered and
  exponential (still 3 attempts).
- *Worker policy (`tts/worker_limits.py`).* effective = max(1, min(requested, queued files, engine ceiling — local
  engines 1, Edge service ceiling 32, logical processors, memory ceiling)). Memory: available − max(1 GiB, 25 % of
  RAM) must hold the largest queued files' estimated peaks (64 MiB + narration seconds × 150 kB; seconds =
  characters ÷ 12; a PDF's characters = pages × 3,000), each figure measured on HOME-PC and rounded up; where free
  memory cannot be read it is not used, and the log says so. The log names the limit that applied. Hardware capacity
  is not service capacity: 32 is kept because 32 simultaneous real conversions succeeded without one retry; it is an
  observation, not a documented Microsoft limit (there is none for this endpoint).
- *Headings by identity.* `get_book` marks `narrate_title`; `read_book` speaks every author-written heading whatever
  its text; consecutive headings are joined into one title; the `"blank"` placeholder is only a name. No word is ever
  filtered.

**Why:** the serialization came from one process-wide side effect, so removing the side effect — not raising a
constant — is what lets every Edge path overlap safely; a limit that names its reason tells someone who asked for 100
why 16 run; and a heading is the author's text, so whether it is spoken cannot depend on what it says.

— Directed by the owner on 2026-11-02; implemented by Claude Code.

---

## 2026-11-01 - Copies own their Python and FFmpeg; the store holds only verified locked files; damage pip cannot see rebuilds the environment; M4B chapter marks are exact (v0.7.0 acceptance D1–D4)

**Context.** The real-GUI acceptance of RC `c6264fc3` (ignored `files/dev-work/act070-acceptance/`) found four Major
defects; owner directive 2026-11-01: fix them for v0.7.0 without weakening hashes, provenance, leases or the nested
Qwen3 engine.

**Decision.**
- *D1.* A venv whose `pyvenv.cfg` `home` is another installation's own Python (`<root>/files/runtime-data/python`, a
  different root) is `repairable` (`foreign-python`), so a copy is rebuilt on its own Python from its own store while
  the original still exists. A system Python is never foreign. An FFmpeg pair under another installation's `files/bin`
  is never pinned or a candidate (`ffmpeg_health.belongs_to_another_installation`). A copied Qwen3 engine stays refused
  by its static identity check (it is never executed); making it portable is not attempted.
- *D2.* Before every install from the store, `base_packages.sweep_store` keeps only the lock's exact artifact names with
  their exact SHA-256; older releases are deleted (as before), everything else is moved to
  `files/runtime-data/python-packages-quarantine` (outside the store, never installed). pip still runs
  `--require-hashes --no-index --find-links <store>`.
- *D3.* Files gone below intact metadata (what pip calls "already satisfied") are checked at launch against each
  installed distribution's own `RECORD` (package `__init__.py`, top-level modules, native libraries; cached list,
  ~10–15 ms) and make the environment `repairable` (`damaged-packages`): rebuilt transactionally from the store under the
  engine lease, carrying the engine. This narrows, and does not replace, the rule that a *missing module* is repaired
  in place: in-place reinstall cannot see this damage and is not transactional. A user's repair request
  (`.venv/.repair-requested`, Preferences & Data > Repair App Environment) takes the same route. A failed repair of an
  environment that still runs opens the app with a notice rather than not at all.
- *D4.* Chapter marks are the exact sample positions of each chapter: no `LEADIN_MS`; both concat commands rebuild
  timestamps from the sample count and keep the AAC encoder's edit list (no `-avoid_negative_ts make_zero`); FAST
  starts come from decoded lengths. Seek slack belongs to players, not to the book's timeline.

**Why:** each defect broke a promise the product already makes (copies are independent; the store makes repair
offline-capable; the launcher is the repair path; a chapter split returns the chapter), and each fix removes the cause
rather than adding a compensating offset or a manual step.

— Directed by the owner on 2026-11-01; implemented by Claude Code.

---

## 2026-10-31 - The app environment installs only from a complete hash lock through a verified local store; pip and NLTK stay inside the app folder; an ending that stops mid-sound is flagged (v0.7.0 portability remediation)

**Context.** The independent review of `9b1349e` (ignored `files/dev-work/act070-rc/evidence/VERIFICATION-REVIEW-9b1349e.md`)
found three release-readiness MAJORs and one diagnostic gap: the base `pip install` left its cache in
`%LOCALAPPDATA%\pip\cache` (pip finds that folder through the Windows known-folder API, so redirecting `LOCALAPPDATA`
does not move it); `ensure_punkt` called `nltk.download` at the start of every narration (unhashed, unconsented, into
`%APPDATA%\nltk_data`); 112 of the 170 base packages and `pip install --upgrade pip` were unpinned and unhashed; and the
final-tail policy reported an ending cut mid-sound (Qwen3 Aiden) as "0.00 s; nothing removed". Owner directive
2026-10-31: resolve them without disturbing the engines, installer, recovery, 28 voices or non-TTS tools. This
supersedes the AUD-010 deferral of main-stack transitive pinning (P04C closing state).

**Decision.**
- *One lock.* `scripts/requirements-lock-windows-py312.txt` names every package of the app environment for Windows
  x86-64 CPython 3.12 at one version, with the SHA-256 of the one artifact pip installs there (170 packages; two have
  no wheel: `docopt`, `antlr4-python3-runtime`). It freezes the versions the qualified portable install p1 proved (28/28
  voices; the only difference from HOME-PC's gate environment was `filelock` 4.2.5 vs 4.2.4) and is generated, never
  hand-edited, by `files/dev-tools/lock_base_requirements.py` with pip's own resolver (`--dry-run --report` under those
  versions as constraints; refused unless the resolution is exactly the proven set). It records the SHA-256 of
  `requirements.txt`, which stays the human-maintained list; `verify.py`'s deps gate fails on a stale, incomplete or
  loosened lock, and a test proves the lock closed and minimal under the packages' own dependency metadata and the gate
  environment identical to it.
- *One installer.* `bootstrap.install_base_packages` serves setup, repair, the drift reconcile and the Kokoro/Chatterbox
  self-heals: the locked setuptools first, then every artifact fetched with `pip download --require-hashes --no-deps
  --no-build-isolation` into `files/runtime-data/python-packages` (kept; pruned to the lock), then `pip install
  --no-index --find-links <store> --require-hashes --no-build-isolation` with dependencies checked, so a package the
  lock does not name cannot be installed. A complete store repairs without the network; a kept file that fails its hash
  is fetched once more. pip is never upgraded: the environment keeps its base Python's `ensurepip` pip (25.0.1 for the
  pinned 3.12.15). Another interpreter installs `requirements.txt` under the same policy.
- *One pip policy* (`shared/base_packages.pip_environment`): no inherited `PIP_*`/`PYTHON*`/activation variables,
  `PIP_CONFIG_FILE` = the null device, `PIP_CACHE_DIR` = `files/runtime-data/pip-cache`, no version check, no prompts;
  the locked commands also pass `--no-cache-dir` (the store is the cache). The Qwen3 engine (`--isolated
  --no-cache-dir`, offline, hash-locked) and the spaCy restore (`--isolated --no-cache-dir --no-index`) keep their own.
- *Sentence data* (`shared/nltk_store`). nltk 3.9.4 needs only `tokenizers/punkt_tab/english/` (four files). The archive
  is pinned at nltk_data commit `4f15a3d` (4,319,076 bytes, SHA-256 `e57f6418…0106`, the SHA-256 NLTK's own index
  publishes) and the four files are pinned and re-checked before use. NLTK searches only `files/runtime-data/nltk_data`.
  It is fetched by first-run setup (named in the wizard text the person accepts with Begin Setup; a failure is not
  fatal), otherwise only after a Yes at Create for an Edge run of a directly added file; `ensure_punkt` never downloads,
  and the Edge folder route, Kokoro, Chatterbox and Qwen3 never depend on it.
- *Endings.* `FinalTail.abrupt` (sound at -60 dBFS within the last 10 ms window) makes the ending `uncertain`, so every
  route's run log says "please listen". Nothing is added or removed, and Qwen3 sampling is unchanged: Aiden stays an
  owner-listening case.
- *Stage 0.* Hashes with .NET instead of `Get-FileHash`, and the launcher clears `PSModulePath` for its stage-0 call:
  started from a PowerShell 7 window, Windows PowerShell 5.1 inherited PowerShell 7's module path, could not load
  `Get-FileHash`, and stopped after downloading Python (found by the isolated qualification).
- *Cleanup.* The post-exit Clear Downloaded Data coordinator may run on the app's own base Python
  (`files/runtime-data/python/python.exe`, outside `.venv` and every cleanup target); every other interpreter inside
  the folder stays refused. Without it, a computer whose only Python is the app's could not clear `.venv` (found by
  the 3.12.15 qualification). A required import that fails after install reinstalls the whole lock from the store
  (a dependency whose files are gone but whose metadata remains is "already satisfied" to pip).

**Not chosen.** `--no-cache-dir` alone (no reuse, no offline repair); pip's HTTP cache moved into the folder as the only
store (index pages expire, so it cannot repair offline); pip-tools or uv for the lock (a new dependency for what pip's
own resolver report already gives); hashes of every file of each release (one artifact is stricter, and pip filters
candidates to the allowed hashes); bundling `punkt_tab` in the release ZIP (redistribution not reviewed; the owner asked
for a consented, verified acquisition); padding or fading an abrupt ending (the policy never adds audio, Q1).

**Consequences.** Every existing installation reconciles once at its next launch (the requirements fingerprint now
covers the lock): about 505 MB is fetched into its store and only differing packages change (HOME-PC 2026-10-31:
`filelock` only). Editing `requirements.txt` requires regenerating the lock. A new package without a wheel must be
reviewed (a test lists the two). The store uses about 505 MB of disk inside the folder.

Signed: Claude Code (Opus 5.5), under the owner directive of 2026-10-31.

---

## 2026-10-25 - Optional voices are acquired only from pinned identities, under a spent consent, and inference loads only verified local copies; Chatterbox's unused s3gen file is dropped (v0.7.0 P05B Stage 2)

Plan Revision 2 §5.4 and §6 / P05B; owner spaCy ruling 2026-10-25; recorded by Claude Code.

**Identity, not location.** Kokoro and Chatterbox Turbo files are pinned by repository, commit, size and SHA-256 in one table
(`tts/model_assets.py`) that the planner, the acquirer and inference all read. URLs name the commit; `refs/main` is never consulted, so a
moved upstream cannot change what is reported, fetched or loaded. Because the identity is pinned, a file of another size or content is
`damaged` (repairable under repair consent), replacing the P05A "unverified, maybe newer". The spaCy model is the owner-approved wheel:
verified before pip, installed with `--no-index --no-deps --require-hashes` into a compatible spaCy that is never changed; not added to
`requirements.txt`.

**One acquirer, existing machinery.** Qwen3 goes through `qwen3_setup.install`/`repair` (one call for both models) rather than a second
installer; Kokoro/Chatterbox files through the same resumable, hash-verified `download_file`, behind an opener that refuses any URL outside
the confirmed files; local work under the existing Qwen3 `InstallLock`, so it is serialized with Qwen3 installs, Qwen3 conversions and
repairs of the app's own environment in the order they already use. Each destination is checked at the write. A proved-broken local engine
gets no download: model files cannot repair packages, which is the launcher's job.

**Inference refuses instead of fetching.** Kokoro is built from the verified local files (`KModel(config=, model=)`, voices from their
`.pt` through the pipeline instance), a missing spaCy model is refused before misaki's `spacy.cli.download`, Chatterbox uses `from_local`.
The refusal is its own exception type so it is never retried as an Application Control block nor taken as proof the packages broke.

**Health is a bounded fact.** The launcher's own proofs run contained, offline and time-limited; an inconclusive probe is unverified,
never healthy and never broken, and is not recorded.

**Chatterbox `s3gen.safetensors` dropped** (Stage 1 open item 7): `from_local` never reads it; acquiring 1.06 GB nobody loads would be an
unexpected file outside the required set.

**Tests refuse production writes at the write.** An audit-hook tripwire (tests only) turns any write-capable operation under the real
installation into `PermissionError` before it happens, for the optional-setup modules; after-the-fact fingerprints remain the suite-wide
guard.

**Not chosen.** `HF_HUB_OFFLINE` alone (offline mode resolves whatever `refs/main` names and verifies nothing); hashing on every load
without a record (gigabytes per Chatterbox load); repairing Kokoro/Chatterbox packages from optional setup (that is the base stack, Q32);
wiring bootstrap's first-run pre-downloads or any UI (P06).

## 2026-10-25 - A consent is bound to the acquisition terms of the plan that was shown; the setup worker's process tree is contained; results are atomic or absent (v0.7.0 P05B Stage 1)

Plan Revision 2 §5.4 and §6 / P05B; owner rulings Q14–Q20; recorded by Claude Code.

**Consent.** The P05A consent named a plan fingerprint that nothing checked. Protocol v2 binds a consent to the SHA-256 of the plan's
acquisition terms (selection; each chosen component's readiness and scope; every acquired unit's components, state, source and download
figure) and carries those terms; the worker recomputes the plan and compares both. Unconditional fingerprint equality was not chosen:
the approved first run confirms a pre-venv estimate and only later sees the exact plan. A pre-venv consent must name the estimate the
worker reproduces (it is deterministic) and covers the main plan only as a per-unit bounded refinement; anything else, and any repair,
needs a renewed confirmation. Scopes are per component, so a mixed install/repair plan is agreed explicitly, never under one scope.
Unknown sizes are listed and agreed as unknown, never counted as zero. Version 1 is refused rather than upgraded. A consent is spent once
just before acquiring; a request has one worker.

**Provenance.** A unit is acquirable only from an exact source: a Hugging Face commit, the Qwen3 manifest, or the hash-locked Qwen3
requirements. The spaCy English model has none until the owner rules, so it cannot be acquired through the plan.

**Process and results.** The worker is started through the existing `qwen3_process.spawn(require_job=True)` (suspended, Job Object,
resumed) rather than a second containment implementation; cancel, timeout and the end of every run end the whole tree and confirm the
job empty. Results are published only by hard link; where that is impossible nothing is published (the P05A exclusive-create fallback
could expose a partial file). An install success must name every component proved working afterwards.

**Not chosen.** An HMAC over the consent (the session token is already on the command line, and any process that can write the exchange
folder runs as the same user; the binding to a recomputed plan is the protection that matters); killing by PID or `taskkill /T` for the
worker; enabling any acquirer in this stage; adopting the spaCy wheel before the owner's ruling.

## 2026-10-25 - Optional voice setup is planned by one acquisition-free planner and answered by a worker that runs only in the app's own CPython 3.12 environment; what is not proved stays unverified (v0.7.0 P05A)

Plan Revision 2 §5.4 and §6 / P05A exit row; owner rulings Q14–Q20, Q32; recorded by Claude Code.

**Contract.** Four components in a fixed order (Kokoro, Chatterbox Turbo, Qwen3 CustomVoice, Qwen3 Cloned Voices / Base), with Kokoro
checked and the other three unchecked as the approved first-run defaults; the wizard itself changes in P06. Seven readiness states with a
fixed precedence: unsupported, bad-bundle, busy, damaged, unverified, missing, ready. Only *missing* can lead to an install and only
*damaged* to a repair, each under its own consent. A component with any unproved part is unverified: never installable, never healthy.
Engine health that needs a probe is a fact the caller supplies; files being present do not prove it.

**Sizes.** Every acquisition is a unit counted once (the shared Qwen3 engine; the Qwen3 files both models share, which are copied or
linked locally). Every figure states its basis: exact, manifest, approximate, at-least or unknown. Kokoro and Chatterbox sizes are
measured from HOME-PC's cache at recorded revisions and stay approximate because upstream is unpinned; what cannot be known without the
network (the spaCy package, the base-package download) is reported as unknown. Base application packages are always disclosed
separately and include the Kokoro and Chatterbox packages (Q32).

**Execution home.** Before the app environment exists only a manifest-derived upper-bound estimate runs (standard library, imports proved
in a bare interpreter). The worker runs as `.venv/Scripts/python.exe -E -s -m tts.optional_setup_worker` from `scripts/`, refuses any
other interpreter itself, accepts one contained request bound to its launcher's session token and at most 10 minutes old, and publishes
exactly one terminal result, which nothing replaces. A consent lists its units and known download; a plan that grows beyond it is stale.

**Not chosen.** Importing `qwen3_setup` into the pre-venv path (the exact Qwen3 plan runs in the worker, reusing `plan_install`); a
second Qwen3 planner; inferring Kokoro/Chatterbox health from file presence; reusing the old ~300 MB / ~3.9 GB strings as totals;
probing locks for `busy` in P05A (it would create lock files; P05B wires real locks).

## 2026-10-25 - P04C closes on the nested Qwen3 layout: .venv/engines/qwen3 is canonical, HOME-PC runs on it, the legacy .venv-qwen3 is kept unused for rollback; MachineGuard stays out of repair and cleanup; residual debt is assigned, not closed (v0.7.0 P04C Stage 5C)

Plan Revision 2 §5.5 and §6 / P04C exit row; owner rulings on P04C Stage 4 (Option B, MachineGuard, pinning, classifications); recorded
by Claude Code. Closure is conditional on the P04C full gate recorded in `checkpoints/P04C.md`.

**Topology.** The nested layout is adopted: a Qwen3 engine is an independent venv at `.venv/engines/qwen3`, created at that final path by
the verified base CPython 3.12, its identity kept outside `.venv`. Legacy `.venv-qwen3` copies keep working while they are the only engine;
when both exist the canonical one is used and judged, and the legacy one is never installed into, rebuilt or deleted. No automatic
migration, and no relocation of an existing environment.

**HOME-PC.** Stage 5B satisfied the exit's "create/verify canonical environment at final destination; retain legacy environment": the
production installer built the canonical engine (89/89 locked, 0 package bodies downloaded, GPU probe PASS), and the preset and clone
narrations matched the Stage 2 goldens byte for byte. `.venv-qwen3` is retained untouched as the rollback target (lease, rename the
canonical folder to an ignored quarantine, remove only `nested_environment`). Its retirement, and deletion of the Q/Q2 qualification copies
and the O3 cache, are separate owner approvals.

**MachineGuard: retained outside repair and cleanup.** Every holder of the guard in a copy already holds that copy's `inference.lock`
(conversion, clone transcription) or `InstallLock` (probe), both inside the engine lease, and an orphan worker holds `engine.lock`. Adding
the guard would add no file safety and would let another copy or another Windows user's conversion (or a `denied` guard) block repair of
a broken app.

**Assigned, not closed.** Main-stack transitive pinning stays deferred (AUD-010; P07/P10 fresh-ZIP qualification covers the drift
risk). Pip-less parent repair (Minor) and Kokoro/Chatterbox model removal under a second window of the same copy (Minor) → P07. The P04B
L cases (true standard user, restricted ACL, long paths disabled, clean-machine SAC, other GPUs/CPU-only, cross-user MachineGuard `denied`)
are UNPROVED → P10 / AUD-004.

**Not chosen.** Option A (closing on the Q2 qualification copy with an exit amendment); migrating `.venv-qwen3` by rename or copy;
deleting the legacy engine at adoption; taking MachineGuard in the repair/cleanup lease.

## 2026-10-25 - The Qwen3 dialog states the engine in use and the destination of a new one from the path authority; a real canonical engine is guarded per test by its identity and top level, and walked whole once per session (v0.7.0 P04C Stage 5A)

Plan Revision 2 §5.5 and §6 / P04C; recorded by Claude Code. Source + tests only; no environment created or changed.

**Dialog.** The install dialog no longer names a fixed engine folder. `qwen3_install_ui.location_text()` asks the runtime
(`venv_dir`, `is_nested`, `environment_status`) and keeps two facts apart: the engine in use (an earlier version's `.venv-qwen3`,
never said to have moved, or `.venv/engines/qwen3`, healthy or needing repair) and where a new or rebuilt engine goes (always
`.venv/engines/qwen3`). It no longer invites deleting folders, and says the engine is not part of the app's own dependencies.

**Test guard.** Walking `.venv/engines` around every test is free while it is absent and about an hour per gate once a real engine is
installed. Per test it is now fingerprinted by what identifies and lays out an engine (one-level listings of `engines`, the engine and
`site-packages`; `pyvenv.cfg` by hash; `Scripts` in full); the whole tree is walked once at the session boundary without following
links. Listings record names, kinds and the folder's own `stat` mtime, never the entries' listing timestamps, which NTFS lets lag.
Accepted limits: no package content is hashed, and a deep edit is reported for the run rather than the test. Nothing in the engine is
exempted; lock files live outside it and keep their own guard.

**Not chosen.** Hashing the engine (5.5 GB); a per-test recursive walk of `site-packages`; exempting `__pycache__`.

## 2026-10-25 - Clear Downloaded Data removes the app environment and the models only under the Qwen3 engine lease; nested engines and repair asides can never be packaged or staged (v0.7.0 P04C Stage 3)

Plan Revision 2 §5.5 and §6 / P04C; recorded by Claude Code. Source + tests only; no live environment changed.

**Lease.** The post-exit coordinator only looked for `.venv/engines/`; with no child yet, a first Qwen3 install holding `setup.lock` (folder
not yet created) passed the look, and an install starting mid-deletion could build inside a half-deleted parent. Models had the same gap
against a conversion, model check, model install or orphan worker. Catalog items now carry `requires_engine_lease` (True for
`virtual_environment` and `downloaded_models`); the coordinator takes `shared.engine_lease` (setup → inference → engine, all or none,
never waiting) before re-authorizing such an item and holds it through removal. Busy, denied, linked or unmakeable locks refuse that item
(`refused`, nothing removed, lock-specific sentence or "could not check"); every other selected item is handled as before. Taken per item,
so a refusal never blocks binaries or logs. MachineGuard is not taken (it protects no file; Stage 1 ADR stands).

**Not chosen.** Detaching, recreating or migrating a held engine so `.venv` can be cleared; offering the engine as a fifth item; waiting
for a busy lock; refusing the whole request when one leased item is busy.

**Wording.** The `.venv` item says it rebuilds "the app's own dependencies" and that "the Qwen3 voice engine is not part of this item"; the
held-engine refusal is unchanged.

**Packaging/ignore.** The packager already walked only `scripts/`; it now also excludes directory components starting `.venv.` or `.venv-`
(set-aside and preserved copies) besides `.venv`/`.venv-qwen3`. `.gitignore` gains `/.venv.replaced*/` and `/.venv.discarded*/`, which were
not ignored. Regression tests force-commit nested engines, asides, preserved copies, models and private records into a fixture repo.

## 2026-10-25 - The Qwen3 engine is installed at .venv/engines/qwen3, built from the verified base Python; a repair always takes the engine lease first (v0.7.0 P04C Stage 2)

Plan Revision 2 §5.5 and §6 / P04C; recorded by Claude Code. Source integration only: no live HOME-PC environment was migrated, rebuilt or
removed. Extends the Stage 1 entry below (its "taken only when something is held" rule is superseded by the unconditional lease here).

**Path authority.** `qwen3_runtime.venv_dir()` is `.venv/engines/qwen3` unless only the legacy `.venv-qwen3` is present. Anything at the
canonical path (a link, an empty or half-made folder included) makes it the one judged, so a damaged new engine is reported, never hidden
behind an older one; when both exist and the canonical one is unusable, the status sentence says the older one is not used. Nothing else
is searched for.

**Creation.** The installer always targets the canonical path, never the legacy one. It creates the engine there directly with
`<base> -I -m venv <final absolute path>`, where `<base>` is `sys._base_executable` (as `python.exe`) proved first on disk (a file, not a
link, outside the app folder, no `pyvenv.cfg` beside or above it) and then by running it isolated (CPython 3.12, `prefix == base_prefix`,
itself as executable). The new `pyvenv.cfg` must name that base. Identity lives outside the replaceable parent, in `state.json` under
`nested_environment`: path, stage (`creating` before `-m venv`, `created` with `venv_layout.base_identity` after it, `installed` after the
probe, `removing` before a rebuild deletes it). `environment_status` trusts the canonical engine only when `venv_layout.assess_child`
proves identity against that recorded base and the record is complete. The legacy record keeps its old key and shape.

**Legacy.** Never installed into, rebuilt or deleted by the app (`safe_to_remove_environment` accepts only the canonical folder). A
healthy legacy-only engine keeps working; adding a model does not reinstall the engine. If it needs rebuilding, the repair builds the
canonical one instead and the plan says so ("installed in its new place … the older .venv-qwen3 … is not changed or deleted"). Removing
`.venv-qwen3` stays the owner's decision. Flagged for review: on such a copy the old folder's disk space (about 5 GB) is not reclaimed.

**First-install race.** `bootstrap._take_engine_lease` (renamed from `_take_held_engines_lease`) takes `setup` → `inference` → `engine`
before any parent mutation even when nothing is under `engines/`. `install_environment` holds `InstallLock` (setup → inference) from its
first check to its last record, taking it itself when the caller does not and reusing one this thread already holds (never two handles on
one lock, which would refuse itself). So whichever starts first wins and the other refuses with nothing changed. `InstallLock` also
checks `engine.lock` is free and gives it back at once: every worker this copy starts is started under `inference.lock`, which the
installer holds, so only an orphan worker can hold it, and the installer's own probe must be able to take it. Order and non-blocking
refusal are unchanged; MachineGuard stays out of the repair lease (Stage 1 ADR). Consequence: a conversion on a legacy engine now also
refuses a main repair, because its `inference.lock` cannot be told apart from an install's.

**Refusals added.** The engine is never created in a parent without `pyvenv.cfg`, reached through a link, or with a `.venv.replaced*`
pending (only setup/repair resolves that); pip is never run into a canonical engine that cannot be verified (it is left alone until a
repair rebuilds it); an interrupted creation or removal is cleared and redone by the next install.

**Subprocess environment.** `worker_environment` (and so `installer_environment`) drops every inherited `PYTHON*` and `PIP_*` variable and
the venv/conda activation variables, and removes from `PATH` the folders of any other Python environment (a folder whose own or parent
folder holds `pyvenv.cfg`, or with `conda-meta` up to two levels up), the app's `.venv\Scripts` included. Everything else on `PATH`
(Windows, GPU driver, CUDA, a base Python) is kept in order.

**Not decided here.** Migration or removal of `.venv-qwen3` on HOME-PC; maintenance/cleanup wording and the packaging check for the nested
layout; main-stack pinning. Each is a later P04C stage behind owner review.

---

## 2026-10-24 - A voice engine held inside .venv is protected by its users' own locks, taken together before any change to the environment (v0.7.0 P04C Stage 1)

Plan Revision 2 §5.5 and §6 / P04C; recorded by Claude Code. Supersedes P04A's assumption that a running engine would make a repair
fail safely: P04B proved natively that Windows renames a folder whose programs are mapped into memory, so file-system refusals protect
nothing here.

**Protocol.** Three lock files in the copy's `files/runtime-data/qwen3/`, all with `qwen3_runtime.FileLock`'s non-blocking byte-0
protocol: `setup.lock` (engine install/repair, `InstallLock`), `inference.lock` (every conversion, transcription and model check, held by
the app for the run; `InstallLock` takes it too) and `engine.lock` (held by the worker process itself, so an engine whose app has gone is
still seen). `shared/engine_lease.Lease` takes them in exactly that order, never waits, and on any refusal releases what it took in
reverse. The operating system drops them when a process dies (measured: free 0.22 s after a kill). Taking a lock creates its empty file
and writes nothing else.

**Who takes it.** `repair_venv` and `run_setup`, before recovery or any rename, whenever `.venv` or `.venv.replaced` holds anything under
`engines/`, held until commit/rollback/cleanup end. Busy, denied, unreadable or reached through a link is an immediate refusal with
nothing changed. With nothing held (the shipped `.venv-qwen3` layout) no lock is consulted and behaviour is unchanged. When the nested
layout is adopted and the installer can create the child, the lease must be taken unconditionally (adoption stage).

**Machine guard excluded.** `MachineGuard` keeps every copy of the app on the computer to one model on the GPU at a time; it protects no
file of this copy, and every user of this copy's engine already holds `inference.lock` or `engine.lock`. Taking it would refuse this
copy's environment repair because another copy (or another Windows user) is converting, and its `denied` case could block the repair
of a broken app indefinitely. Reversible: one more lock in `ORDER` if the owner rules otherwise.

**Worker.** Refuses (stage `engine`) before any heavy import when its job names no `engine_lock`, when that lock is held, or when its
interpreter's prefix lies inside `.venv.replaced*` or `.venv.discarded*`: an engine only ever runs at its own final path.

**Superseded environments.** Renamed to `.venv.discarded` before deletion, so a deletion cut short (mapped DLLs, a crash) can only be
finished, never restored as last-known-good. A leftover is reported in the log and the repair message (still a successful repair — the
new environment launches — but never a clean one); recovery finishes deleting it. A rename refused by an open handle keeps the old
environment whole under its own name.

## 2026-10-24 - The app environment's own lifecycle keeps anything held under .venv/engines/; the nested Qwen3 layout stays a candidate, not adopted

Plan Revision 2 §5.5 and §6 / P04A (owner task "Execute P04A: Nested Environment Lifecycle Safety and Recovery Tests"); recorded by
Claude Code.

**Not a topology change.** Qwen3 still runs from `.venv-qwen3` (`qwen3_runtime.venv_dir()` unchanged). `.venv/engines/qwen3/` is a
candidate only: nothing installs there, nothing is migrated, and adoption needs P04B's real proof and the owner's decision.

**Vocabulary.** New `shared/venv_layout.py` (read-only, standard library only, imported by the bootstrap and the cleanup
coordinator). Anything under `<parent>/engines/` is *held*: a folder, a file or a link, with an unreadable folder counting as holding
something. A child environment is identified, never assumed: at its own final path, reached through no link below the repository
root, `include-system-site-packages = false`, interpreter present, not built from the parent's interpreter, still where `pyvenv.cfg`
`command` says it was created, and matching a recorded base-interpreter identity (home, version, executable, its size and mtime).
Missing, changed or unrecorded evidence is `unverified`, never healthy, and identity is not engine health (the import probe is still
required). The two Qwen3 locations are named exactly; both present is reported, never resolved by deleting one.

**Bootstrap transaction** (inert today because nothing is held). `VenvReplacement.commit` first moves `engines/` from the set-aside
environment into the replacement (one `os.replace`, so it is in exactly one place at every instant and returns to the same absolute
path), with the same bounded Windows WinError 5/32 retry as setting a venv aside (now one helper, `_replace_retrying`). An aside that
still holds anything is never deleted; commit keeps it (`retained`), the repair still succeeds and says the folder was kept, and the
next recovery retries. A rollback moves whatever the candidate holds back into the aside before deleting the candidate and refuses to
delete if it cannot; it now removes the candidate's import proof before deleting anything, so an interrupted rollback can never be
mistaken for a finished repair. Recovery applies the same rules in every branch. A link, a conflict (both sides hold something) or a
refused rename leaves both sides as they were. The main repair cannot reach the Qwen3 installer.

**Cleanup.** The "Private Python environment" item is refused while `.venv` holds anything under `engines/`, both in the inventory (row
present, not selectable, with the reason) and again in the coordinator immediately before acting: "dependencies rebuild on the next
launch" is not true of a voice engine. The catalog is still exactly four items; including or separately offering a held engine is a
P04C/owner decision. The coordinator's module set grows by `venv_layout.py`.

**Qwen3 removal.** `safe_to_remove_environment` and `environment_location_problem` also refuse a link in any folder between the
repository root and the environment (`qwen3_runtime.link_below_root`). For `.venv-qwen3` this is exactly the old leaf check; for a
nested path it closes a bypass in which a junction at `.venv` or `.venv/engines` to another folder inside the repository passed both
old checks and a rebuild would have deleted that folder's contents.

**Not chosen:** copying or renaming an installed environment into the nested path (environments are not relocatable; the identity check
rejects a moved one); merging or choosing between two held copies; deleting a backup that holds the only copy; force-stopping
processes, elevation, ACL or antivirus/Smart App Control changes to make a rename succeed; widening retries beyond the existing 250 ms.

**Not changed.** Production paths, model pins, generation parameters, TTS behaviour, the transcript bundle, the six WAVs, the 28
previews, version identity 0.6.6.

---

## 2026-10-24 - Developer mode is a typed config.toml boolean, shipped false; the reference-transcript tools and any local override are developer-only

Plan Revision 2 §5.3 config contract and §6 / P03D (owner task "Execute P03D"); recorded by Claude Code.

**Setting.** `config.toml` gains `[development] developer_mode = false`. `shared/config.py` accepts only a genuine TOML boolean
(`type(raw) is bool`); a missing key or section is the built-in `false`; a string ("true"), number, table, date or malformed file
resolves to `false` with the normal per-key diagnostic. The typed immutable snapshot carries it as `EffectiveConfig.development.developer_mode`
with its source layer (`default` or `config.toml`). It is not a `settings.json` overlay (`SETTINGS_OVERLAY` is unchanged, so any settings key
naming it is reported and ignored), there is no environment-variable shortcut, and the app never writes the TOML. `config.developer_mode()`
reads the cached snapshot, so an edit takes effect when the app is started again (documented in the TOML). The repository gate
(`verify.py` config check) fails unless the committed file states `developer_mode = false` explicitly, and the packager refuses a checkout,
and re-checks each finished archive's own `config.toml` member, unless it says exactly `false`.

**Normal mode (false).** "Install / repair Qwen3 voices" creates no transcript-tool button (`btn_clones is None`); installing, repairing
and all eight Qwen3 voices are unchanged, and the six clones read only the shipped bundle (P03C). Nothing checks, downloads or runs the speech
recognizer. Enforcement is in the backend, not only the widget: `qwen3_runtime.require_developer_mode()` (`DeveloperModeRequired`) guards
every restricted path. `load_transcript(..., override=)` returns a refusal. `ACT_QWEN3_TRANSCRIPTS` is ignored (`local_store_path()` is the
default file). A selection file is never read. `qwen3_clone_setup` refuses `install_recognizer`, `create_drafts` (through
`drafting_problem`), `approve`, `write_store`, `select_for_narration` and `return_to_shipped` before touching the store. The clone dialog
refuses to build. `qwen3_transcript_review.py` refuses `build`, `apply` and `status --store` (plain `status` still reports the bundle), and
`voice_previews.py` refuses `--provisional-transcripts` and the provisional loader. The calm harness only reads `load_transcript` and needs no
gate.

**Developer mode (true).** One entry point appears: "Developer tools → Reference transcripts..." (dialog title "Developer tools →
Reference transcripts"), reusing the existing recognizer-install / local-draft / listen-and-approve workflow and its save-error recovery. The
dialog states that local approvals do not replace the shipped transcripts. Downloads and transcription still need their own button and
confirmation. Developer mode alone activates neither the ambient store nor the variable: narration changes only for a clone the developer
deliberately selects ("4. Narrate with my approved texts...", confirmed; "Use the shipped texts" undoes it). The selection is private state in
`files/runtime-data/qwen3/transcript-selection.json` (ignored, never packaged): `{"schema": 1, "voices": {<voice_id>: {"reference_id",
"wav_sha256", "text_sha256"}}}`. It stores no text or path, is keyed by stable voice id, and only an approved local entry for the recording on
disk can be selected (all or nothing). At use, the local entry must still be literally approved, bound to the registered recording, pass the
bundle's text rules and hash to the selected digest. Otherwise that clone fails closed with "Developer tools → Reference transcripts" advice and
never falls back to the bundle. A damaged selection file refuses all six until it is cleared. The bundle file is never written. A preview never
records a developer-selected text as the shipped one.

**Not changed.** The bundle (`dd953523…7429`, byte-identical), the six reference WAVs, the 28 preview WAVs, speech parameters, P01 tail and
P02 naming policies, the other engines and tools, version identity 0.6.6.

---

## 2026-10-24 - The six clone transcripts ship as a curated bundle; narration trusts only that verified bundle

Owner approval 2026-10-24 (plan Revision 2 §5.3 step 5 / P03C, owner rulings Q8, Q13, Q35); recorded by Claude Code.

**Approval.** The owner personally reviewed and approved the six final Qwen3 clone reference texts in the 4,334-byte private review file with
SHA-256 `48f5dbeff1e866f94da2b4f93fc91a2842533ed96a5c1b0661605295ab20c236` (not the superseded `c22a9dc5…9b4`), and authorised publishing exactly
those six texts, only in `scripts/tts/data/bundled_clone_transcripts.json`, with only these fields: top level `schema_version`, `bundle_revision`,
`entries`; per entry `reference_id`, `voice_id`, `wav_sha256`, `text`, `text_sha256`. No approval record, personal information, original store or
review artifact is published. The approval does not cover further transcript changes, audio synthesis or P03D. The private review file, the preserved
store and all review evidence stay ignored.

**Generation.** `files/dev-tools/clone_transcript_bundle.py` (developer only) read the approved file once and refused it unless its SHA-256 equals the
approved hash. It refused any envelope or entry whose fields were not exactly the expected set, and checked the six registered IDs in order with their
voice IDs and WAV hashes, each text (non-blank, ≤ 2,000 characters, no outer whitespace or control characters, Male-4 starts with "Hello Arthur.") and
the six recordings on disk. It then wrote the bundle by exclusive create, copying the texts byte for byte (UTF-8, LF, fixed key order). The model
never typed or read the texts. The result: bundle revision 1, 3,002 bytes, SHA-256 `dd9535236ca2d09012ffdc1946de78115176dc95902da47e9ae7cdbb51cd7429`. The
six text digests equal the owner-validated ones (Female-1 `74b8174d…`, Female-2 `dd7cbd39…`, Male-1 `5afea1f7…`, Male-2 `3589fb60…`,
Male-3 `7be44794…`, Male-4 `a66dcfea…`), and `test_bundled_clone_transcripts.py` pins all six. `--check` mode reproduces the committed file byte for
byte. `.gitattributes` keeps `scripts/tts/data/*.json` LF on every checkout. Hashing is integrity binding, not a publisher signature.

**Resolution (supersedes the v0.6.7 Q5 "never committed, each user approves locally" rule).** `qwen3_runtime.load_transcript(voice_id)` returns the
bundle text exactly as stored (no strip, no normalisation) and nothing else: no search path, no `ACT_QWEN3_TRANSCRIPTS`, no local store. A local
store is read only through an explicit `load_transcript(..., override=path)` (the maintainer tools); `local_store_path()` names where those tools
keep it. The whole bundle is validated on every read (`load_bundle`): exact top-level and entry field sets, `schema_version` the integer 1, a
positive integer `bundle_revision`, exactly six entries for the six registered clones with no duplicates, the registered voice ID and recording hash
for each, text rules as above, and a lowercase `text_sha256` equal to the UTF-8 digest. Duplicate JSON keys, a BOM, invalid UTF-8/JSON and files
over 64 KiB are refused too. A bundle that fails any check is trusted in no part: all six clones report "Setup required for <label>: the reference
transcripts shipped with the app are … . Extract a fresh copy of the app to restore the files it ships with." The presets, Edge, Kokoro and
Chatterbox are unaffected, and nothing falls back to a local store. A recording whose bytes differ from its registered hash still blocks only its own
clone (Q10, unchanged). A fresh install with the engine, the Base model and the six recordings therefore has six ready clones, with no recognizer, no
approval and no write.

**Tooling and UI.** The install dialog reports "Cloned voice transcripts: included with the app." (or the bundle problem) instead of a local
"set up: N of 6" count. "Set up cloned voices…" stays visible until P03D gates it behind developer mode. Its wording and the clone-setup module now
call it a maintainer workflow whose approvals stay in the local store and do not change the voices. `qwen3_transcript_review.py status` reports the
bundle, and `status --store FILE` reports one named store. The voice-preview tool's provisional loader takes `override=`, and its README paragraph now says
the app uses the shipped approved texts (the six clone preview WAVs are unchanged and still labelled provisional). The calm-narration harness already
used the app's resolution, so it now reads the bundle. The README's "Set up cloned voices" step is removed.

**Packaging.** The packager already ships every tracked file under `scripts/`, so the bundle ships with no packager change. The tests' blanket "no
member names a transcript" ban becomes a one-path exception for exactly `scripts/tts/data/bundled_clone_transcripts.json`. Near-miss paths and every
local store, model, environment and log stay refused, and the bundle must appear once in each archive with its committed bytes. A packager-side
allowlist check stays with P07A.

**Not changed.** Voice identity, recordings (6/6 Appendix A), the 28 preview WAVs, generation parameters, `config.toml` (P03D adds `developer_mode`),
the extraction helper and the original private store (`8469606c…`, untouched).

---

## 2026-10-24 - The six clone references live in files/Cloned-Voice-Uploads/, resolved canonical-only; the no-echo extraction helper is tracked developer tooling

Plan Revision 2 §5.3 and §6 / P03A; recorded by Claude Code.

**Move.** The six tracked WAVs moved by scoped `git mv` from `files/Chatterbox-Voice-Uploads/` to `files/Cloned-Voice-Uploads/`; basenames and bytes
unchanged (SHA-256 = plan Appendix A, 6/6). The old folder was not moved or emptied: it keeps the owner's six ignored MP3 originals.
`voice_registry.REFERENCE_DIRECTORY` is the one path authority for both engines; `release.REFERENCE_ASSETS` keeps its own literal closed allowlist (the
packager imports nothing from the app) and a test pins the two together. This completes the 2026-10-24 P02A note that the directory stays until P03A.

**Canonical-only; no legacy lookup.** No supported workflow leaves the recordings at the old path: a fresh archive ships them at the new path and an
archive extracted over an older folder writes them there too; a git checkout moves them with the commit; there is no in-app updater and the README
documents fresh extraction only; the P12 restoration covers `.venv`, `.venv-qwen3` and `files/runtime-data`, never the references; Chatterbox
derivatives/conditionals and Qwen3 transcript bindings are keyed by WAV SHA-256, not by path (the clip manifest's `source_path` is never read back). So a
missing canonical file is "setup required", a canonical file with the wrong hash fails closed, and an old copy is never consulted, opened or deleted.
Revisit only if a supported path that needs a lookup is found; then it must be exact-basename, hash-matched, canonical-preferred and report conflicts.

**Ignore rules.** `files/Cloned-Voice-Uploads/*` with exact-basename exceptions for the six WAVs; `files/Chatterbox-Voice-Uploads/` ignored whole, so a
WAV cannot be re-added at the old path. Fixes baseline hazard H4 (the exceptions named non-existent `Female-1.wav`-style files; the real WAVs were
tracked only because they were already indexed). Git on Windows matches case-insensitively (`core.ignorecase`), so a case variant of a canonical name
matches its exception; on that filesystem it is the same file.

**No-echo helper.** `files/dev-tools/clone_transcript_extract.py` implements §5.3 steps 1–3 and 6: store found only through the named preservation
manifest, read once read-only and fingerprinted before/after, exactly six IDs with literal `approved: true`, registered WAV and text digests, Male-4
opening check, exact text copied without strip or normalisation, exclusive-create owner-only ignored output, link/escape/overwrite refusals, and
metadata-only stdout/stderr/report (unexpected exceptions by type name only). Adapted from the ignored private tool used for the earlier exceptional
review, with: the manifest named by argument and its tag read from `preservation-<tag>.json` (no owner-specific constant in tracked code); the
canonical folder; owner-only access in both modes (the private tool restricted only review-pending); a store size cap; a fixed refusal for an existing
run folder. Its registry is pinned and test-checked against the app. Tested on synthetic fixtures only (`test_clone_transcript_extract.py`); it has
not been run on the real store. P03B runs it unchanged, and only when authorised. The private tool and its owner-edit validator stay ignored.

**Not changed.** Transcript resolution (`qwen3_runtime.load_transcript` and its search paths), voice identity, naming, timing and generation parameters.
The previously validated private review artifact stays UNAPPROVED and NOT FOR SYNTHESIS (identity in ignored evidence only); that exceptional review is
not P03B or P03C authorisation.

---

## 2026-10-24 - One TTS output name: <source-stem>-<frozen display label>.mp3; collisions numbered; an invalid voice list is a registry error

Owner decisions Q4/Q5/Q6 (plan §2 and §5.2), implemented at P02B; recorded by Claude Code.

**Name.** Every narration route (Edge direct and folder, Kokoro, Chatterbox, Qwen3 presets and clones, standalone `batch_convert.py`) names its file
`<source-stem>-<display label>.mp3` through `tts/output_names.py`. Superseded: Edge direct `<stem> (<speaker>).mp3` and every other route's `<stem>.mp3`.
The label is frozen by value in the run's tool options (`freeze_tts_options(label=...)`) and destinations are planned from that frozen value once, at
run start; a retry reuses the planned destinations, so a renamed or reordered registry moves no run. The label is only ever text in a file name. No
backend or voice-id suffix is added; clashes (existing files, case-only, Unicode-composition and sanitised duplicates, same-stem PDF/TXT, duplicate
occurrences, mixed direct/folder) are numbered by the shared `DestinationPlanner` (`stem-1.mp3`). The Edge direct engine still writes its private
`<stem> (<speaker>).mp3` inside a temporary folder; only the planned name is ever published.

**Sanitation (TTS-local, on top of `shared.output_paths`).** Stem and label are cleaned separately (so `AC/DC` is `AC_DC`, not a name cut at the `/`):
NFC, control characters dropped, Windows-forbidden characters and separators and unpaired surrogates become `_`, outer whitespace stripped; spaces,
punctuation and Unicode kept. A device name is guarded with `_` only where Windows would see one (before the first dot: `nul.backup-…`); `CON-Label.mp3`
is legal and kept.

**Length.** A planned name leaves room for the longest collision suffix (`-10000`) and the longest temporary publish name (`.<8 hex>.part`, Qwen3):
20 units in the 255 component and, where the platform limits it, in the whole path (Windows without long-path support: 259, folders 247, counted in
UTF-16 units; macOS/Linux: 1023 UTF-8 bytes; Windows with `RtlAreLongPathsEnabled`: component only). Only the source stem is shortened, from its end;
the label is never cut. If even one stem character cannot fit, or the folder itself is too deep, planning raises `OutputNameError` (an
`OutputPathError`) before anything is synthesised, and the panel releases the empty run folder it had reserved.

**Standalone helper.** `run_batch_convert(label=None)` defaults to the registered label of the Edge `speaker` and refuses an unregistered speaker
without an explicit label (`--label`). Without `--resume` an existing file is never overwritten (the new file is numbered); with it, names are planned
without the disk so an earlier output is found under its own name and skipped. The Edge folder route's scratch folder is now a 16-hex digest of the
destination (the joined relative path could exceed one 255 component). Non-TTS tools' names and `shared/output_paths.py` are unchanged.

**Registry error at launch.** The launcher's per-tool error panel recognises a genuine `tts.voice_registry.VoiceRegistryError` (class name, defining
module and `ValueError` base; the exception itself only) and shows its message with "correct the listed entries in scripts/tts/voice_registry.py"
instead of "a dependency is missing … reinstall requirements". TTS stays unavailable (no fallback, no skipped voice); the other five tools load. Every
other load failure keeps the original advice and traceback. The status bar still reads "— ready." after any failed load, as before (pre-existing).

## 2026-10-24 - Voice identity is (backend, voice_id); labels and order are cosmetic; the six recordings are fixed by table

Owner decisions Q5/Q31 (plan §5.2), implemented at P02A; recorded by Claude Code.

**Identity.** `VoiceEntry.key == (backend, voice_id)` is the durable identity. `display_label` and row position may be edited freely: the dropdown is
`VOICES` order exactly (engine groups may interleave; nothing regroups or sorts), the default is `DEFAULT_VOICE_KEY` (Steffan) under whatever label he
carries (`default_voice_label()`), and lookups (`voice_by_key`, `label_for`, `get_voice`) read `VOICES` at call time.

**Recordings by table, not by label.** `reference_recording_filename(voice_id)` (which built `"<Chatterbox label>.wav"`) is replaced by explicit data:
`VOICE_REFERENCES[(backend, voice_id)]` → stable reference id (`Female-1` … `Male-4`, which is also the Qwen3 transcript key `reference_name`) →
`REFERENCE_RECORDINGS` fixed basename (`Chatterbox - Female 1.wav` … `Chatterbox - Male 4.wav`, unchanged). `reference_recording_filename(backend,
voice_id)` now takes the backend. `CLONE_REFERENCE_VOICE` (qwen→chatterbox id map) is removed; the shared recording is found through the reference id.
The directory stays `files/Chatterbox-Voice-Uploads/` until P03A. This supersedes the 2026-10-20 "reference recordings named after their labels" wording
(the files, bytes and hashes are untouched).

**One label authority.** `qwen3_runtime.Qwen3Voice` and `chatterbox_synth.ReferenceVoice` no longer store a label; `.label` is a property reading the
registry by stable key (lazy import in `qwen3_runtime`, so the registry never imports an engine). Visible consequences: Chatterbox engine log/status text
now says `Chatterbox - Female 1` (the registry label) instead of the engine's own em-dash `Chatterbox — Female 1`, and the Qwen3 install dialog lists
the presets as `Qwen3 - Aiden and Qwen3 - Ryan` (was the fixed `Aiden and Ryan`). An unregistered Chatterbox evaluation candidate is shown by its id.
Model descriptions (`CustomVoice`, `Base`), preset speaker tokens (`Aiden`, `Ryan`) and the clone generation profile are unchanged.

**Validation (`registry_problems` / `check_registry`, run on import).** Refused, each with the stable keys named: unknown backend; a voice id that is not
a plain token; the same `(backend, voice_id)` twice; the same voice id under two backends (preview files and the panel's voice code key on the id alone);
an empty, padded or control-character label; two labels equal after Unicode NFC (displayed text is kept exactly as written; case-only differences are a
P02B filename concern, not a label duplicate); a missing default voice; a Chatterbox row with no reference mapping. On import failure the launcher's
existing per-tool error panel shows the message for TTS only; other tools load (bootstrap never imports the registry).

**Panel.** `run_job` refuses a label that resolves to no registered voice ("Voice not recognised") instead of the old silent fallback to backend `edge`
with the last voice id. `_default_timing_preset` is now unreachable from `run_job`; it is left in place (P01 tests pin it) for a later cleanup decision.

**Previews.** `files/dev-tools/voice_previews.py sync-labels` is a metadata-only operation: it copies registry labels and order into `previews.json`
and re-renders the README; it reads no WAV, calls no engine, downloads nothing, refuses a roster or engine change, and its result must pass
`label_sync_problems` (only per-voice `label` and voice order may differ) before anything is written. `check` now also reports labels that differ from
the registry ("run sync-labels"). The existing `sync` was measured as a no-op on the committed manifest and is unchanged.

## 2026-10-23 - P01C before the combined owner listening session (checkpoint order only; acceptance unchanged)

Owner direction 2026-10-23 ("ACT v0.7.0 — P01C Edge EOF remediation and five-voice listening evidence"); recorded by Claude Code.

**The owner wants real production samples of all 28 voices before one consolidated manual listening session, so P01C (Edge) is implemented and
technically verified before the P01B listening checkpoint instead of after it.** The plan (§6 P01B/P01C exit rows) put owner listening of the local
endings before further audio changes; this changes the order of checkpoints only.

- Acceptance standards are unchanged: every ending still needs ≤ 300 ms measured trailing near-silence **and** owner listening PASS (§5.1). Mechanical
  figures never stand in for listening.
- Status words stay exact: P01B owner listening **NOT RUN**; combined 28-voice listening **NOT RUN**; P01C technical verification may PASS while its
  owner listening stays **OPEN**. Nothing is marked accepted without the owner's exported verdicts.
- If the combined session finds a clipped or wrong ending (local or Edge), it is corrected then; no long tail is added to compensate (§6 P01 exit).
- P02/P03 and later phases are not authorised by this exception.

## 2026-10-23 - Edge narration ends with its last sound: direct and folder routes share the P01B final-tail policy

Owner decision Q1 (plan §5.1), implemented at P01C; recorded by Claude Code.

**Edge direct (`epub2tts_edge.read_book` → `make_mp3`):** the book's final sentence gets no sentence/paragraph pause and the final chapter no chapter
pause; every pause between rendered content (sentence, paragraph, comma/ellipsis/dash, title, between-chapter) is unchanged. `end_of_book_pause` is still
accepted by `read_book`, `run_conversion_job` and the `--end-pause` command-line option, so no caller breaks, but it adds nothing and its default is 0 —
the same treatment P01B gave the local engines' `end_silence_ms`. Measured old stack after the final word: paragraph 850 + chapter 2,000 + end 3,000 =
5.85 s (the "about 6 s" seen in the app).

**Edge folder (`batch_convert.merge_mp3s`):** the 50 ms `CHUNK_PAUSE_MS` join goes between chunks only, and `END_RECORDING_SILENCE_MS` (3,000) is
deleted rather than set to 0, so it cannot quietly come back. The padding Edge returns at the end of every earlier network chunk is pacing and is kept.

**One policy, no extra encode:** both routes apply `tts.audio_tail` (−60 dBFS nominal end + 150 ms, never less than the −70 dBFS end, terminal suffix
only) through a new pydub adapter `apply_final_tail_policy_to_segment`, which reads the segment's own signed PCM (8/16/32-bit) and returns an exact
sample prefix (`get_sample_slice`). It runs on the already-decoded assembly immediately before each route's existing single MP3 encode; the encoder calls,
bitrate handling and no-clobber/cancel paths are untouched (the direct route's encode line is byte-identical). The folder worker logs the tail line per
file; the direct engine prints it like its other progress lines.

**Deliberately unchanged:** the direct route's per-sentence −58 dBFS edge trim (approved v0.6.5; it also shapes every internal pause), the generic MP3/M4B
tools, the Edge CLI's own `--format m4b` route (not used by the app: it now has no closing pause structurally, but no tail policy, because applying it
there would mean another decode), and `generate_voice_samples`' raw single-chunk Edge preview call (no ACT assembly or pause; trimming it would add a
lossy generation). Speech-characterization goldens for `edge_direct`/`edge_folder` were regenerated on purpose; every changed field is the removed pause
arithmetic (`audio/p01c/golden-diff.txt`, `golden-reconcile.txt`); text, splits and the other four routes are byte-identical.

## 2026-10-23 - A venv that must be replaced but cannot be set aside fails the repair; Windows retries WinError 5/32 within 250 ms

Owner-authorised at P01B (owner task "P01B Windows Venv-Rename Reliability Fix"); recorded by Claude Code.

**When the health authority says REPAIRABLE, the old environment must be renamed aside before anything is created in its place.** If that rename fails
and the environment is still there, `_create_validated_venv` returns False and the repair reports failure with the previous environment unchanged. There is no
create, no package reconcile, no stamp and no commit. Before this, the environment was kept and `repair_venv` could report "rebuilt, with limits" when
nothing had been rebuilt. Healthy and deliberately DEGRADED environments are still kept as before.

**`_move_venv_aside` retries only on Windows and only for WinError 5 (access denied) or 32 (sharing violation).** These are the refusals another process's brief
handle causes, and they were measured to clear within 2 ms. It retries the same source and destination with delays of 5–80 ms inside a single 250 ms
monotonic budget. No sleep or attempt may run past that budget, and before each retry it re-checks that no aside has appeared. Any other error, or a refusal
that outlasts the window, is a failure.

Not chosen: unbounded or generic filesystem retry; ACL changes, elevation, process killing or antivirus/SAC exclusions; test-side retries, stubbing the
rename, or accepting a failed aside in tests. The test-side options would weaken the contract rather than fix the defect.

## 2026-10-23 - Qwen3 hash lock moves scikit-learn to 1.9.0 (Smart App Control drift; same build as the main environment)

Owner-authorised at P01B (plan Revision 2 §6); recorded by Claude Code.

**`scripts/qwen3-requirements.txt` now locks `scikit-learn==1.9.0 --hash=sha256:4306775fad04cc4b472a1b15af1ae9cede1540fbfcc17fbce3767cd8dc7ae283`**
(was 1.9.1 `4b59abb3…`). Smart App Control (Enforce) refused 1.9.1's unsigned `sklearn/utils/_isfinite` on HOME-PC. transformers' generation module
imports scikit-learn, so the Qwen3 worker could not start. The official 1.9.0 cp312 wheel is the one already pinned in the main environment. The full locked
Qwen3 stack with only this line changed was qualified first in a disposable environment and then in the live `.venv-qwen3`. Results: hashed install, `pip check`
clean, 0 SAC-blocked natives, the real worker probe passes, and so does the real-library self-check. The other 88 pins and hashes are unchanged. Existing
installs see a new requirements fingerprint and report "out of date". `qwen3_setup.install()` then re-runs the hashed pip command in place (a one-package
change) and re-records the probe. The full-check `repair()` path rebuilds the whole environment instead (`rebuild=True`, about 3 GB to download). That is
existing behaviour, not changed here.

Not chosen: disabling SAC or adding exclusions, wheel substitution outside the hash lock, or a rebuild of the 5 GB environment for a one-package delta.

## 2026-10-23 - scikit-learn pinned to 1.9.0 in the main environment (Smart App Control drift, srsly precedent)

Owner-authorised at P01B (plan Revision 2 §6); recorded by Claude Code.

**`scikit-learn==1.9.0 ; python_version < "3.13"` is pinned in `scripts/requirements.txt`.** scikit-learn is a transitive dependency
(chatterbox-tts → librosa 0.11.0, which accepts >=1.1.0), and transformers' generation module imports it, so every local engine depends on it. The 2026-10-21
fresh install resolved 1.9.1. On 2026-10-23 Smart App Control (Enforce) refused its unsigned `sklearn/utils/_isfinite` extension (earlier
`__check_build`), so Kokoro and Chatterbox could not import. Re-probing later the same day did not clear it. 1.9.0 is the build the main environment
ran from 2026-08-16. Its official wheel (sha256 `4306775f…`) was qualified in disposable environments and then in the live `.venv`: 0 blocked natives,
`pip check` clean, and the real Kokoro proof passes. Existing installs pick the pin up through the launch-time requirements reconciliation.

Not chosen: disabling SAC or adding exclusions (end users run SAC, so the qualification would stop meaning anything), unqualified wheel substitution, or waiting
indefinitely. `.venv-qwen3`'s hash lock stays 1.9.1 until its own qualification and an owner decision. The srsly entry's recommendation stands: a
full transitive lock of the main environment would prevent this class of drift. Still not done.

## 2026-10-23 - v0.7.0 supersedes the v0.6.7 release target; new working branch; owner preservation is guarded by exact ignore rules

Owner decisions from the approved plan `files/plans/ACT-v0.7.0-Final-Release-QA-Remediation-Implementation-Plan.md` (Revision 2: D36, Q33, §3),
recorded by Claude Code at checkpoint P00B.

**The release target is v0.7.0 (D36).** The Revision 2 plan is the authority for the remaining release work. It supersedes the v0.6.7 remediation target
and the "Codex closure check, then version bump, merge, tag and release" sequence in the 2026-10-21 records. Historical v0.6.7 plans, evidence and
entries keep their original identifiers and are not rewritten. Code and config identity stays 0.6.6 until the separately authorised final-identity
checkpoint (P11); each plan checkpoint is separately assigned and stops for review.

**New working branch from the verified feature tip (Q33).** `feature/0.7.0-release-remediation` was created from `feature/0.6.7-speech-pipeline-and-layout`
at `d61822b` after confirming that tip equals the remote tip, never from `master`. The old branch is preserved; no history rewrite, no remote deletion.

**Owner preservation is protected by exact ignore rules, not by cleanup (§3).** The three directories renamed before the 2026-10-21 fresh-install test
(tag `20261021-184021-592ae0be`) are ignored by root-anchored, directory-only rules that match only those exact names; near-miss names, nested copies and
other paths stay visible. This was proved with `git check-ignore` on synthetic paths, without reading the private contents. They are not install, repair,
migration or cleanup targets and no interpreter inside them is run; restoration is plan checkpoint P12 only, with separate owner approval. Ignoring them
does not replace explicit, path-scoped staging. Rejected: a broad `*.act67-preserved-*` glob (it could hide unrelated future work) and ignoring their
parent folders.

**The plan lives under `files/plans/`, not `md-instructions/`.** The four-document contract (`Briefing.md`, `Handoff.md`, `Decisions.md`, `Changelog.md`)
is unchanged. The tracked plan contains no absolute local path or account identity; owner- and machine-specific details stay in ignored evidence under
`files/dev-work/`.

**Known local-only items stay as found.** `.ai/`, `scripts/project-status.py` and `files/run-temp/` remain untracked, unignored and unstaged by owner
decision; no new ignore rule was added for them. A clean checkpoint exit means clean tracked and staging state, not an artificially empty `git status`.

Signed: the owner (plan Revision 2 decisions and the P00B brief); recorded by Claude Code.

---

## 2026-10-21 - v0.6.7 closure corrections: three-state Kokoro health, a fail-closed Qwen3 guard, one Tk bound, a session-wide test redirect

Implementation decisions by Claude Code under the owner's narrow corrective brief for the second Codex closure audit (CLR-001 to CLR-004).

**"Not proven broken" is not "proven healthy" (CLR-001).** `kokoro_is_healthy` returns `(True | False | None, reason)` and `ensure_kokoro_installed`
returns `True | False | None`; `None` means the proof timed out or could not be started. The smallest representation that keeps every caller's tuple
shape: tests and call sites that already unpack `(ok, reason)` keep working, and only the three callers that must tell the states apart (launch,
setup, repair) branch on `is None`. `None` is never recorded (no success cache, no failure cache), never triggers a repair, rebuild or download,
and launches the app with an honest notice; the next launch proves again, so a completed proof recovers to healthy or finds the real fault. After a
repair whose proof cannot finish, launch reports "unverified" at once instead of waiting out the same limit a second time.

**Machine-wide protection fails closed (CLR-002, owner decision).** `MachineGuard` uses the `Global\` mutex only. The `Local\` fallback is removed:
a session-scoped mutex cannot exclude another Windows session on the same GPU, and a fallback in one process with a Global guard in another would
protect different kernel objects. Outcomes are now distinguishable: `failure == "busy"` (wait timed out; the established contention message),
`failure == "denied"` (access denied opening an existing mutex; a message that says Windows refused permission and does NOT claim another user is
running anything), and a raised `Qwen3Unavailable` carrying the Windows error number when creation or the wait itself fails. Callers (the lease and
the model-load probe) take the message from `guard.refusal_message`. Normal contention, crash-release by the kernel and the per-installation file
locks are unchanged. Rejected: an "accepted reduced-scope" mode (more states to explain, and it would have to be surfaced by every caller).

**One bound for every Tk proof (CLR-003).** `probe_venv` uses `TK_PROOF_TIMEOUT_S` like `_tcl_tk_ok`; the stage-0 script already used 30 s. A source-level
test pins that no literal timeout sits beside a Tk proof, and real hung interpreters (and a real stage-0 `Test-Candidate` with an accelerated bound)
prove the bound is enforced and the child is gone. The macOS `.command` `tk_ok` still uses `tkinter.Tcl()` with no timeout; it only picks an
interpreter and the Python bootstrap proves real Tk afterwards, so it was left alone as out of scope (recorded in the Handoff).

**Test isolation is established by an explicit import, not by luck (CLR-004).** `conftest._isolated_runtime_data` imports `shared.paths` and
`shared.settings` (constants-only modules, safe to import, unlike `shared.bootstrap`) and redirects `paths.LOGS_DIR` and `paths.SETTINGS_FILE` for the
whole session, before any test body can start the logger. Redirecting `SETTINGS_FILE` (not calling `settings.use_path`) matters: ten test modules end with
`use_path(None)`, which falls back to `paths.SETTINGS_FILE`. Production log retention was not touched. The proof runs in a disposable copy of the
checkout, never against the real runtime-data.

## 2026-10-21 - v0.6.7 Codex audit remediation: no-clobber packaging, proved Kokoro health, a cross-installation Qwen3 guard, real Tk proofs

Implementation decisions by Claude Code under the owner's remediation brief for `files/dev-work/final-codex-audit/ACT-v0.6.7-Final-Audit.md`.

**Release archives are never replaced (AUD-001).** `release.py` checks both destinations first and refuses if either exists; nothing in `dist/` is deleted
or overwritten except the run's own `.staging-*` folder. Archives are validated member by member (order, size, CRC32 against the source, launcher mode 0755)
and published with `os.link`, chosen because it fails on an existing destination on NTFS, APFS and ext4 alike (`os.replace` would silently overwrite on
POSIX). If a later link fails, earlier links of the same run are withdrawn only while `os.path.samefile` proves they are still this run's file. A drive
without hard links is refused rather than given a replacing fallback. There is deliberately no "replace" option: moving old archives aside stays a manual act.

**Kokoro health = presence + a recorded offline proof (AUD-002).** Presence (`find_spec`) still runs every launch (cheap). The proof imports kokoro, torch,
misaki, spaCy, srsly, soundfile and scipy and, when spaCy's English model is installed, builds the English G2P with `model=False` under
`HF_HUB_OFFLINE=1`, so it can never download the Kokoro weights or spaCy's model. It is recorded in `.venv/.kokoro-proof.json`, keyed to the requirements
hash and the interpreter: success trusted 7 days (same as the import proof), failure 1 day. `kokoro_synth` deletes the record when a real pipeline load
fails. Repairs run `pip install -r scripts/requirements.txt` (never the hand-kept `KOKORO_PKGS` list), and a repair whose proof still fails is not rerun
that day, because reinstalling the same pinned files cannot change an Application Control decision. The repair no longer warms the full model (which could
download ~300 MB unasked); setup's opt-in warmup is unchanged.

**Qwen3 resource scope (AUD-003).** `rt.MachineGuard` is a Windows named mutex, `Global\AudiobookCreationTool-Qwen3-ModelGuard-v1`: one heavy Qwen3 model
operation at a time across every copy of the app and every Windows user/session (one GPU, one RAM). If Windows refuses the `Global\` namespace for any
reason other than access denied, it falls back to `Local\` (this logon session) and says so in `scope`. Access denied means another user's copy holds it
open and is treated as busy. Acquisition never waits; the kernel releases an abandoned mutex, so a crash cannot strand it; it is thread-owned, so it is only
used as a `with` block. Taken by `inference_lease` (conversions, transcription drafting) and around the install/repair model-load probe; downloads do not
take it. The per-installation `setup.lock`/`inference.lock` file locks stay for the installation's own files. A mutex rather than a shared lock file avoids a
global file location; Qwen3 is Windows-only, so elsewhere the guard is an explicit no-op (`scope = "none"`). The test suite uses its own mutex name.

**GUI health means Tk initialises (AUD-006).** One proof everywhere: `tkinter.Tk()`, `withdraw()`, `destroy()` before any event loop (no window), 30 s bound,
in the venv probe, `_tcl_tk_ok` and stage 0 (which now runs candidates as a bounded process, not with `&`). A TclError about a missing display is a property
of where the app runs, not of the environment: reported as degraded `no-display`, never as a reason to rebuild.

**Clone approval persistence (AUD-007).** `write_store` maps any filesystem error to `SetupError` with one actionable message; the dialog also catches any
other exception. Failures return before the rows reload, so the user's text and ticks stay. `atomic_write_text` removes only its own partial temp file.

**Packaging and docs (AUD-011/AUD-012).** The README gallery link is absolute and must name the same ref as `voice_previews.RAW_BASE` (a test pins that); both
move to the stable branch together at the owner's merge decision. The release walk skips exactly three tracked developer entry points
(`DEVELOPER_ONLY_SCRIPTS`); no application module imports them (tested on the built archive).

**Recorded, not changed (AUD-010).** The main `.venv` pins direct requirements only; transitive packages can drift between installs (two qualified
environments already differ in spaCy 3.8.15 vs 3.8.16), and Chatterbox's weights are fetched without a pinned revision. A full transitive lock and a pinned
Chatterbox revision are a separate, owner-approved change; nothing was upgraded or locked here. `.venv-qwen3` remains fully hash-pinned.

**Gates kept open, not waived:** AUD-004 (clean standard-user Windows install), AUD-005 (redistribution authority for the six reference recordings), AUD-008
(an exact final release-candidate ZIP), AUD-009 (real network acquisition of the Qwen3 models and recognizer).

---

## 2026-10-20 - v0.6.7 final implementation: owner listening approval, in-app clone set-up, Windows stage 0, the reference names and the B2 split

**Owner listening approval (owner).** The owner listened to all 28 published voice previews and approved their audio quality. The six Qwen3 clones PASS at temperature 0.70 and sub-talker
temperature 0.80 (`CLONE_GENERATION_REVISION = 1`); no further experiments. The 28 WAVs and every voice identity are preserved as published. This approves AUDIO; it approves no reference
transcript: the preview drafts stay provisional (`approved: false`) and nothing in the repository becomes a production transcript.

**Production transcripts come from each user, in the app (implementation decision under the owner's brief).** A clone is used only with a transcript the person at that computer approved,
bound to the recording's SHA-256 (unchanged loader rule). TTS Audiobook → "Install / repair Qwen3 voices..." → "Set up cloned voices...": (1) install the pinned Whisper small.en recognizer
(revision `e8727524…`, 11 files, 970,930,930 bytes, each size- and SHA-256-checked; only after the size is shown and confirmed), (2) draft all six locally in `.venv-qwen3`
(`qwen3_worker.py` job kind `transcribe`, at most 30 s of audio, result written to a file, never stdout), saved `approved: false`, (3) the person plays each recording, corrects the text,
ticks "I listened" and approves. An approved entry is never overwritten by a draft; a draft for a changed recording reads as stale. No CLI, no JSON editing, no review page, no external
provider, no silent download. Modules: `tts/qwen3_clone_setup.py`, `tts/qwen3_clone_setup_ui.py` (named so no tracked `scripts/` file name contains "transcript", the Q5 guard).

**Windows stage 0 (`scripts/shared/bootstrap_host.ps1`).** The launcher no longer depends on winget to get Python. Stage 0 RUNS each candidate (py launcher 3.12/3.11, the per-user and
Program Files installs, `python` on PATH; the Store alias is skipped) and accepts only 3.11/3.12 with ssl, venv and Tk. With none, it asks, then downloads the pinned python.org 3.12.10 amd64
installer (26,964,224 bytes, SHA-256 `67B5635E…95FB`, Authenticode subject must be the Python Software Foundation) into `files/temp/bootstrap/`, reuses it when still valid, and installs
per-user with no PATH change, no file associations, no py launcher. winget (user scope) is only the fallback. Exit 0 ok / 2 declined / 3 failed. Not proven: running the installer on
HOME-PC (it already has 3.12.10, and Windows Sandbox is unavailable), so the clean-machine path stays unverified.

**Reference recordings named after their labels.** `files/Chatterbox-Voice-Uploads/Chatterbox - Female 1.wav` ... `Chatterbox - Male 4.wav` (`git mv`, bytes and hashes unchanged), derived
from `voice_registry` (`reference_recording_filename`); one copy serves both engines (`CLONE_REFERENCE_VOICE`). `qwen3_runtime.reference_name` ("Female-1") stays the stable transcript key.

**S5 production fixes.** (a) Runaway Qwen3 chunk: longer than 1.0 s + 0.6 s per word → re-render with seed + k·104729, at most twice, keep the shortest (found as Ryan laughing after
"Chapter One"; Aiden unchanged). (b) The worker uses CUDA only when `is_available()` AND `device_count() > 0` (an empty `CUDA_VISIBLE_DEVICES` made PyTorch report a GPU it could not open).
(c) The clone set-up rows scroll inside a box sized to the screen (it was 942 px tall). (d) A status message became a named constant so no string `.set()` literal names a voice
(`test_voice_labels` reads one as a persisted voice setting). None of these changes text, chunks or seeds: `PIPELINE_REVISION` stays 1 and the A0 golden is unchanged.

**B2 (Plan 01B §5.1 Level 3).** `scripts/mp3_tools/` is split into `mp3/`, `m4b/` (`converter/`, `maker/`, `metadata/` + the shared M4B modules) and `artwork/`; 30 modules moved with their
names, classes and behaviour unchanged. Relative imports became absolute. `source_probe.APPLICATION_PACKAGES = ("shared", "tts", "mp3", "m4b", "artwork")`. Three content pins were
re-pinned on purpose (each records its previous digest): `shared/numbering.py` and `m4b/m4b_numbering.py` (docstring dotted names only) and `test_m4b_numbering.py` (imports and path
constants only). `paths.MP3_TOOLS_DIR` (unused) became `MP3_DIR`/`M4B_DIR`/`ARTWORK_DIR`. No stale-folder warning was added for `scripts/mp3_tools/`: it only ever existed in development
checkouts, where a pull leaves at most an ignored `__pycache__`.

**`srsly==2.5.3` pinned (release blocker found by the extracted-ZIP test).** The main `.venv` pins only direct dependencies; a fresh install resolved the transitive `srsly` to 2.5.4,
and Smart App Control (enforcing on HOME-PC) refused its unsigned `srsly/msgpack/_epoch` extension, so every Kokoro pipeline failed. 2.5.3 is the build S5 qualified and it loads under
the same policy; the launch-time requirements reconciliation applies the pin to existing installs. A full transitive lock of the main `.venv` (as `.venv-qwen3` has) is recommended, not done.

**Version identity stays 0.6.6.** `version.py` says the identity is bumped at the approved release-candidate checkpoint; no such approval exists, so the qualification archive is the
committed tree packaged as 0.6.6 and renamed `-identity-<sha>` in a separate folder. The bump to 0.6.7 is an owner decision.

## 2026-10-20 - Qwen3 clone previews: provisional transcripts for listening samples, the calmer profile, and the reference-tail fix

**Decision (owner).** The six clone previews are published NOW for the owner to listen to, before any further approval. The owner authorized using Whisper's existing drafts as PROVISIONAL reference text for these
listening samples only, and ordered less dramatic delivery. Publishing a sample is not an approval of its audio quality.

- *Provisional transcripts.* `voice_previews.py generate --provisional-transcripts` reads the Whisper drafts (`qwen3-initial/transcripts/verified.json`), proves each is bound to the registered recording's SHA-256 (they also read back at
  word error rate 0.00 against a fresh transcription of the originals), and lets the production clone path see them for exactly that one synthesis, in the tool's own process. The production approval rule is untouched: the application
  still refuses a clone without an approved, reference-bound transcript, nothing is ever written to `transcripts.json`, all six drafts remain `approved: false`, and no PASS decision was invented. Each clone preview records
  `transcript.status = provisional` (a hash of the text, never the text) and the README labels the rows "(provisional transcript)". Re-render with approved transcripts once the owner approves them.
- *Calmer sampling (production, clones only).* A clone job carries temperature 0.70 and sub-talker temperature 0.80 (the Base defaults are 0.90 / 0.90), forwarded by the worker as validated floats; top_p, top_k,
  repetition_penalty, max_new_tokens and the deterministic chunk seeds are the Base model's own / unchanged; Aiden, Ryan and the other engines are untouched. Proved in the installed `qwen-tts 0.1.1` that both values reach
  the talker and the code predictor. `CLONE_GENERATION_REVISION = 1` identifies the profile and is logged and recorded per preview; `PIPELINE_REVISION` stays 1 because the immutable A0 golden pins it and text, chunks and seeds are unchanged.
- *Root-cause defect found by validating the audio, and its fix.* Three clones (Female 1, Female 2, Male 4) opened with a stray leftover sound and, for Male 4, lost the word "Welcome"; re-seeding (six takes each) did not help. The cause:
  those three reference recordings were cut at 15.0 s mid-sound, and a clone continues from its reference, whereas the three whose references end in silence opened cleanly. Appending 0.6 s of silence to the reference copy fixed all
  three in a scratch test. It is now production behavior: `snapshot_reference` appends `CLONE_REFERENCE_TAIL_SILENCE_S = 0.6` to the COPY the worker receives, after proving the copy is the approved recording (the file in the
  repository, its hash and its transcript are unchanged; silence adds no words). This also removes the same stray opening from every chunk of a cloned audiobook, so it is a real application change that the owner's listening review covers.
- *What the preview tool now validates.* A preview must begin from near-silence (first 10 ms below -50 dBFS), a clone take must read back (local whisper-small.en) with its first and last word and a word error rate of at most 0.10,
  and a failing clone take is re-rendered with the next seed take (at most six; the take is recorded). A bounded clean-up for a short leftover (under 0.6 s, followed by a 100 ms pause) exists for the preview tool only; with
  the fix above none of the six needed a re-take or a trim (`seed_take` 0, `leading_fragment_trimmed_ms` 0).
- *Result.* 28 of 28 previews exist. All 28 read back at word error rate 0.00; clone pitch tracks each reference; the 22 earlier files are byte-identical to what was published. Not established without listening: naturalness,
  whether the calmer delivery is calm enough, identity likeness, and any residual artifacts. Two clips are loud (Male 1 peak 0.91, Male 3 peak 0.95; not clipped).
- *Verification.* Focused suites (preview tool 101, Qwen3 synth/worker/runtime/packaging/harness/review, release packaging, layout and boundary guards, A0) and mutation checks of the new guards; no full `verify.py`.

-- Provisional-transcript use and publication ordered by the owner (2026-10-20); recorded and implemented by Claude Code

---

## 2026-10-20 - Qwen3 clone narration: calm-delivery preference, the transcript review package, and the temperature experiment (owner-gated)

**Preference (owner).** The six Qwen3 Base clones should narrate calmly and evenly: noticeably less variation in pitch, emotional intensity and pace than their Chatterbox counterparts; no sudden
high-to-low pitch swings, exaggerated inflection, dramatic sentence endings, needless loudness or cadence changes, or different delivery between adjacent chunks. Each clone keeps its reference voice and
natural accent, accurate and complete text, natural phrasing and pauses, the six original Chatterbox reference WAVs (unchanged), and Qwen3 Base ICL cloning from an owner-approved, hash-bound transcript.
Excluded by the owner: a new model, voice substitution, style instructions embedded in the text, a pitch-flattening filter, a dependency upgrade.

**Facts established from the pinned install (no model loaded, no audio).** `qwen-tts==0.1.1`. Production passes no sampling argument, so a clone uses the Base model's own `generation_config.json` (the library's
docstring says `generate_config.json`; the code reads `generation_config.json`): `do_sample` true, `temperature` 0.9, `top_p` 1.0, `top_k` 50, `repetition_penalty` 1.05, `max_new_tokens` 8192, and for the
sub-talker `subtalker_dosample` true, `subtalker_temperature` 0.9, `subtalker_top_p` 1.0, `subtalker_top_k` 50. `generate_voice_clone(**kwargs)` forwards sampling arguments through
`_merge_generate_kwargs`: an explicit `temperature=0.9` is the identical merge to passing nothing, and `temperature=0.8` changes that one value and nothing else (proved against the real library by
`qwen3_calm_venv_tools.py selfcheck`, and by a test that runs it where `.venv-qwen3` exists). Each chunk's seed (`derive_seed`) does not depend on temperature, so candidates are paired.

**Could `subtalker_temperature` help?** Plausibly, but secondarily. In the model code the main talker samples one codec token per frame (the first codebook: what is said, its timing and its overall contour) and the
sub-talker (`code_predictor`) then fills in the remaining codebooks for that frame (acoustic detail). So the main `temperature` is the more plausible lever for pitch, inflection and pace, and the sub-talker's for
fine texture. That is an inference from the code structure, not a measurement. It is NOT varied in the first experiment (the owner asked for it to stay 0.9); the harness cannot override it. It is a possible second
axis if 0.8/0.7 do not calm the delivery enough, and adding it would be an owner decision.

**What was built (development only; nothing in production changed).**
- `files/dev-tools/qwen3_transcript_review.py`: builds `files/dev-work/qwen3-eval/transcript-review/review.html`, an offline, self-contained page that plays the six ORIGINAL reference WAVs (embedded byte for byte,
  each checked against the SHA-256 the app registered), shows each Whisper draft beside an editable field with a "listened" tick and PASS / NEEDS CORRECTION, and downloads one decisions file. `apply FILE` is a
  dry run; `apply FILE --write` records PASS entries as `approved: true`, bound to the recording's SHA-256, in the local untracked `files/runtime-data/qwen3/transcripts.json` (the file the app's own loader reads).
  Nothing is approved by building the page, by a dry run, by NEEDS CORRECTION or by an undecided voice; the Whisper drafts, the recordings and every tracked file are never modified.
- `files/dev-tools/qwen3_calm_worker.py` + `qwen3_calm_experiment.py` + `qwen3_calm_venv_tools.py`: the comparison harness. Every clip goes through the PRODUCTION entry point `qwen3_file_to_mp3` (its availability and
  transcript-approval rules apply; no `availability`, `python` or other safety seam is overridden). The baseline (0.9) runs the production worker with no override; a candidate runs the same production worker
  through a wrapper that forwards one extra argument, `temperature` (range 0.1-1.5), to clone `synth` jobs only (a preset such as Aiden or Ryan is never altered). Candidates 0.8 and 0.7, optional 0.6; the text
  (a fixed 2,328-character passage with prose, dialogue, punctuation and paragraph transitions), the reference, the transcript, the chunking, the seeds and every other control are identical. Output (WAVs, manifest
  with seeds and hashes but never transcript text, pitch/loudness/pace measurements, a whisper read-back for completeness, a labelled `listen.html`) goes only under ignored `files/dev-work/`, never into `files/voice-previews/`.
- Tests: `test_qwen3_calm_harness.py` (68) and `test_qwen3_transcript_review.py` (25), offline; 25 of 25 mutants of the new guards killed on the final pass (the one early survivor was a guard whose error was
  masked by a later one; its test now requires the explicit reason).

**Owner gate (unchanged by this entry).** No clone audio has been generated, because no transcript is approved. After the owner approves the six transcripts: run the harness on one female and one male clone,
provide labelled baseline / 0.8 / 0.7 samples for listening, and let the owner choose. Until the owner approves a candidate: no new production temperature, no change to the Qwen3 generation contract or pipeline
revision, no replacement of any published preview. If a lower temperature is approved: ONE shared, tested clone narration profile, a tracked pipeline-revision change, Aiden and Ryan untouched, and the six
genuine public clone previews generated with that profile. The transcripts must be verified and approved either way. No full `verify.py` before S5.

-- Preference and gate set by the owner (2026-10-20); recorded and prepared by Claude Code

---

## 2026-10-20 - Owner publication decision: preview audio for all 28 voices may be published (supersedes the Q5/Q8 preview restriction)

**Decision.** The owner explicitly authorized publishing short generated preview audio for **all 28 registered ACT voices** in `files/voice-previews/`. The earlier rule that kept
the Edge, Chatterbox and Qwen3-clone previews unpublished (CP6 rulings Q5 and Q8, 2026-10-19, and the Q8 rights gate built from them) is superseded **for preview audio**. It was
a mistake as a blanket block, and it must not be used to stop these samples being generated or uploaded. The 2026-10-19 entries stay as written; they are history.

- *What this is, and is not.* It is an **owner publication decision**. No third-party legal opinion was obtained and no external license or service terms (Microsoft's Edge Read
  Aloud service, the Chatterbox reference recordings' owners, the Qwen3 clones) were independently verified by this project; the manifest and README say exactly that and claim
  nothing more. For Kokoro and the two Qwen3 presets the earlier license-review evidence (Apache-2.0 model cards, hashed) is unchanged.
- *Scope.* Short generated preview audio only. **Not covered:** the private reference transcripts, the reference recordings (Q5 still applies to both: neither is committed), any
  untracked or private asset, the rejected Qwen3 presets, or any voice outside the 28 registered ones. Previews stay out of the release archives, as before.
- *Four things kept apart, because they are different facts.*
  1. **Publication permission: APPROVED** for 28 of 28.
  2. **Audio generated and verified: 22 YES, 6 NO.** Nine Kokoro, Qwen3 Aiden and Ryan (already published, untouched), and now five Edge and six Chatterbox. The six Qwen3 clones are
     NOT generated.
  3. **Qwen3 clone transcript validation is independently required.** A clone is only made from an owner-approved transcript bound to the reference recording's SHA-256
     (`qwen3_runtime.load_transcript`); the only transcripts on HOME-PC are the Whisper drafts in `files/dev-work/qwen3-eval/runs/qwen3-initial/transcripts/verified.json`, all six
     `"approved": false`. Nothing was approved, invented, bypassed or copied from Chatterbox. The six are recorded **pending generation** (not blocked) with that exact reason.
  4. **Qwen3 production-clone qualification is unchanged:** it remains under its separate S5 gates; a published preview does not qualify a voice.
- *Model.* `previews.json` is schema 2: an `owner_decision` block (stated by the tool and checked equal), per-voice `rights.status` of `confirmed` (license evidence), `owner_authorized`
  (the 17 voices the decision names, in `OWNER_AUTHORIZED_VOICES`) or `unresolved` (now meaning only *withdrawn*), and preview status `generated` / `pending` (with a required
  `pending_reason`) / `blocked` (withdrawal only). A schema-1 record that was `unresolved` is migrated once by `sync`; from schema 2 on an `unresolved` voice is never re-authorized
  by a sync. A voice added to the registry later is not in the decision, so it starts blocked until someone decides. The set is still never called complete while any row is
  missing, and a preview marked generated for a non-authorized voice is refused, uncounted and unrendered.
- *How the new previews were made (no substitution).* The same standardized sentence and target (24 kHz mono PCM16 WAV, edges trimmed to 120 ms, 8-13 s, no clipping or silence,
  SHA-256 and duration recorded). **Edge:** the folder route's own `batch_convert.synthesize_chunk_mp3` request for the registered voice at that voice's own rate, the service's MP3
  decoded straight to WAV (no re-encode); no retry, fallback voice or other engine, and a refusal is reported in the `edge_failures` wording and leaves the voice pending.
  **Chatterbox:** the production `chatterbox_file_to_mp3` on the bundled approved reference for that voice, pauses zero, encoder swapped for a lossless WAV and restored afterwards
  even on failure. Each voice asks the app's own availability answer first; one that cannot run here stays pending and is never a failure.
- *Verification.* `test_voice_previews.py` (70 offline tests; an Edge fake bound to the real `Communicate` signature, the Chatterbox/Qwen3 seams, the migration, the withdrawal path,
  the transcript approval rule on the real loader); 13 of 14 mutants of the new guards killed (the survivor, a duplicate non-mono check that `audio_problems` also makes, is
  redundant). All 22 files: whisper-small.en read-back WER 0.00 for the whole sentence, pitch consistent with the named voice (Chatterbox against its own reference recording),
  distinct SHA-256 per file, none clipped. No full `verify.py` (reserved for S5); A0 `check` OK; no production GUI, synthesis setting, model pin or A0-A6 behavior changed.
- *To finish the last six (owner action).* Listen to each reference recording, correct its draft transcript so it matches exactly what is spoken, set `approved: true` (the entry
  already carries the recording's `wav_sha256`) in the untracked `files/runtime-data/qwen3/transcripts.json` (or `ACT_QWEN3_TRANSCRIPTS`); then
  `python files/dev-tools/voice_previews.py generate qwen3-female-1 qwen3-female-2 qwen3-male-1 qwen3-male-2 qwen3-male-3 qwen3-male-4` and commit the six WAVs, manifest and README.
  The transcript is never committed.

-- Decided by the owner (2026-10-20); recorded and implemented by Claude Code

---

## 2026-10-20 - Edge TTS reliability and recovery (final hardening checkpoint): classify, retry only what can recover, say what to do

**Decision.** Both Edge routes (direct `run_edgespeak`, folder `convert_single_pdf`) now decide whether another attempt can help from the exception's real type and
attributes, instead of retrying every exception. One new module, `scripts/tts/edge_failures.py`, is the only place that classifies and words failures.

| Kind | Real signals | Retried? | What the user is told |
|---|---|---|---|
| service refused | `aiohttp.ClientResponseError`/`WSServerHandshakeError` status 401/403; `edge_tts.SkewAdjustmentError` | no | Microsoft's service refused the connection; retrying/reinstalling/updating may not fix it; check connection and PC date/time; report if it persists; an offline voice can be chosen *by the user* |
| protocol | other HTTP statuses (400/404/426/...); `UnknownResponse`, `UnexpectedResponse` | no | the service answered in a way this ACT version does not understand (it has probably changed); retrying will not fix it; report it |
| network / temporary | status 408/425/429/5xx; `WebSocketError`; `aiohttp.ClientConnectionError`/`ClientPayloadError`/timeouts; `TimeoutError`, `ConnectionError`, `socket.gaierror` | yes, the existing bounds | could not reach the service after several tries; check connection/VPN/firewall; Retry Failed |
| local | `OSError` that is not a network error, `ValueError`, `TypeError` | no | not an Edge message at all: the original exception is raised unchanged |
| cancelled | `ConversionCancelled`, `asyncio.CancelledError`, `KeyboardInterrupt` | no | never wrapped, never reported as a service failure |
| unknown | `NoAudioReceived`, other `EdgeTTSException`, anything unrecognised | yes, the existing bounds | failed unexpectedly after several tries; Retry Failed; report with the log |

- *Retry bounds are the approved ones, only applied to failures that can recover.* Direct: 3 attempts, 3 s apart. Folder: `CHUNK_MAX_RETRIES = 5` (2/4/8/16 s) inside
  `PDF_MAX_RETRIES = 2` whole-file redos (5 s) -- both constants and `INTER_CHUNK_DELAY_SEC` unchanged and still pinned by existing tests. A refused handshake used to cost
  3 requests (direct) or 15 (folder, 5 x 3, ~100 s of waiting); it now costs 1 and no wait. The folder's whole-file redo is also skipped for permanent failures.
- *Cancellation:* the folder route checks the user's cancel before each back-off and before the whole-file pause, so a cancelled run no longer sits out up to 30 s of waits.
  The direct route is unchanged there (cancel is already checked between sentences; its longest wait is 3 s).
- *Diagnostics survive, secrets and book text do not.* The final error is `EdgeServiceError` (a `RuntimeError`), `str()` = `<one-line advice> | Technical detail: <type,
  HTTP status, scrubbed message, attempt count, edge-tts version>`, with the original exception chained. Every URL query string and bare `TrustedClientToken`/`Sec-MS-GEC`/
  `ConnectionId` is removed (also from the folder route's traceback text in `batch_errors.log`). The direct route's log line no longer prints the sentence it was synthesizing.
  A failed attempt's partial audio file is removed. Nothing is published on failure: the direct route moves its file only after assembly; the folder route merges only after
  every chunk succeeded (unchanged).
- *Panel:* `record_failure` appends the advice line to the item's `display_message` when the failure text carries one (`split_failure_text`); the technical detail stays in
  `technical_detail` and the log. Items stay `retryable=True`, so Retry Failed means what it always did.
- *Recovery is guidance, not action.* Setup_and_Run is named only when the installed `edge_tts.__version__` differs from the pin (`EXPECTED_EDGE_TTS`, kept equal to
  `requirements.txt` by a test); a remote 403 is never promised to be fixable by reinstalling. `edge-tts==7.3.1` and every other pin are unchanged; no auto-upgrade, no
  alternative provider, no venv repair, no new startup network call, no fallback voice or engine, no dialog.
- *Not done on purpose:* a run-level circuit breaker that would skip the remaining files after the first refusal. Each file now fails after one quick request, the failures
  are individually retryable, and skipping would change which items are reported as failed. Revisit only if a service-wide outage makes long queues noisy.
- *Verification:* `files/tests/test_edge_failures.py` (57 offline tests; the real `Communicate` boundary replaced by a scripted fake that is checked against the real
  signature; real aiohttp/edge_tts exception types), three panel tests in `test_tts_jobs.py`; run against the pre-change route code the refusal, token and cancel tests fail
  (15 requests, token and sentence in the log). Eight mutants of the new logic killed. One live request through the production path with the pinned dependency and
  `en-US-SteffanNeural` succeeded (live availability is a service fact, not a test prerequisite). The full `verify.py` gate is reserved for S5; A0 `check` OK.

-- Decided by the owner's deferral (2026-10-20); implemented by Claude Code

---

## 2026-10-20 - Plan 01B checkpoint A6: the Chatterbox colon compatibility code is RETAINED WITH EVIDENCE

**Question.** With speech preparation on (A5, G2 passed), can either Chatterbox colon mechanism be retired?
(A) the structural-colon `punc_norm` patch (`_structural_colon_punc_norm`, `_ensure_structural_colon_patch`, applied in `_instantiate_model`), which keeps
times, ratios, references, URL schemes and paths away from the pinned wheel's blanket `:` -> `,`; (B) the prose-colon pause (`_PROSE_COLON`,
`split_at_prose_colon`, `COLON_PAUSE_MS = 75`, joined in `_synthesize_chunk`). Evaluated independently.

**Evidence (text level, no audio; `files/dev-tools/chatterbox_colon_matrix.py`, output `files/dev-work/speech-ab/a6/text-matrix.{json,md}`).**
- The pinned `chatterbox-tts==0.1.7` `ChatterboxTurboTTS.generate()` calls the module-level `punc_norm` unconditionally before tokenizing, with no parameter
  to skip or configure it; the wheel's `punc_norm` replaces every `:`. Token level (pinned tokenizer, offline): `6:45` -> `:` id 25 becomes `,` id 11;
  `https://` -> `://` id 1378 becomes `,` + `//`; `C:\` -> `:\` id 7479 becomes `,` + `\`. Colon-free text: identical ids.
- With preparation `v1` (A5 table) **and** `off`, these colons still reach `generate()` by policy and only the patch keeps them: cue-less times (`It was 6:45
  when`, `His best lap was 1:30`, `3:15`, `01:02:03`), bare ratios (`2:1`, DIFFICULT_SHORT's `3:1`), references (`John 3:16`, `clause 4:2`), URL schemes
  (`https://`, `ftp://`, `mailto:`) and Windows paths (`C:\`). Cued times and ratios (`6:45 p.m.`, `at 1:30`, `odds were 3:1`) are expanded in `v1` and no
  longer need it. DIFFICULT_SHORT: 4 colons kept by the patch with `off`, 3 with `v1` (`6:45`, `3:1`, the URL; `7:15` is expanded).
- Prose colons never reach the tokenizer either way (patched and wheel output are identical); their pause comes only from the split and the 75 ms PCM gap.
- The immutable A0 OFF golden (`files/tests/golden/speech/chatterbox.json`) pins both mechanisms: `colon_pause_ms` 75, the prose-colon segments, the exact
  `generate()` inputs, the patched `punc_norm` output (4 colons in `qc_difficult_short`, 5 in `punctuation`) and the assembled sample counts.

**Gate A (mechanical feasibility) not met -- no credible candidate, so no GPU evaluation was run.**
- (A) Unmet: A6 criterion 1 and prerequisites 1 and 3. No defined non-patch fate exists for the unexpanded and protected colons: (a) spoken forms for URLs and
  paths are URL respelling, closed as a forbidden substitution; (b) the only patch-free ways to keep a colon from the wheel are a look-alike character (the
  tokenizer then never sees the approved `:` / `://` tokens -- a new pronunciation contract) or re-implementing `generate()` against the wheel's internals
  (a deeper coupling than one attribute); (c) an accepted residual risk is not approved and is not a substitute for correctness. Expanding the ambiguous
  forms would reopen the A2-A5 ambiguity and protected-span policies, and `off` would still need the patch. Removing the patch changes the A0 OFF golden.
- (B) Unmet: prerequisites 3 and 6. Without the split the wheel reads a prose colon as a comma -- the 0 ms option the owner did not choose (0 / 75 / 125 ms set,
  2026-08-16). A text-only pause was proven impossible for a colon (every spacing variant normalises to the same comma); substituting other punctuation
  (`;`, `.`) would be a new pacing contract with a model-chosen, unseeded length, would add or remove prose colons (Plan 01B 3.3 forbids it), and before
  chunking would change the clause-level chunk plan (the semicolon outranks the colon). Removing it changes the A0 OFF golden. Mechanism B is the app's own
  assembly code, not a patch of the wheel; it depends only on the wheel turning a colon into a comma.

**Decision.** Both mechanisms stay unchanged, as an evidenced engine exception (Plan 01B 4.6 convergence rule; A6 criterion 5). No production code, wheel
pin, golden or test assertion changed. New tracked evidence: `files/tests/test_chatterbox_colon_a6.py` (mutation-checked: removing the patch, removing the
split or zeroing the pause each fails it); the existing colon contract tests are unchanged. G3 does not arise (no candidate audio).
**Re-evaluation:** at the final S5 review, or at any explicitly authorised Chatterbox wheel change (the byte-parity test in
`test_chatterbox_colon_integration.py` flags a `punc_norm` change), or if the owner approves spoken forms for URLs and paths.
*Observation, not a finding:* the split makes each colon segment its own `generate()` call, so the wheel capitalises the segment's first letter (`never` ->
`Never`) and the word before the colon ends a call (`one rule,`); this is the approved behaviour and the G2 recording passed by ear.

-- Evaluated and recorded by Claude Code under the owner's A6 authorisation; no owner verdict required (no candidate)

---

## 2026-10-20 - Plan 01B gate G2 approved (4/4 PASS); A6 authorised, G3 not approved

**Owner verdicts (G2, approved).** The owner listened to all four ~3-minute production recordings in `files/dev-work/speech-ab/g2/`:

| Recording | Verdict | Notes |
|---|---|---|
| `1-Edge-Steffan.mp3` | PASS | none |
| `2-Kokoro-Heart.mp3` | PASS | none |
| `3-Chatterbox-Female-1.mp3` | PASS | none |
| `4-Qwen3-Aiden.mp3` | PASS | none |

**Decision.**
- G2 is passed. No pronunciation, voice, timing, pacing or normalization change is requested; the A5 configuration (G1 mode table, four native exceptions,
  `[tts] speech_prep = "v1"`, Qwen3 revision handling) stands as approved. G2 samples are not regenerated; G1 is not reopened.
- The advisory Whisper read-back of "one rule:" as "one roll" in the Chatterbox recording is **not** an owner-reported failure: the recording passed by ear.
- A6 (Chatterbox colon compatibility retirement *evaluation*) is authorised. It is not permission to remove the workaround; removal needs the A6 mechanical criteria
  and owner gate G3, which is **not** approved.

-- Decided by the owner (G2 verdicts); recorded by Claude Code

---

## 2026-10-20 - Plan 01B gate G1 verdicts and checkpoint A5: the production mode table

**Owner verdicts (G1, approved).** 60 comparisons in `files/dev-work/speech-ab/a4/listen-ordered/`: 11 A, 18 B, 31 Same, 0 Neither, decoded through the private
key (A/B are listening slots, never preparation sides). Tracked record: `files/tests/golden/speech/g1-verdicts.json`. Decoded: 25 preferences for the expanded
reading, 4 for the engine's own reading, 31 Same.

**Decision.**
- *Rule.* A cell expands unless the owner preferred the native reading. A Same verdict expands (Plan 01B 7.2, convergence decision D6): all 60 pairs passed every
  mechanical and integrity check, so no Same cell was held back as mechanically unsafe. HYG (mechanical-only, never a listening class) expands everywhere.
- *Exceptions (native), each an explicit owner preference, each re-tested at the next RULESET_VERSION change and at S5:*
  - edge CUR (comparison 047, verdict B = native): Microsoft's server-side reading of currency was preferred.
  - edge FRAC (comparison 050, verdict B = native): the service reads `1/2 cup` well natively; preferred.
  - edge SYM (comparison 056, verdict A = native): native `&` / `x` reading preferred.
  - kokoro CUR (comparison 017, verdict B = native): misaki's own currency handling (it knows the `$` symbol) was preferred.
  Edge direct and Edge folder share the `edge` row (same service, same glossary scope); both routes are tested separately against it.
- *Default.* `[tts] speech_prep` defaults to `v1`; `off` restores the pre-A5 text exactly (the A0 baselines still characterize that path, unchanged).
- *Qwen3 revision.* `PIPELINE_REVISION` stays 1: it describes the planner/seed/generation/assembly code, which A0 proves unchanged, and the immutable A0 golden records it.
  A run with speech preparation on reports `SPEECH_PREP_PIPELINE_REVISION = 2` (`qwen3_synth.pipeline_revision`, logged in Details), because its text -- and so its
  chunks, seeds and audio -- can differ. This reconciles "bump the revision when audio can change" with "never edit the A0 goldens"; flagged for the owner.
- *Chatterbox colon shim stays* (structural-colon `punc_norm` patch, 75 ms prose-colon pause) until A6 decides.
- *A4 listening copies* in `listen-ordered/` were trimmed of terminal silence (evaluation hygiene only; production timing untouched).
- *Edge hardening deferred (owner, verbatim):* "ACT v0.6.7 will retain pinned edge-tts 7.3.1. A dedicated Edge reliability and recovery enhancement is deferred to
  final release hardening. It will consider service-failure detection, explicit recovery/repair, safe verified dependency updates, and preservation of user work. No
  automatic unverified upgrades or silent voice substitutions."

-- Decided by the owner (G1 verdicts, deferral); implemented by Claude Code

---

## 2026-10-20 - edge-tts pinned to 7.3.1; the A4 ordered listening export

**Decision.**
- *edge-tts 7.2.8 -> 7.3.1 (owner-authorized).* The read-aloud endpoint answers 7.2.8's WebSocket handshake with HTTP 403 (clock verified in sync); upstream issue
  #490 was fixed in 7.3.0, and 7.3.1 also fixes server date parsing. 7.3.1 declares the same four dependencies and every installed version satisfies them; a
  `pip install --dry-run -r scripts/requirements.txt` would change only `edge-tts`, and the bootstrap's own reconcile then changed exactly that one package. No other pin,
  no voice parameter and no protocol detail changed; no token is embedded. Proven first in a throwaway venv, then through `runner.run_conversion_job` for all five
  registered Edge voices. `test_edge_tts_pin.py` pins the version, the installed package, the `Communicate` API ACT calls, and the fingerprint change that makes an existing
  install reconcile.
- *Ordered export slots follow the blind sheet.* In `listen-ordered/`, `NNN-Engine-CLASS-A.wav` is the pair's lower-numbered blind clip and `-B` the higher one -- the same
  rule as the original sheet's First/Second -- never the preparation side. The private mapping (`key/ordered-mapping.json`) records each file's source clip, SHA-256 and side.
  The export copies bytes and never synthesizes. The first `listen/REVIEW-SHEET.md` is kept as issued; `listen-ordered/REVIEW-SHEET.md` is the current sheet.

**Why.** A non-technical user's Edge voices had silently stopped working; the A4 review needs all four engines and a folder that sorts naturally in Explorer.

-- Decided by the owner's instruction; implemented by Claude Code

---

## 2026-10-20 - Plan 01B checkpoint A3: how speech preparation is wired, frozen and kept switched off

**Decision.**
- *Normalization runs on the decoded text, before each route's structure stage.* The normalizer protects `Title:`/`Author:`/`#` markers and never changes a line count, so
  the structure stage sees the same structure, and every offset indexes the decoded source as Plan 01B 4.4 requires. Edge direct keeps `get_book`; it reads the prepared text.
- *One mode-table row per engine* (edge, kokoro, chatterbox, qwen3): the two Edge routes share the `edge` row, as they share the glossary scope. `data/modes.json` ships with
  all 64 cells `native` (D6).
- *The setting is a configuration key, not a settings.json key.* `[tts] speech_prep = "off" | "v1"` is validated in `shared/config.py` (unknown values fall back to `off`
  with a diagnostic). `USER_STATE_SETTINGS` lists only keys a real `settings.set` writer produces, so it does not gain one.
- *Off means the old call.* The panel passes `speech_prep=` to an engine, and the Edge runner passes it to `get_book`, only when the snapshot is enabled; an `off` run makes
  byte-for-byte the calls it made before, so existing engine fakes and the A0 baselines are untouched.
- *By value, once.* `SpeechPrepSnapshot` (frozen dataclass of tuples, frozen glossary entries) is built on the main thread at run start, frozen into `tool_options`, and
  re-used by Retry Failed. Worker threads never read a file. Notes (a broken user file) are written to Details once per attempt.
- *Defects never fail a conversion.* An integrity failure in one file falls back to that file's unchanged text with a Details line; an unreadable bundled mode table turns
  speech preparation off for the run with a note.
- *Qwen3 keeps its `Chunk`.* The A0 golden serialises `Chunk` with `asdict`, so source spans are not new fields: `qwen3_synth.chunk_source_spans` derives them through a
  verified structure map and the normalization map, only when preparation is on. Seeds still hash the spoken chunk text, so unchanged documents keep identical plans and seeds;
  `PIPELINE_REVISION` is not bumped in A3 because no audio can change.

**Why.** The owner's acceptance condition for A3: off and native paths must reproduce the A0 characterization exactly; a run must not be able to see a glossary edited after it
started; and broken user data must never cost a non-technical user a conversion.

-- Decided under the owner's A2-A6 authorisation; implemented by Claude Code

---

## 2026-10-20 - Plan 01B checkpoint A2: normalizer core decisions

**Decision.**
- *Hygiene resolves last, on what the classes leave.* Plan 4.3 lists hygiene above the classes; its spans are single characters, and the only overlap is a no-break space
  inside a numeric token (`5 km` from PDF extraction), whose spoken form already uses an ordinary space. Resolving it first would have blocked that token.
- *A claim is a claim.* An ambiguous token, and an edit whose class is not `expand`, still claims its span, so no lower rule rewrites part of it (`5 km` with UNIT native is
  never half-expanded by CARD). A mixed-number match also offers its bare fraction, because a longer claim can otherwise hide a candidate that a second pass would find (I6).
- *Mode semantics.* `expand` applies the class's rule edits; `glossary_only` withholds them but lets an owner glossary entry change the token; `native` leaves the token to the
  engine, glossary included. A glossary entry on ordinary words applies whenever its engine scope matches.
- *Metadata lines are protected whole.* Edge direct uses the `Title:`/`Author:` values as metadata, so they are never edited; `#` markers are protected and heading text is
  normalized like body text.
- *Years.* The ambiguous band is 1000-2099 (the plan said 1100; `in 1066` needs the same cue logic). A cued year is classed YEAR even where both readings coincide (`since 2005`),
  so the YEAR mode governs every cued year. A year cue together with a count noun (`in 1500 cases`) is a conflict and is left unchanged.
- *Numbers that look like identifiers* (leading zero, more than 15 digits, a cue such as Room/Flight/No., or a street address) are left unchanged from 100 upward.
- *Clock markers are spoken `A M` / `P M`.* The plan's example wrote `p m`; a lower-case `a` risks being read as the article. Open for the A4 listening.
- *English detection is a line heuristic* (non-Latin script share, or more foreign than English function words); a line it rejects is protected, never edited (D14, D15).
- *Fail closed in the core.* A violated invariant raises `IntegrityError`; how a run reacts is decided where the core is wired (A3).
- *Versioning.* `RULESET_VERSION` = 1. A test pins a fingerprint of the version, every data table and the rule registry, so a data change cannot land without a bump; a code
  change to a rule still needs a deliberate bump and a Changelog line.
- *Package boundary.* The speech-package import guard now allow-lists the exact standard-library modules used and forbids randomness, clocks, network, processes and threads.

**Why.** Each choice keeps the plan's conservative policy (unchanged unless a positive cue exists) and keeps behaviour traceable and testable before anything is wired.

-- Decided under the owner's A2-A6 authorisation; implemented by Claude Code

---

## 2026-10-19 - Application source is an explicit registry, not discovery

**Decision.** `source_probe.APPLICATION_PACKAGES = ("shared", "tts", "mp3_tools")` is the only definition of production packages for guards; folders are never discovered from disk. A new production top-level folder requires a deliberate registry edit, enforced by a tracked-tree canary. **Why.** Discovery by `__init__.py` pulled untracked developer packages into FFmpeg, architecture and syntax guards. This supersedes the discovery clause in the entry below.

-- Decided by the owner's instruction; implemented by Claude Code

---

## 2026-10-20 - Plan 01B checkpoint A1: one structure loader, existing engine differences kept as options; intermediate Codex reviews deferred

**Decision.**
- *One loader, explicit options.* `tts/speech/document.py` owns decoding and the `Title:`/`Author:`/`#` rules. Engine differences are options, not forks: Qwen3 makes a heading a paragraph of
  its own (and drops an empty heading), Kokoro/Chatterbox keep heading text in line (an empty heading leaves an empty line), Edge folder takes the text untouched. Unifying any of these
  would change audio and remains the owner's decision ([D10], [D11]); A1 changes none.
- *The speech package is a pure-Python leaf.* Standard library only; it imports no engine and no UI module (pinned by a test). It is listed in the production-source allow-list on purpose.
- *Review cadence.* The owner explicitly deferred the independent Codex review of B1's final correction and of every intermediate checkpoint (A1 onward) to ONE consolidated pre-merge verification before v0.6.7 closes. Codex has NOT independently passed the final B1 correction; that evidence stays unresolved until the consolidated qualification.

-- Decided by the owner's instruction; implemented by Claude Code

---

## 2026-10-19 - Plan 01B corrective checkpoint: where a startup notice is shown, and what "application source" means to a guard

**Decision (Codex findings on B1).**
- *A notice travels with the launch, not with the check.* The only reliable GUI-visible place on a Windows launch is the launcher window, so `bootstrap.launch_gui`
  sets `ACT_STARTUP_NOTICE` in the child's environment and the launcher shows it once in its status bar and removes it. `main()` does not evaluate it, which keeps
  `--venv-check` and `--launch-only` from losing or duplicating it. It is a one-line status, never a modal; detection and presentation failures are swallowed.
- *Detection covers `.py` and `.json`.* A leftover application folder can hold data files only; `__pycache__` is ignored; counts are named per type.
- *Guards over production modules call `source_probe.application_python_files`.* That is `launcher.py` plus every `.py` under the application packages (any top-level
  folder with an `__init__.py` is a package), not `scripts/**/*.py`. Whole-tree scans that must be broad (layout, packaging, "this file exists nowhere") stay raw and are
  listed in `test_application_source_boundary.py`; adding a new raw walk fails that test until it is justified.

**Why.** After the lift to `scripts/`, a glob over `scripts/` also reads `verify.py` and untracked local helpers, so a guard's verdict depended on the machine. The old
notice also could not be seen on the launch path the owner actually uses.

-- Decided by the owner's instruction; implemented by Claude Code

---

## 2026-10-19 - Plan 01B working decisions; `scripts/` is the import root (checkpoints C0, A0, B1)

**Decision (owner working decisions D1-D15, recorded in `files/plans/ACT-v0.6.7-Plan-01B-Text-Pipeline-and-Script-Layout.md` section 0).**
- *Layout.* `scripts/Universal/{launcher.py,shared,tts,mp3_tools}` moved up to `scripts/`, which is now the import root; the `MacOS/` and
  `Windows/` placeholders were removed. The package names did not change, so no import statement changed. The deep MP3/M4B package split is
  deferred until after S5 (592 test references); navigation is by short README maps instead. A leftover `scripts/Universal` produces a
  warning only: the app never deletes it, and no ignored or untracked file was deleted to make the folder disappear.
- *Sequence.* C0, then A0 (characterization baselines of the five text routes, captured from the original code **before** anything moved),
  then B1; A1-A5 and S5 follow only after the owner's manual Windows launch and Codex's independent review of B1.
- *Baselines live under `files/tests/golden/speech/`.* `files/test-files/` is gitignored local-fixture space, so a tracked golden cannot live
  there. They are text, chunk and seed baselines (no audio, no network) and any later pure refactor must leave them byte-identical.
- *Test counts.* The pre-existing suite must show no regression and the new tests must pass; the two counts are recorded separately and the
  total is allowed to rise.
- *Chatterbox colon behaviour is temporary compatibility.* The structural-colon `punc_norm` patch and the 75 ms prose-colon pause stay
  untouched through B1 and A1-A5; checkpoint A6 defines the criteria (including unexpanded and protected colons and URLs) for retiring them.
- *A run freezes its speech-preparation settings by value* (an immutable run-scoped copy; a hash alone does not freeze anything), so Retry
  Failed cannot see an edited glossary. Shared normalization is the end state for every engine; per-engine modes are rollout scaffolding,
  and each exception needs evidence, a Decisions entry, a review checkpoint and independent review.
- *One pinned test was re-pinned on purpose.* `test_plan6_boundaries.PHASE6_PROMOTION_HASHES` pins the content of `test_m4b_numbering.py`; its
  single changed line is the path constant, so the digest was updated once with the old value recorded beside it.

**Why.** The relocation removes an extra directory level and three confusing folder names without touching behaviour; characterising the text
routes first lets the move and the later speech-pipeline work prove they changed no text path.

-- Decided by the owner's working decisions; implemented by Claude Code

---

## 2026-10-19 - CP6 build decisions: how the Qwen3 voices are installed, contained, locked and previewed

**Decision (engineering, inside the owner's Q1-Q8 rulings; independent Codex review after every slice).**
- *Install and repair are in-app only.* One dialog ("Install / repair Qwen3 voices...", shown beside a Qwen3 voice) serves first-time
  and existing users; `bootstrap.py` is unchanged and nothing downloads on launch. The sizes are on the buttons and again in a
  confirmation before anything is acquired. CustomVoice and Base install independently (or together); files already present and
  intact are reused, and the nine files the two models share are downloaded once.
- *Downloads are verified, bounded and contained.* The tracked manifest lists, per model, the 11 files the loader needs with size and
  SHA-256 at an immutable commit. File names are validated (no traversal, absolute paths, device names or aliases) and nothing beneath a
  model folder may be a link. A response is checked against the manifest (status, `Content-Range`, `Content-Length`, no content
  encoding), never written past the manifest size, and accepted only after its SHA-256 matches; an interrupted file resumes from its
  `.part`. The models root itself may be a link so the models can live on another drive. A leftover `.part` or temporary file that is a
  link, or that shares its bytes with another file, is removed and never written through, and a Cancel during a retry wait is honoured
  within half a second.
- *The environment is isolated and pinned to artifacts.* pip runs `--isolated --require-virtualenv --require-hashes --no-deps` against a
  requirements file whose 89 lines each pin one exact wheel by SHA-256 (taken from the evaluation's install report), with ambient `PIP_*`
  settings removed and TEMP/caches inside the repository tree. `.venv-qwen3` must be a real folder inside the repository: a link or
  junction is refused and never deleted through. CPython 3.12 only (the tested wheels are cp312).
- *Nothing can outlive a Cancel.* The worker and pip start suspended inside a Windows Job Object that kills every member (including the
  venv launcher's child) and, if that containment cannot be established, they are not run. After a kill there is a final deadline, so
  the conversion thread can never wait forever. A worker's `done` is believed only if it also exits with status 0.
- *Setup and conversion exclude each other machine-wide* with operating-system file locks (`setup.lock`, `inference.lock`): an install
  or repair needs both, a conversion holds `inference.lock`. A crash cannot leave a stale lock. One Qwen3 conversion per machine at a
  time, which also suits a GPU that holds a multi-gigabyte model.
- *Repair checks first.* "Check and repair" starts the engine (a repaired-away DLL leaves every record valid), hashes every installed file,
  shows what it found and what fixing it would download, and acts only on a yes, re-hashing nothing it has just proved good. The check
  itself holds both install locks (it starts the engine and reads every model file, so it may not overlap an install or a conversion), and
  a model whose files are all intact but whose verified record is missing, unreadable or for another version (what a cancel between the
  record's removal and its rewrite leaves) is found and marked again with nothing to download.
- *Previews.* `files/voice-previews/previews.json` is the per-voice rights/status record. Eleven previews exist (nine Kokoro, Qwen3 Aiden
  and Ryan) because their licenses are documented and no third-party voice is involved; seventeen (Edge, Chatterbox, the six Qwen3
  clones) are blocked pending the owner's rights decisions. The set is never reported complete while any row is blocked. A preview
  tool refuses to generate for a voice whose rights are not `confirmed`; availability, the counts and the README are derived from rights
  and preview status together (a manifest that contradicts the rule is refused, never rendered); a new take is validated and its hash
  computed before it replaces the published file, and a published preview, its record and the README change together or are all rolled
  back. The recorded basis states only what the pinned model cards say (Apache-2.0 for the weights) and that the training-data provenance
  is the model author's claim. *(The `confirmed`-only generation rule described here is superseded by the 2026-10-20 owner decision; Kokoro/Qwen3-preset evidence is unchanged.)*
- *Trust boundary for link guards.* Anything that can write into the repository folder can already replace the scripts, so the
  link/junction/hard-link guards defend against accidental or content-driven redirection of the app's own state, locks, job text, caches,
  scratch files and downloaded model files, not against an attacker who can edit code. `files/runtime-data` and the models folder may
  themselves be links (moving data to another drive is legitimate); the Qwen3 runtime folder, everything the app creates beneath it,
  `.venv-qwen3` and anything inside a model folder may not. Four Codex follow-up rounds each found the same class one folder deeper; it
  is now closed by class (`ensure_runtime_dir`, `remove_entry`, exclusive temp-file + `os.replace`), not by path.
- *The install dialog imports none of the Plan 3 job foundation.* `test_plan3_boundaries` pins the adopters at exactly twenty modules, so
  `tts/qwen3_install_ui.py` receives its confirmation and style functions from the adopting TTS panel instead of importing `shared.job_ui`.
- *Left deliberately unchanged:* the data-cleanup tool keeps its four assets (only the wording of "Downloaded voice models" now says the
  Qwen3 models must be installed again); the Qwen3 environment is not a fifth asset, so freeing its ~5 GB is a manual folder delete
  (stated in the dialog). Adding it would be an owner decision.

**Why.** The owner asked for verified cancellation, failure recovery and output preservation, honest hardware disclosure, and no
automatic downloads, and Codex's reviews of S1-S3 found real gaps in each area (path traversal, ambient pip configuration, stale locks,
repair without confirmation, an uncontained fallback, unbounded downloads); each is fixed and has a regression test that was
mutation-checked.

-- Decided by maintainer's rulings, implemented by Claude Code

---

## 2026-10-19 - CP6: Qwen3-TTS production architecture approved (owner rulings Q1-Q8)

**Decision (owner, explicit).**
- **Q1** A second isolated `.venv-qwen3` and one Qwen worker subprocess per source file. The root `.venv`, production dependencies and Chatterbox are unchanged.
- **Q2** CustomVoice (Aiden, Ryan) and Base (the six clones) install independently, with an "Install Both" choice, in one shared environment. Download/install sizes are shown first, valid cached assets are reused, and nothing downloads on ordinary launch.
- **Q3** CPU fallback on Windows without an NVIDIA GPU, with hardware and speed stated plainly. The measured 2.15x real time applies only to the tested Ryzen 7 9800X3D. No silent downgrade, quantization or alternate model.
- **Q4** Windows first. On macOS the existing engines keep working and the Qwen3 voices read "not yet available"; no macOS Qwen3 claim without a Mac test.
- **Q5** NOT approved for public redistribution: the six verified transcripts, new cloned-voice previews and (pending a rights audit) the original reference recordings are not committed. The transcript interface is built with synthetic fixtures and accepts development-only local files; real clone synthesis still needs the owner's `verified.json` approval; there is no transcript-free cloning; the clones stay blocked for public-release qualification. **[Superseded for preview audio by the owner's publication decision of 2026-10-20 (the entry at the top of this log). The history is kept as written.]**
- **Q6** Qwen follows ACT's existing local-engine narration policy (the voice preset's paragraph pause between chunks, its end pause), not the evaluation's fixed pauses; source text and chunk/paragraph boundaries are preserved; one final MP3 encode.
- **Q7** About 1.4-1.9x real time is acceptable for the first integration; speed is disclosed as machine-dependent and no fixed performance is promised.
- **Q8** The permanent 10-second previews stay in scope but are generated or published only per voice with confirmed output rights and source permissions. Edge and cloned-voice previews are not published while rights are unresolved, a per-voice rights/status manifest is kept, and the 28-preview deliverable is not declared complete while any preview is blocked. **[Superseded for preview audio by the owner's publication decision of 2026-10-20 (the entry at the top of this log). The history is kept as written.]**

**Build choices made under these rulings.**
- *In-app install/repair only; `bootstrap.py` is not changed.* One "Install / repair Qwen3 voices" dialog serves first-time and existing users. This drops the draft's bootstrap slice (D8), so no new setup behaviour needs separate approval and the every-launch fast path never touches Qwen3.
- *Transcripts are read from a local, untracked file* (`files/runtime-data/qwen3/transcripts.json`, or the path in `ACT_QWEN3_TRANSCRIPTS`) in the same shape as the evaluation's `verified.json`, and are accepted only when `approved` is the literal `true` and the entry is bound to the reference recording's SHA-256. A tracked transcript file must not exist (a test enforces it).
- *One tested wheel set* (the cu128 build the evaluation and the CPU measurement used) is installed on every Windows machine. A smaller CPU-only wheel is a later optimisation because the CPU speed was measured with the cu128 build.
- *No automatic device fallback after a failure.* The worker uses the GPU when torch reports one and the CPU otherwise; a GPU that is present but fails (for example out of memory) fails that file with a clear message instead of silently re-running on the CPU.
- *Cancellation is bounded:* a flag file asked for between chunks, then the whole process tree is killed after a short grace period (the Windows venv `python.exe` is a launcher that starts the real interpreter as a child, so killing only the launcher would leave inference running).

-- Decided by maintainer, recorded by Claude Code

---

## 2026-10-19 - Final ACT voice roster: Decision B (28 voices)

**Decision (owner, explicit).** Retain Chatterbox and add selected Qwen3 voices. Final target inventory: Edge 5 (unchanged), Kokoro 9
(the five existing plus `am_fenrir`, `am_puck`, `am_onyx`, `bm_daniel`), Chatterbox 6 (unchanged: no removal, rename, archival or
replacement), Qwen3-TTS 8 (CustomVoice Aiden and Ryan; the six Base clones Female 1, Female 2, Male 1, Male 2, Male 3, Male 4) = **28**.
Excluded from production: Dylan, Eric, Ono_Anna, Serena, Sohee, Uncle_Fu, Vivian (their evaluation evidence stays).

**Labels and identity.** `Qwen3 - Aiden`, `Qwen3 - Ryan`, `Qwen3 - Female 1` ... `Qwen3 - Male 4`; a separate Qwen3 GUI group; distinct internal ids and
backend dispatch (never keyed on display labels); a Qwen clone is independent of its Chatterbox counterpart; the default voice, existing identities, saved
settings and ordering are preserved.

**Why / consequences.** The sustained Qwen evaluation target changes from four recordings (Aiden, Dylan, a female preset, a clone) to eight
(Aiden, Ryan and the six clones) on the existing frozen long corpus; the earlier selection matrix is superseded in the plan. This approves the
roster only: transcript approval, audio validation, regression gates and the bounded Qwen3 production addendum (new runtime, bootstrap and
platform decisions need the owner's approval) all still apply, and no Chatterbox retirement is authorized. Permanent 10-second previews cover the
final 28 voices only, subject to a per-voice redistribution check. *(Preview audio: see the 2026-10-20 owner publication decision.)*

-- Decided by maintainer, recorded by Claude Code

---

## 2026-10-18 - Plan 01 evaluation: isolated Qwen3-TTS runtime and dev-only tooling

**Decision.** The Qwen3-TTS / Kokoro / Chatterbox voice evaluation runs from `files/dev-tools/` (never shipped) and an
ignored isolated venv at `files/dev-work/qwen3-eval/.venv/`. Production `scripts/requirements.txt`, the root `.venv`,
the voice registry, the GUI and `scripts/Universal/shared/release.py` are untouched; the only tracked production edit is
the opt-in `--qwen-eval` flag group in `generate_voice_samples.py`. The evaluation stack is pinned in
`files/dev-tools/qwen_eval_constraints.txt` (89 exact pins: `qwen-tts==0.1.1`, `transformers==4.57.3`,
`accelerate==1.12.0`, `torch`/`torchaudio` `2.10.0+cu128`), models are pinned to immutable Hugging Face revisions in
`files/dev-tools/qwen_eval_assets.py`, and synthesis loads complete local snapshot directories with Hugging Face offline
mode on.

**Why.** Qwen needs a Transformers pin that conflicts with the production one, and the root torch is a CPU build that
cannot use the RTX 5070. An isolated interpreter keeps the working product intact while giving Qwen a real GPU
(`torch 2.10.0+cu128` was proven on sm_120 with bf16 matmul and SDPA before any model was downloaded). Gradio is installed
only because `qwen-tts` declares it; no server is run.

**Choices a future agent might undo, and why they stand.**

- *Join profile.* 50 ms of silence after **every** chunk plus 3,000 ms at the end, exactly as `chatterbox_file_to_mp3`
  and `kokoro_file_to_mp3` do, so Qwen files are comparable with the baselines. The plan's wording ("between chunks")
  differs from the engines by one trailing 50 ms; the engines were followed and the manifest records every inserted sample.
- *Audible duration* excludes inserted silence (engine-configured pauses are read from the engine's own signature).
  The 45-90 s / 8-12 min targets apply to this figure.
- *Evaluation passages* live in `qwen_eval_corpus.py`, not in `quality_corpus.py`, so the production corpus identity
  (`407fa95d7c524c64`) is unchanged and a test pins it. They were revised once, globally, after pilot timing (short
  172 -> 154 words, long 1,428 -> 1,528 words) and are frozen byte-exact per run; a changed passage requires a new run.
- *Chunk ceiling 600 characters* for Qwen only (pilot: peak VRAM 4.7 GB, the longest chunk used <= 6% of the generation cap); Chatterbox keeps
  its 300-character ceiling and Kokoro its own chunker.
- *Transcript gate.* A reference transcript conditions a clone only when `verified.json` holds `"approved": true` for it
  (a literal boolean); Whisper drafts never count, `x_vector_only_mode` is never used, and the transcript hash is part of
  the resume identity, so editing an approved transcript invalidates the clone.
- *Seeds* are `sha256(base|row|chunk|attempt)` per chunk; Chatterbox and Kokoro stay unseeded because that is production.
- *Resume* needs BOTH the identity (text, plan, profile, model revision, package pins, reference/transcript hashes and a
  deliberate `PIPELINE_REVISION`, not whole source files, so reporting/ASR edits never invalidate finished work) AND a
  match between what the row recorded about how it was made (installed package versions, model revision, Kokoro voice-asset
  hash, device build, reference and transcript hashes) and the present state. There is deliberately no "rebase"
  operation: it could legitimise audio made under a different profile.
- *Nothing complete is touched by accident.* A complete recording whose evidence no longer matches is reported STALE and
  kept; `--eval-rerun-stale` regenerates it, and `--eval-dry-run` shows every row's reuse/block/run decision without
  starting a worker. A temporarily missing prerequisite never demotes a complete result. Retired attempts have their
  files moved to `attempts/<row>/attempt-NN/`, and `Manifest.restore_attempt` can bring them back; every worker call keeps
  its own timestamped job file and log. Archive folders are numbered from the folders that exist, never from the list
  length. Retiring or restoring an attempt is ONE transaction (the file moves and the manifest save succeed or fail
  together; a restore is fully preflighted first; a rollback that cannot complete says which files it could not return). A row that is retired while blocked or failed keeps its
  diagnostics archived, and a recording that was received but failed to encode stays tracked. (Learned the hard way on 2026-10-18: the first version of the runtime check
  compared `torch` package metadata `2.6.0` with the runtime `2.6.0+cpu`, so one stage run retired and began regenerating
  12 good recordings. They were restored byte-identically and the spurious takes stay archived; the stale-guard and
  dry-run exist so that cannot recur silently.)
- *Transcript approval is bound to the reference recording's SHA-256* (`wav_sha256` in `verified.json`); an approval made
  for a different recording is not used.
- *Run ids* are one plain filename component and are checked to resolve inside `files/dev-work/qwen3-eval/runs/`.
- *ASR read-back* (`--qwen-eval asr-check`) is advisory: it can flag gross omissions, never approve or overrule listening.
- *Codex independent review* ran three times on 2026-10-18 (after one usage-limit delay): 10 major + 1 minor findings
  against `2ad8272`, 8 major + 2 minor against `a80825e`, and 5 major + 3 minor against `842a524`. Every finding was
  verified against the code before fixing, all were real, and all were fixed with regression tests. The later rounds
  are failure-injection scenarios (a save that fails after files moved, a restore whose archived file vanished), which is
  why retire/restore became a transaction. A further confirmation pass is the closeout review's job; a Claude
  self-review is never labelled independent.

Nothing here selects a voice or authorises integration: the owner's listening decisions (CP4/CP6) are separate gates.

-- Decided by maintainer (Plan 01 and its 2026-10-18 CP1 rulings), implemented by Claude Code

---

**Out-of-order entries.** The eight entries below (2026-10-27, 2026-10-30 and six of 2026-11-09) were appended to the
original file after its oldest entry (2026-07-06). They belong to this era, so they are kept here, unchanged and in their
original order, after the rest of it.

---

## 2026-10-27 — Owner-approved Option B: base preparation is separate from optional acquisition

**Decision:** Early **Continue** prepares the base ACT application only. It does
not authorize any optional model acquisition. Python stage-0 installation retains
its own separate explicit consent.

After verified main CPython 3.12 is available, show the complete exact v3 Plan,
including full history, identities, acquisition terms, reuse, disk/headroom and
explicit repair/rebuild effects. Require genuine trusted GUI presentation
acknowledgment, independently retain the immutable original bytes, then perform
strict original-bound exchange readback. None of selection, early Continue,
worker success, presentation acknowledgment or original retention is consent.
Only a later live **Install Selected Components** (repair-aware when needed)
affirmative action may authorize exact v3 issuance, subject to fresh validation.

Keep Kokoro checked and Chatterbox, Qwen3 CustomVoice and Qwen3 Cloned Voices/Base
unchecked. Estimates remain estimates; unknown base network costs remain unknown.
Count shared Qwen bytes once and distinguish network, reuse, disk and headroom.
All skipped/no eligible mutation means no optional consent or acquisition; a
zero-network repair/local copy is still a mutation requiring disclosure.
Skip/Cancel/close/failure is safe, with no automatic retry, deferred install or
surprise download. A future in-app Skip/Cancel abandons the frozen narration
intent and requires another Create. Fixed resource limits refuse losslessly;
never omit history, relax caps or imply qualified availability.

**Supersession:** This append-only decision changes only Revision 2 section 5.4's
early checkbox/setup-action acquisition-consent interpretation and older P05
commentary treating pre-main estimates as optional acquisition consent. Historical
entries and all other approved choices and security/release gates remain intact.
The Stage 4D-2F presentation-adapter ordering is approved. M1 authorizes only
controlled read-only qualification; consent issuance, production acquisition,
actual first-run/run_job integration, P06 and release activation remain blocked.
Application identity remains 0.6.6.

— Approved by the owner on 2026-10-27; recorded during consolidated M1 qualification.

---

## 2026-10-30 — Release installer: Option B through the existing consented v2 pipeline

**Decision:** The v0.7.0 first-run wizard and the TTS panel's Install & Continue install the four optional
components through the existing optional-setup protocol (contained setup worker in `.venv`, lifecycle, consent
bound to the acquisition fingerprint of the worker's own fresh plan, spent once) and `RealAcquirer`, now the
production default. Option B's user-facing order is kept: early **Begin Setup** builds the base only; after the
base exists a read-only plan is shown in full; only a live click on **Install Selected Components** creates the
consent; Skip/Cancel/close never download, keep what works and never retry by themselves.

The three P05B Stage 3 consent-scope escapes are closed in the acquirer itself: every response passes a byte
budget fixed by the consent (known download plus a stated ceiling for units shown as unknown), refused before the
body is read when its length exceeds what remains; the Qwen3 installer may touch the engine only when the consent
includes the `qwen3-engine` unit. The engine's packages are the reviewed manifest's 89 exact wheels (sox: the
accepted derivative at supply commit `b7e1b1ae`), each fetched by size and SHA-256 through that budgeted opener and
installed offline (`--no-index --require-hashes --no-deps --only-binary=:all:` under the offline bootstrap), so pip
no longer has index access. The bootstrap's unpinned pre-download and warm-up routes are removed.

**Why:** The owner's 2026-10-30 directive makes a working, user-installable application the priority and forbids a
second installation framework. The v3 presentation-acknowledgment/retention/readback machinery (M1/M2) remains in
the tree, qualified and unused by production; it is not required for the consent to be exact, because the worker
refuses any plan whose terms differ from the confirmed ones.

— Directed by the owner on 2026-10-30; implemented by Claude Code.

---

## 2026-11-09 — Private staging lives exactly as long as a Retry Failed can reach it (v0.7.2 Phase 6, batch A)

**Decision:** The MP3 Tool, M4B Maker and M4B Metadata Editor keep a Book's private staging only while a Retry Failed
can still re-run that Book. Each attempt, before its terminal event, removes the staging of every Book its settled result
cannot retry (a Cancel, a non-retryable failure, an internal fault and a full success keep nothing). The rest goes when the
panel lets the run go: Clear All Imports, a new run of the same tool, or closing the tool. An attempt still running at that
moment keeps nothing when it ends; a lock (injected into the Tk-free runners by their panels) and an `abandoned` mark keep
the two releases from overlapping. Removal is bounded to the plan's own Book folders, unlinks a link (a junction included)
as a link and never follows it, and never touches published output. The Maker's custom-folder staging moved from a loose
`tempfile.mkdtemp("act-m4b-build-")` folder into an entry of `tts/work_area.py` (new kind `maker`), so it has an owner
(process id and creation time) and a later custom build recovers what a killed Maker left; a loose `act-m4b-build-*`
folder is never touched by name. The Converter removes a failed or cancelled split book's empty folders (rmdir only,
never the run folder, never through a link).

**Why:** ACT72-019/031/034/037 and ACT72-029: staging outlived every chance of being used, and custom Maker staging had
no owner at all. The rule follows the existing Plan 3 contract (Retry Failed is offered only after a run completed with a
retryable failure) instead of inventing a second one.

**Crash boundary (deliberate):** a killed process can leave a standard run's `.work` in that run folder (private, never
published). Nothing sweeps the output folder for it: there is no ownership record there, and sweeping by name, age or
process id is forbidden by the plan.

— Implemented by Claude Code under the owner's "Complete Phase 6" authority, 2026-11-09.

---

## 2026-11-09 — A closed window's Tk objects are finished on the main thread; a setup stop ends pip's tree by its own id (v0.7.2 Phase 6, batch B)

**Decision 1 (ACT72-017):** once the main loop has ended, `launcher.main` calls `_release_tk_objects(root)` on the main
thread: a collection there frees what is already garbage, then every Tk variable, image and font of that root still alive
is deleted from Tcl exactly as its `__del__` would and marked done, so a later `__del__` on any thread does nothing. The root
stays held by `_ROOT`.

**Why not simply clear `Variable._tk`:** the Phase 2 note (`tk_closed_root` in memory, Phase 2 closeout) found that disarming
variables made the forced arm crash sooner, because the traceback of the ignored exception had been what kept the root alive.
Since Phase 3 the root is held deliberately (`_ROOT`), so that accident no longer matters; and this does not merely disarm:
it completes the deletion on the right thread and leaves nothing for a worker. Measured natively: Cover 17.4 s and TTS 22.9 s
of ignored `main thread is not in main loop` errors before, 0.016–0.032 s and none after; the crash control still crashes
when the root is released.

**Decision 2 (ACT72-039):** the first-run window asks "Stop setup?" when closed during the base install. Yes sets a stop request
that ends the registered pip and everything it started with `taskkill /PID <pip> /T /F` (other platforms: its own process
group), starts no later step, and closes the window only after the worker has reported (exit 1, incomplete).

**Why not the Job Object of `tts.qwen3_process`:** `test_the_app_environment_repair_can_never_reach_the_qwen3_installer` holds
`bootstrap.py` to importing nothing from `tts`, so that an environment repair can never reach an engine installer. That
guard stays as it is. `taskkill /T` from our own child's process id is `qwen3_process`'s own fallback route; the id cannot be
reused while this process holds the child's unreaped handle. Limitation: if the setup process itself is killed (not closed),
pip is not ended with it, as before.

— Implemented by Claude Code under the owner's "Complete Phase 6" authority, 2026-11-09.

---

## 2026-11-09 — Messages say what happened; values are judged as typed (v0.7.2 Phase 6, batch C)

**Decision 1 (ACT72-004):** the 2026-11-05 decision stands: no per-item CANCELLED status; a file or Book stopped by Cancel stays
`NOT_ATTEMPTED`, and Retry Failed never offers it. Only the words change: the multi-Book panels show the Book a Cancel stopped
part-way as "Cancelled" (each runner records `stopped_book_id`; the MP3 panel reads the Books its projection saw begin) and count
it as "stopped by Cancel"; TTS counts finished, stopped and not-started files in its closing line.

**Decision 2 (ACT72-021):** the 160 kbit/s ceiling of a 24 kHz MP3 is told, not worked around. Resampling to 44.1 or 48 kHz to
honour 192k/320k would change every engine's output for no audible gain on speech; the options stay as they are and the Summary
says what the files get.

**Decision 3 (ACT72-025):** a typed Cover size must lie in the size box's own range, 256 to 4096. Smaller sizes were reachable
only by typing; no product path or journey used them, and the panel tests that did now use 256.

— Implemented by Claude Code under the owner's "Complete Phase 6" authority, 2026-11-09.

---

## 2026-11-09 — The owned work area is shared; Enter presses the focused button (v0.7.2 Phase 6, batch D)

**Decision 1:** `work_area` moves from `scripts/tts/` to `scripts/shared/`. Batch A made the M4B Maker stage its custom builds in
it, which broke the standing rule that `m4b`, `mp3` and `artwork` never import `tts`
(`test_tts_output_names::test_no_other_tool_reaches_the_tts_naming_policy`, missed by batch A's targeted runs). The guard is kept
as it is; the module, now used by two tools, lives where shared things live. Names, behaviour and the `%TEMP%\act-tts` folder are
unchanged, so an interrupted run of an earlier build is still recovered.

**Decision 2 (ACT72-060):** in Cover Image's replacement question, Return and keypad Enter press the button that holds the
keyboard, as on any Windows dialog. Cancel holds it when the question opens, so Enter cancels; a person who moves to Replace
and presses Enter replaces. Tk binds Space but not Return on a ttk button, so before this Enter did nothing, and the test that
claimed otherwise called Cancel's handler directly.

**Decision 3 (ACT72-056):** the native close-during-scan journey paces the scan through the launcher adapter's own hook
(`slow_scan_seconds`: a sleep at each Cancel checkpoint) so that the close lands while the walk is under way. Only the pace
changes; the scan, its Cancel and the shutdown are production's.

— Implemented by Claude Code under the owner's "Complete Phase 6" authority, 2026-11-09.

---

## 2026-11-09 — The TTS skip box says what it does; unreferenced helpers wait for the owner (v0.7.2 Phase 6, batch E)

**Decision 1 (ACT72-046):** wording only, as the owner asked, and no cross-run resume. The box reads "Skip MP3s already in this
run". A first attempt always starts in a newly reserved folder, so in the app it has nothing to skip; it never claimed less than
that, but "Resume" suggested continuing an earlier run. Behaviour and default are unchanged, and so is the command line's
`--resume`. Removing the box from the app would be a larger change to what a person sees, and was not asked for.

**Decision 2 (ACT72-030, deferred):** the eleven helpers with no production caller stay for now. The four on the Converter side are
each exercised by at most one test; the MP3 Tool's six are pinned by six test modules (`test_mp3_write_id3`,
`test_mp3_tool_ui`, `test_mp3_duration_authority`, `test_mp3_concat_paths`, `test_mp3_hardening`, `test_tool_output_integration`)
as the proven FFmpeg helpers the Phase 7 redesign re-exported. Proposal for the owner: one cleanup slice that removes all eleven and
the tests that exercise only them, keeping `write_concat_listfile`, `ffmpeg_escape_listfile_path`, `run_ff`, `seconds_to_hms` and
`ffprobe_duration_seconds`, which the app does call. ACT72-030 stays open at Phase 6 until then.

**Decision 3:** the six-tool consistency matrix (`files/dev-work/feature-map/consistency-matrix.md`) records five differences
and changes none of them: the Converter corrects typed values instead of refusing them; FFmpeg readiness is checked three ways;
Open Output Folder is in three tools of six; the Converter and Cover Image have no per-attempt divider; TTS remembers no folder.
Each is a change to what a person sees, so each is the owner's to approve.

— Implemented by Claude Code under the owner's "Complete Phase 6" authority, 2026-11-09.

---

## 2026-11-09 — What the final full gate on c2244ae found (v0.7.2 Phase 6, final candidate)

The one full Windows gate on `c2244ae` (`2026-11-09_150101_full_5f93`) failed on four checks: 14,020 tests passed, 2 failed,
and coverage named 2 test ids that pytest does not collect. None changes what a person sees; each is a standing check that
my direct runs did not include.

**Decision 1:** `launcher._release_tk_objects` (batch B, ACT72-017) is renamed `_finish_tk_objects`.
`test_release_packaging::test_building_is_not_part_of_application_startup` forbids the word "release" anywhere in the
launcher, so that building a release is never part of starting the app. The check is unchanged; the name now says what
the helper does.

**Decision 2:** `test_cleanup_worker::test_deletion_of_a_catalog_target_is_reachable_only_from_the_coordinator` names
`work_area.py` beside `cleanup_worker.py` for `os.rmdir`, and beside the four named files for `rmtree`. Batch D moved
`work_area.py` from `tts/` (outside the check) into `shared/`. It removes only the private working folders this process
made, its own empty workspace, and a workspace whose recorded owner has provably ended (Phase 6B). It is held to the same
two assertions as the others (never `authorized_target`, never `compiled_target`), and the check now applies them to it
even if it stops using `rmtree`. Any other shared module that calls `os.rmdir` still fails. This adds one named exception
to a guard and removes no check; the file is checked more than it was before the move. Planted defects prove both halves:
an `os.rmdir` in another shared module, and a catalog name in `work_area.py`, each fail the check.

**Decision 3:** the MP3 Tool's refused-plan test has ASCII parameter ids (pytest writes the arrow in "Combine MP3s → One
MP3" as an escape sequence, so coverage's id never matched), and `ACT.MAKER.BUILD` names the three parametrized ids of the
Maker's refusal test instead of its bare name. All 1,606 behaviour ids in coverage are collected; the same check names the
dead ids against the committed coverage.

— Implemented by Claude Code under the owner's "Complete Phase 6" authority, 2026-11-09.
