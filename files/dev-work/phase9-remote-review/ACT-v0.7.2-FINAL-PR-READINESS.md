# ACT v0.7.2 — Final PR readiness

**Verdict: BLOCKED. The PR stays a draft.** Prepared 2026-11-12 by Claude Code on HOME-PC (Windows 11 build
26300.9974).

The one authorized full Windows gate **FAILED** on the tested candidate `c4a9853`: 3 of 15,034 tests failed, all of them
structural tests left stale by Phase 9 changes. The test-only correction `5978e88` passes those tests, their negative
controls and a focused gate, but **no full gate has run on it**. Another full gate needs the owner's authorization. Both
qualifications that needed current-source evidence passed.

No merge, tag, release or archive publication was performed. The owner merges manually.

Run folders named below are in the ignored `files/dev-work/verification-gate/outputs/` on HOME-PC. They are local
evidence, not on GitHub, and the owner may delete them in a deliberate cleanup (plan section 13.4).

## 1. Executive verdict

| Area | State |
|---|---|
| Independent Codex closure of R9-01 to R9-04 | **PASS**, focused (section 4); the final report is published |
| Full routine Windows gate on the current source | **FAIL** on `c4a9853`; **NOT RUN** on `5978e88` |
| `m4b-scaling` (incl. the T5 census on real FFmpeg) | **PASS** on `c4a9853` |
| `edge-low-memory` | **PASS** on `c4a9853` |
| `optional-engines`, `fresh-windows` | **CARRIED FORWARD** from `3aa421a` (section 3.2) |
| Package audit | **PASS** on `5978e88` |
| Owner decisions | Three (section 7) |

What is missing before a merge recommendation: one full Windows gate PASS on the corrected candidate. Section 8 lists it
with the owner decisions that go with it.

## 2. Git identities

| Item | SHA |
|---|---|
| `master` base (= `origin/master` and the merge-base; the branch is 0 behind) | `204c33bbd2d11db8a0848b261a5cb567a9240d74` |
| Tested candidate: the full gate, `m4b-scaling`, `edge-low-memory` | `c4a9853a9fadca77320e576c618d14395dd2191c` |
| Corrected candidate: tests only; focused gate and package audit | `5978e88f8c62f7f1c1c31dc0ed0a663ddfece5c0` |
| Last application change (`scripts/` byte-identical from here to the reporting commit) | `a00f0a2b73068dae33b06fb1ae95083cc4251b4b` |
| Last Codex report commit (published this session, unchanged) | `11fa57428eef79b4ccb1002aa6acc901b5d3b0c9` |
| Final reporting commit | the commit that adds this report; its SHA is in the PR (a commit cannot name itself) |

What each step changed:

- `11fa574` to `c4a9853`: the issue ledger (`coverage.json`) and the TTS feature map.
- `c4a9853` to `5978e88`: three test modules (section 3.3).
- `5978e88` to the reporting commit: Markdown only, namely the four canonical documents in `md-instructions/` and this
  file.

**How the gate reads these identities** (`--status --require-current`):

- On `5978e88`, every run made on `c4a9853` reads `stale` because the test digest moved.
- On the reporting commit, the `5978e88` focused run reads `stale` as well. `md-instructions/` is in the "docs" class,
  which carries forward under plan section 13.3, but this report's folder is in "other", which never carries.

None of this is hidden. The application bytes, and both qualification scenarios' own code digests (scenario code plus
`scripts/`), are equal on all three commits: `m4b-scaling` `60219fb14de2513b…`, `edge-low-memory` `dd8a4d5c14e358fd…`.

## 3. Test and qualification matrix

| Qualification | Result | Run (`outputs/`) | Source and read-back |
|---|---|---|---|
| Full routine Windows gate | **FAIL** (details below this table) | `2026-11-12_135000_full_85b2` | `c4a9853`; FAIL, `exact` |
| Focused gate on the correction | **PASS**: 922 executed, 921 passed, 1 policy skip; coverage-inventory PASS | `2026-11-12_153553_focused_531d` | `5978e88`; PASS, `exact` |
| `m4b-scaling` (T1–T8, T1b) | **PASS**: 79/79 checks, 207 runs, 8,223 s | `2026-11-12_112630_qualification_1476` | `c4a9853`; PASS, `exact` |
| `edge-low-memory` | **PASS**: 61/61 checks, 6 runs, 307 s | `2026-11-12_134404_qualification_a6dd` | `c4a9853`; PASS, `exact` |
| `optional-engines` | **CARRIED FORWARD**: PASS 76/76, 6 runs | `2026-11-12_030349_qualification_f77a` | `3aa421a`; mechanically `stale`, relevant inputs unchanged (section 3.2) |
| `fresh-windows` | **CARRIED FORWARD**: PASS 43/43, 11 runs | `2026-11-12_025238_qualification_25cd` | `3aa421a`; mechanically `stale`, relevant inputs unchanged; package re-audited (section 6) |
| Full gate on `5978e88` | **NOT RUN** (needs owner authorization) | — | — |
| Windows 10, another computer, a clean Windows installation, display scaling other than 100 %, macOS, Linux | **NOT RUN** (unavailable or not authorized) | — | — |

The full gate's FAIL in detail: 6,204 s; 15,034 expected, collected and executed; 14,966 passed (14,434 ordinary, plus
457 and 75 in the two guarded groups); **3 failed**; 65 skips, each named by the policy; 56/56 native journeys; coverage
262/262; every other check PASS.

### 3.1 Freshness assessment (plan section 13.3)

| Qualification | Existing evidence (`3aa421a`) | Changed relevant code since | Current-source evidence required | Decision |
|---|---|---|---|---|
| Full gate | PASS `2026-11-12_050536_full_c132` | 5 application files, 8 test modules, `scaling/staging.py`, `coverage.json`, feature map | Yes | C: ran once on `c4a9853`, FAIL |
| `m4b-scaling` | PASS `..._002934_qualification_2cd6` | Converter Cancel/commit order (`m4b_converter.py`), `output_paths.publish_new`, the T5 census (`scaling/staging.py`) | Yes. No narrower route exists: `qualify.py` refuses `--rehearse` outside `--smoke`, and `verification.json` requires 79 checks over 207 runs | C: ran once, PASS |
| `edge-low-memory` | PASS `..._031059_qualification_feb6` | `tts/pdf_extractor.py`: its mixed folder narrates two PDFs | Yes | C: ran once, PASS |
| `optional-engines` | PASS `..._030349_qualification_f77a` | None on its path: no PDF, no MP3 Tool or M4B code, TTS publication unchanged | No | A: carried forward |
| `fresh-windows` | PASS `..._025238_qualification_25cd` | No setup, bootstrap, launcher, requirements or packager change; five `.py` members of the package differ | Bounded package audit only | A: carried forward, package re-audited |
| Other platforms and configurations | none | — | Not available or not authorized | D |

### 3.2 Why the carried-forward evidence still describes this source

`git diff 3aa421a c4a9853 -- scripts` changes five files: `tts/pdf_extractor.py`, `mp3/mp3_plan.py`,
`m4b/m4b_staging.py`, `m4b/converter/m4b_converter.py`, and `shared/output_paths.py` (a new `move_without_replacing`,
with `publish_new` routed through it).

- `optional-engines` synthesizes plain text with the installed local engines and publishes through
  `tts/publication.py`, which calls neither changed function.
- `fresh-windows` packages, extracts, sets up, launches and repairs. No setup, bootstrap, launcher, requirements,
  `Setup_and_Run` or packager file changed.

The gate's own reader calls both records `stale`, because their code digest covers all of `scripts/`; that is stated
here, not hidden. Accepting this carry-forward is part of owner checklist item 3.

### 3.3 The full gate's three failures and the correction

None of the three failures is in application behaviour. All were found only because the full gate runs every test.

1. **`test_m4b_converter_jobs.py::test_the_worker_names_no_widget_and_holds_no_estimator`** and
2. **`test_m4b_retry.py::test_the_retry_worker_reads_no_widget`**: both allowed the Converter worker `_run_conversion`
   only `self._cancel_event` and `self._log_q`.
   - The R9-04 repair in `a943a26` made the worker also read `self._cancel_decision`. That is the `threading.Lock`
     (`m4b_converter.py:456`) its `authorize_publication` holds while it reads the latch and asks the controller
     (`:1839`). It is a threading primitive, not a widget or Tk variable, so there is no thread-safety defect.
   - The guards were simply not updated, and the targeted runs of `a943a26` did not select them.
3. **`test_verification_gate_contract.py::test_no_active_caller_depends_on_the_retired_gate_path`**: flagged two Phase 9
   review reports that say the retired gate path was *not run*. One is Codex's `PHASE9-CODEX-FOCUSED-CLOSURE.md`, one is
   mine, `PHASE9-CLAUDE-FINAL-TARGETED-FIX.md`. An independent report is never edited afterwards.

**Correction `5978e88` (three test files, no application, gate or policy change):**

- The two guards now allow `_cancel_decision`.
- The jobs guard also pins that the panel only ever assigns `threading.Lock()` to it.
- Top-level Markdown in `files/dev-work/phase9-remote-review/` now counts as history, like `files/plans/`. A new test,
  `test_only_history_and_the_absence_tests_may_name_the_retired_gate_path`, pins that exemption exactly.

**How it was checked:**

- The four tests pass.
- Seven controls run the real test functions against planted defects (`outputs/2026-11-12_release_9c3d/fix-controls/`).
  - A widget read inside the worker and a fourth attribute fail both guards.
  - A Tk variable for the lock and a rebinding of it fail the new pin.
  - An exemption widened to the whole folder fails the new test.
  - The unmodified source and the committed helper pass.
- Focused gate `2026-11-12_153553_focused_531d` covers the three modules and the nine modules that read test files
  (`test_application_source_boundary`, `test_verification_coverage`, `test_repository_contract`,
  `test_release_packaging` and others): PASS.

### 3.4 Other runs of this session (recorded, not evidence)

- **`outputs/2026-11-12_release_9c3d/smoke`:** `qualify.py --smoke --rehearse resources` before the scenario. Verdict
  SMOKE, which is never a PASS, with 0 failing checks; T5 read before 301 removals and 100 renames on the 100-chapter
  book.
- **`2026-11-12_134932_full_a730`, a launch error of mine, not a gate execution.** I started the gate with a ten-minute
  tool timeout attached and stopped it 20 seconds later, during test collection (0 tests executed), so the timeout
  could not cut it short. It stays on disk as INCOMPLETE. `2026-11-12_135000_full_85b2` is the one execution.

### 3.5 Key qualification results

**`m4b-scaling`:**

| Check | Result |
|---|---|
| T1, 6 h / 48 chapters | 317.0 → 134.4 s: 2.36× wall, 2.35× CPU (budget 2.0×) |
| T1b, 1,000 chapters | 2.38× wall (budget 1.8×), 3.29× CPU (budget 2.0×) |
| T2 | 10 books below the threshold unchanged; 5 above it at 0.790–0.929 of the seeking time |
| T3 | 6/6 |
| T4 | 9/9; least headroom 3.30 MB, on the 1,000-chapter book |
| T5 | Each one-decode run's exact staged total equals the seeking route's: 17,407,343 B, 215,936 B and 69,484,778 B (one run 69,484,777 B), no allowance. Every removal and rename was read first (3,001 and 1,000 on the 1,000-chapter book); nothing left behind |
| T6 | p99 0.0154 s; no stall over 2 s |
| T7 | Cancel settled in 0.25 and 0.87 s |
| T8 | 30/30 outputs identical to the reference pinned from `204c33b` |
| Faults, pause | 3/3 faults (killed encoder or decoder, retried, identical); 1/1 pause |
| Containment | Downloads output tree unchanged; no file-manager window opened |

This is the real-FFmpeg qualification of the T5 census that changed after Phase 8 (ACT72-073).

**`edge-low-memory`:**

| Case | Result |
|---|---|
| Overlap | Eight files in flight |
| Mixed folder | Four text files and two PDFs, all narrated through the changed extractor |
| Cancel during synthesis | 16 of about 328 requests sent; none began later than 0.3 s after Cancel; nothing published |
| Cancel at finalization; Pause then Cancel | Both pass |
| Low memory | Under a real per-process memory limit |
| Containment | Owner's output tree 22 files before, 22 after |

## 4. Independent Codex reviews and their scope

| Report | Reviewed SHA | Scope | Verdict |
|---|---|---|---|
| `PHASE9-INDEPENDENT-CODEX-REVIEW.md` (local evidence `outputs/2026-11-11_phase9_codex_6a91/`, ignored) | `8596025` | Full Phase 9 review, including an **independently executed full Windows gate**, `2026-11-11_124747_full_b6c3` | Gate PASS: 14,317 ordinary (14,252 passed, 65 policy skips), guarded 457 and 75, 56/56 journeys. Review **FAIL**: P9-01 to P9-05 |
| `files/dev-work/phase9-remote-review/PHASE9-CODEX-REMOTE-REVIEW.md` (`664353c`, `4119d86`) | `dd8fb1f` | Remote re-review of the remediation | **FAIL**: R9-01 to R9-04 |
| `files/dev-work/phase9-remote-review/PHASE9-CODEX-FOCUSED-CLOSURE.md` (`3f02d4c`) | `a943a26` | Focused closure | R9-02 and R9-04 **PASS**; R9-01 and R9-03 **FAIL** |
| `files/dev-work/phase9-remote-review/PHASE9-CODEX-FINAL-CLOSURE.md` (`11fa574`, published this session) | `a00f0a2` | Focused closure | R9-01 and R9-03 **PASS** (R9-03 within the reviewed Windows scope) |

GitHub's blob of the final closure report equals the local one (`01f33bd`). All four report commits are ancestors of
the branch, and no report was edited.

**The independence distinction (still open).**

- Plan Phase 9 asks Codex to run the full applicable Windows gate independently. That happened on `8596025`, and it
  passed.
- Since the remediation (`7272eb9` through `a00f0a2`, application code included), Codex's independent evidence is focused
  re-review only: it covers R9-01 to R9-04 and no full-suite execution.
- The current-source full gate in section 3 is a **Claude-executed** release verification. It is not independent, and it
  failed.
- Plan Phase 9's recovery clause ("bounded fix, affected gate rerun and necessary independent re-review") reads as
  satisfied. Phase 10's entry ("final independent review passed for the actual current source and relevant
  qualification") is met only by focused reviews.

**Owner decision:** whether the next full gate on `5978e88` is run by Claude, or independently by Codex (which would
also settle this distinction). No owner decision supersedes the original requirement yet.

## 5. Issues

75 recorded: 72 closed, 3 open.

| Issue | State | Basis |
|---|---|---|
| ACT72-070 PDF semantic loss | **Closed** (in `c4a9853`) | Codex focused closure (`3f02d4c`) and final closure (`11fa574`). `pdf_extractor.py` is byte-identical from `a00f0a2` |
| ACT72-071 Converter Cancel against the commit | **Closed** (in `c4a9853`) | Codex focused closure R9-04 PASS at `a943a26`. Converter byte-identical since |
| ACT72-075 MP3 and M4B staging publication and roll-back | **Closed** (in `c4a9853`) | Codex focused closure (forward no-clobber) and final closure (roll-back held on Windows). Off-Windows limits stated in the record |
| ACT72-073 T5 census | **Open, closure-ready** | Independent R9-02 PASS (`3f02d4c`) plus the real-FFmpeg `m4b-scaling` PASS on `c4a9853` (section 3) |
| ACT72-064 PDF cleaning limits | **Open, for the owner** | Five limits that lose no word, plus three layout ambiguities (owner checklist item 1). Not deferred; no deferral is presented as approved |
| ACT72-030 unreferenced helpers | **Open, deferred** | The owner deferred it to a later maintenance release on 2026-11-09 |

ACT72-073 is open rather than closed for one reason: closing it in `coverage.json` after the run would change the policy
digest of the evidence that closes it. It can be flipped together with the next full gate's candidate.

The three gate failures in section 3.3 are not entered in the ledger. They were repaired before any issue could be
filed, and entering them now would change the policy digest. They are recorded here, in `Handoff.md` and in
`Decisions.md`.

## 6. Packaging and Windows compatibility

**Package audit PASS on `5978e88`.** This is the qualification's own `package` step, run alone: the real packager
(`scripts/shared/release.py`) writes and validates the archive from the commit, and every member is compared with the
commit. Nothing is extracted, set up or downloaded.

| Item | Result |
|---|---|
| Archive | `AudiobookTool-Windows-candidate-5978e88f8c62.zip`: 167 members, 4,797,632 bytes, SHA-256 `47cc957df54e16a1b99fb38e65ed3e221535f913f600b0e90dac62bcb32fc69c`. Written into ignored evidence only; nothing published |
| Contents | Every member is the commit's own file, with nothing else inside |
| Version | 0.7.2 in `version.py` and `config.toml` |
| Developer mode | Ships off |
| Reference recordings | Exactly the six approved recordings, byte for byte |
| Left out | The owner's untracked `scripts/project-status.py` |
| Same as `c4a9853` | Yes: tests are not packaged |

Other release checks:

- **Version references:** `README.md` still describes the published v0.7.0 and its download link, by recorded decision
  (`Decisions.md` 2026-11-10, Phase 8 Decision 7). It changes at publication, which is not part of this PR. Package
  names come from `release.py` (`AudiobookTool-Windows-vX.Y.Z.zip`).
- **Policy:** `verification.json`'s skip policy, stage budgets and journey list are identical to the state Codex's full
  gate ran under (`8596025`). The only difference is the stricter `pass_requires` blocks (P9-03), unchanged since
  `3aa421a`. `coverage.json` holds no exception.
- **Output compatibility:** T8 holds every Converter output byte-identical to the reference pinned from `204c33b`. The
  speech goldens are unchanged apart from the hand-edited PDF extraction golden (`Decisions.md` 2026-11-12, Decision 3a).
- **No unreviewed production code:** `scripts/` is byte-identical from `a00f0a2` (Codex final closure) to the reporting
  commit.
- **Secrets and private data:** the lines this branch adds (`204c33b..`) contain no secret-like string, no private
  absolute path and no e-mail address. `Handoff.md` carries five private absolute paths inherited from `master`; this
  branch adds none.
- **Platform scope:** Windows 11 on HOME-PC, at 100 % display scaling, as qualified above.
  - Off Windows, an MP3 roll-back moves nothing and names what it left published, and a retry then refuses until that
    is reconciled.
  - Off Windows, `publish_new` needs hard links, which FAT and exFAT lack.
  - None of this was executed on macOS or Linux.

## 7. Minimal owner acceptance checklist

**Carried forward (owner acceptance on record, not invalidated):**

- **Listening:** the owner approved the audio of all 28 voice previews on 2026-10-20 (`Decisions.md`).
  - v0.7.2 changes no engine or voice. The local engines changed only where their temporary WAV lives and a Cancel
    check before the encode.
  - The speech goldens other than PDF extraction are unchanged.
  - The PDF change alters which words are read, not how, and is covered by expected-narration tests and Codex's 14
    independent PDF cases.
- **General GUI and UX:** Phases 5 and 6 accepted by the owner at `5170b8f` and `721c323`.
- **Standing owner approvals:** the five cross-tool differences (2026-11-09), the `%TEMP%\act-gate` exception
  (2026-11-06), the ACT72-030 deferral (2026-11-09) and the ACT72-058 920x600 layout.

**Verified automatically (current source):**

- **Cancel and Pause in every tool:** the 56 native journeys in the gate (all PASS even in the failed run),
  `edge-low-memory`'s cancel and pause cases, and `m4b-scaling`'s T7 and pause case.
- **Setup, first run and repair:** the three `setup.*` journeys, plus the carried-forward `fresh-windows` run.
- **Output compatibility (T8) and publication safety:** the regressions plus Codex's closures.

**Needs the owner (three actions):**

1. **ACT72-064, the PDF limits.** Accept or schedule each one, or name a specific behaviour that is unacceptable. Each is
   pinned by a test.
   - Five lose no word:
     - a long running head is read at each page;
     - furniture nothing repeats is read;
     - a compound broken before a small letter loses its hyphen;
     - capitals at a page's end or start keep a line break;
     - a drop capital on its own line is read as a letter.
   - Three are layout ambiguities:
     - a bare number alone under a finished sentence that counts with the next page's (a year, 1984 then 1985) is
       removed as a page number;
     - counting page numbers that every sentence runs into are read out;
     - one number with page-number evidence makes a whole counting run furniture.
2. **Confirm the release scope:** Windows 10/11, qualified on Windows 11 only; the off-Windows MP3 roll-back fallback
   and the hard-link need described in section 6; macOS and Linux not run; README updated only at publication.
3. **Authorize the last verification and decide what it rests on:**
   - **One full Windows gate on `5978e88`**, run by Claude or independently by Codex (section 4).
   - Whether the `m4b-scaling` and `edge-low-memory` PASS on `c4a9853` carry to `5978e88` (application and scenario
     code digests equal; only three test files differ) or are run again.
   - The `optional-engines` and `fresh-windows` carry-forward (section 3.2).
   - The 89 visual candidates the gate lists (none approved; the visual comparison is NOT RUN).
   - Flipping ACT72-073.

   Then review the PR, mark it ready and click **Merge** on GitHub.

## 8. Remaining merge blockers

1. **No full Windows gate PASS on the current source.** It ran once on `c4a9853` and failed (section 3.3), and it has not
   run on `5978e88`. A further full run needs the owner's authorization.
2. **The independence distinction** in section 4, decided by the owner, and settled at once if Codex runs that gate.
3. The owner decisions in section 7 (ACT72-064, release scope, the carry-forward and visual-candidate questions).

## 9. What was not done

- Nothing was merged, squashed, tagged or released, and no archive was published.
- Auto-merge is off, and the feature branch is kept.
- No v0.8.0 work.
- No owner state was touched: the 14 tracked deletions, the untracked files (the v0.8.0 plan among them), `.ai/`,
  `files/run-temp/`, `scripts/project-status.py`, model caches and media
  (`outputs/2026-11-12_release_9c3d/03-owner-state-before.txt` and `-after.txt` agree).
- The gate kept two new scratch folders under `%TEMP%\act-gate` as evidence of runs that did not pass: `f8d7`, from the
  aborted launch, and `8c22`, from the failed full gate. They are the owner's to remove; nothing was cleaned up.
