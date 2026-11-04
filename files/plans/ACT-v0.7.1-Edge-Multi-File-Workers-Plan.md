# Audiobook Creation Tool — v0.7.1 Edge Multi-File Workers Implementation Plan

Branch `feature/0.7.1-multi-file-workers`, cut from the approved, published v0.7.0 baseline (`master` =
`origin/master` = tag `v0.7.0` = `c0896d8`). Machine: HOME-PC (Windows 11, Ryzen 7 9800X3D 8 cores / 16 logical
processors, 31.8 GB RAM). Authority: owner prompt of 2026-11-02 (Edge only; local engines stay at one worker; stop at
the independent-review / owner-acceptance checkpoint; no merge, tag or release).

## 1. Goal, authority and execution boundaries

### In scope

- Real concurrent conversion of **directly imported** Edge TXT/PDF files (today an all-direct queue runs one at a
  time), kept for folder imports, and for mixed queues.
- One hardware- and workload-aware worker policy for every registered Edge voice: requests of 1–100 accepted, the
  effective count bounded by queue, engine, Edge service, processors and free memory, with a stated reason.
- Narration integrity: the "blank" placeholder and every author-written heading.
- Tests, real HOME-PC Edge generation (1/2/4/8 workers, mixed, oversized), listening samples, docs, Codex handoff.

### Out of scope / deferred

- Any concurrency for Kokoro, Chatterbox Turbo or Qwen3 (stay exactly 1; research only, Phase 9, gated).
- Changing audio assembly, pauses, trimming, final-tail policy, chunking, the folder route's retry constants, or the
  folder route's (structure-free) text handling.
- Release identity, archives, tags, merge to master.

## 2. Source audit: verified facts

| # | Fact | Evidence |
|---|---|---|
| F1 | `runner.run_conversion_job` `os.chdir`s into a private temp folder because the vendored engine writes bare relative scratch names (`part{i}.flac`, `pgraphs{n}.flac`, `sntnc0.mp3`, `sntnc{n}_sub{k}.mp3`, `FFMETADATAFILE`, `filelist.txt`). `os.chdir` is process-wide, so `_CWD_ISOLATION_LOCK` serializes the whole conversion. | `runner.py:107-245`, `epub2tts_edge.py:354-551` |
| F2 | `resolve_effective_workers(..., direct_files=)` caps an Edge queue to `folder_files + 1`; an all-direct queue is 1. | `epub2tts_gui.py:343-376`; live: `BASE-v070` run logged `Requested workers: 8 \| Effective workers: 1`, peak 1 file in flight |
| F3 | Folder items (`batch_convert.convert_single_pdf`) use absolute per-source chunk folders and never `chdir`; they already overlap. | `batch_convert.py:140-265` |
| F4 | **PyMuPDF is not thread-safe** ("does not support running on multiple threads — doing so may cause incorrect behaviour or even crash Python itself", PyMuPDF docs). `pdf_extractor` is the only PyMuPDF user and is already called from concurrent folder workers; direct PDFs would add more. Pre-existing hazard. | Context7 `/pymupdf/pymupdf` FAQ; `pdf_extractor.py:103-124` |
| F5 | `_sentence_tokenizer()` lazily builds a module global with no lock (first concurrent use races; it also calls `cache_clear()` on NLTK's shared loader). | `epub2tts_edge.py:83-117` |
| F6 | Everything else on the direct path is per-call: `asyncio.run` per request (own loop), `edge_tts.Communicate` per request, pydub's FFmpeg children with their own temp files, `audio_tail` pure. FFmpeg/pydub globals are set once at start. | code read; folder route already exercises pydub + FFmpeg concurrently |
| F7 | ETA = mean per-file duration × remaining files: with N overlapping workers it over-states by ~N. Pre-existing for folder runs. | `job_control.py:2729-2736` |
| F8 | Worker stdout/stderr is redirected process-wide into one queue; `print` writes text and newline separately, so concurrent engine lines can interleave mid-line. | `epub2tts_gui.py:2972-2974, 3494-3504` |
| F9 | Direct retries: 3 attempts with a fixed 3 s wait. N workers hit by one service blip retry in lock-step (a retry burst). Folder route: 5 attempts, 2/4/8/16 s + whole-file retries — unchanged. | `epub2tts_edge.py:567-594`; `test_edge_failures.py:284` |
| F10 | Worker spinbox stops at 16. | `epub2tts_gui.py:1299-1301` |
| F11 | "blank": `get_book` names a chapter with no heading `"blank"`; `read_book` skips any title *equal to* `"Title"` or `"blank"`. Ordinary sentences keep every "blank". **Author headings `# blank` and `# Title` are silently not narrated; for two consecutive headings the first is never narrated** (and M4B chapter titles misalign). `# Blank` is narrated. | probe `files/run-temp/act071/probe_headings.py` (exact text sent to Edge) |
| F12 | Edge audio is 24 kHz mono 16-bit = 48,000 PCM bytes per second of narration. | one real request (`measure_memory.py fetch`) |
| F13 | Per in-flight file, peak memory grows linearly with narration length: **≈144 KB per narration second (direct, 3.0× PCM), ≈115 KB/s (folder, 2.4× PCM)**; FFmpeg children ≈22–24 MB regardless of length. Process-wide import overhead is shared, not per worker. | `measure_memory.py` (10/30/60/200 min, fresh process each, real assembly code, reused real clip) and `measure_ffmpeg_child.py` |
| F14 | Real Steffan narration rate: **14.7–15.1 source characters per second** of finished audio. PDFs: 1,580–1,740 extracted chars per page; page count ≈1.5 ms; a whole light-novel volume ≈370k chars ≈ 7 h ≈ 3.6 GB peak. | `BASE-v070` outputs; `files/test-files/*.pdf` (read-only) |

## 3. Design

### 3.1 Concurrency architecture (chosen: explicit working directory, no `chdir`)

Alternatives considered: (1) explicit absolute paths, (2) one subprocess per conversion, (3) keep the lock. (2) would
re-plumb cancellation, logging, typed failures (`EdgeServiceError` advice, `FileExistsError`) across a process
boundary for no gain: the engine's only process-wide dependency is the working directory. (3) is the defect. Chosen:

- `read_book`, `generate_metadata` and `make_m4b` gain a keyword `workdir=None`; every scratch name is joined to it.
  `None` keeps the legacy relative behaviour for direct callers (tests, dev tools). `make_mp3` already works from the
  absolute `work_txt`.
- `run_conversion_job` creates its private `mkdtemp`, passes `workdir=tmp`, **never changes the working directory**,
  and keeps its "cancelled before starting" check. `_CWD_ISOLATION_LOCK` is removed (nothing left to protect).
- `_sentence_tokenizer()` initialises under a lock (double-checked).
- `pdf_extractor` holds one module lock around all PyMuPDF use (extraction is ~0.2 s per volume; synthesis stays
  parallel). Covers direct, folder and local-engine PDF extraction.
- One source file's own chapters/paragraphs/sentences stay sequential and ordered (unchanged).

### 3.2 Worker policy (`scripts/tts/worker_limits.py`, stdlib only, pure and testable)

*The memory ceiling below was replaced by the review remediation: see §10.2.*

`effective = max(1, min(requested, queued files, engine ceiling, Edge service ceiling, CPU ceiling, memory ceiling))`

- Engine ceiling: Kokoro, Chatterbox, Qwen3 = 1 (unchanged constants and reasons).
- Edge service ceiling: the pre-existing 32 (`EDGE_BACKEND_SAFE_WORKERS`), kept only if a bounded live burst
  validates it; otherwise lowered to the highest validated level (§6 P5). Microsoft documents no limit for this
  unofficial endpoint; hardware capacity is not service capacity.
- CPU ceiling (Edge): one worker per logical processor (existing policy, Decisions 2026-09-21); verified by CPU sampling.
- Memory ceiling (Edge, when free memory is measurable — Windows `GlobalMemoryStatusEx`, Linux `MemAvailable`;
  macOS not measured, so not applied): usable = available − max(1 GiB, 25 % of physical RAM); each queued file's
  peak = 64 MiB + estimated narration seconds × 150,000 B/s; the ceiling is the largest N whose N **largest**
  estimates fit in usable (worst case: the biggest files run together). Narration seconds = characters ÷ 12
  (measured 14.7–15.1; margin for slower voices and pause-dense text). Characters: TXT = file bytes; PDF = pages ×
  3,000 (measured ≤1,740/page). Constants are measured (F12–F14), rounded up.
- The run log keeps `Requested workers: N | Effective workers: M` and adds `Worker limit: <reason>` when M < N.
- Spinbox range 1–100; non-numeric input keeps the existing fallback (2).
- The standalone `batch_convert` CLI uses the same policy.

### 3.3 Narration integrity ("blank")

- `get_book` marks each chapter with `narrate_title`: true only for an author-written heading with speakable text.
  The `"blank"` placeholder stays as the *name* (M4B metadata, compatibility) but is never matched by text.
- `read_book` decides by `narrate_title` (legacy dicts without it keep the old rule).
- Consecutive headings with no text between them are joined into one spoken title ("Part One. Chapter 1"), and the
  M4B chapter-title list stays one entry per chapter.
- The placeholder log becomes "Chapter heading: none in the source (nothing extra is spoken)".
- No global word suppression exists or is added.

### 3.4 Run-level correctness under concurrency

- ETA: `EtaEstimator` gains `parallelism` (default 1, so no other tool changes); estimate = mean × remaining ÷
  min(parallelism, remaining). The worker reports its effective count through the existing queue; the main thread
  applies it.
- Log: `QueueWriter` buffers per thread and emits whole lines, prefixed `[<source name>]` while a file converts.
- Direct retries: same 3 attempts; waits become exponential with ±50 % jitter (1–3 s, then 2–6 s; same mean, max
  9 s) so concurrent workers do not retry in lock-step. 401/403/protocol failures still never retry.
- Unchanged and re-proved: per-occurrence planned destinations, private staging, discard of a failed/cancelled
  occurrence's own output, cancel at chapter/paragraph/sentence checkpoints, pause between files, Retry Failed by
  occurrence id.

## 4. Phases and checkpoints (each: focused tests green → commit)

| Phase | Work | Gate |
|---|---|---|
| P0 | Branch, baseline 363 targeted tests green, live baseline `BASE-v070` | done |
| P1 | This plan + measurements | done |
| P2 | §3.1 engine/runner/tokenizer/PyMuPDF; tests: no `chdir` (AST guard), real-runner overlap with deterministic barriers, isolated + cleaned temp folders, same-stem sources, cancel during overlap | focused suites |
| P3 | §3.2 policy + GUI/CLI; hardware-profile tests (2/4/8/16/64 CPUs, 4–64 GB, unknown memory, huge PDFs) | focused suites |
| P4 | §3.3 narration; exact-text tests incl. the five mandatory sentences, `# Blank`, `# blank`, `# Title`, missing/consecutive headings | focused suites |
| P5 | §3.4; full `verify.py` | `RESULT: PASS` |
| P6 | Real HOME-PC Edge runs A–F (+ service burst), analysis, listening samples, GUI smoke | evidence |
| P7 | Docs (Changelog, Briefing, Decisions, Handoff), version 0.7.1, push branch | pushed |
| P8 | Codex handoff + owner manual guide — **STOP** | owner/Codex |
| P9 | Local-engine feasibility research — gated on P8 acceptance and owner authorization | — |

## 5. Real-run matrix (P6)

Voice `Edge Male - Steffan (en-US)` (+ one other Edge voice smoke). Inputs: `files/test-for-manual-listen-elmatthe/
ACT-v0.7.1-edge-concurrency/sources/` (original text). Harness `files/dev-work/act071/qa_harness.py` drives the real
panel and records per-file intervals, every request's exact text and audio hash, CPU and memory.

| Run | Queue | Requested | Expected effective |
|---|---|---|---|
| A | 08-blank-focus (direct) | 1 | 1 |
| B | 2 direct | 2 | 2 |
| C | 4 direct (TXT + PDF) | 4 | 4 |
| D | 01–08 direct | 8 | 8 (listening set) |
| E | 2 direct + 2 folder | 4 | 4 |
| F | 20 tiny direct | 100 | 16 (CPU ceiling) |

Checks per output: decodes, plausible duration, not silent, ending within the final-tail budget, no duplicate output,
requests attributed to exactly one file, recorded text = source text (word sequence, every "blank").

Run C's PDF is `sources-pdf/05-cartographers-oath-pdf.pdf` (heading `Chapter 5: …`). Observation, pre-existing and
unchanged: the PDF extractor's soft-wrap repair protects only `Chapter N`-style lines as headings, so an
`Interlude: …` first line was merged into the first paragraph (and would then be spoken as the heading). Flagged for
owner review; not in v0.7.1 scope.

## 6. Real-run results (P6, HOME-PC, real Edge service, final code)

Every run below used the real panel, the real runner/engine and the live Microsoft Edge service; only the output base
was redirected into the ignored QA folder. Per-run JSON and the per-file analysis are in `files/dev-work/act071/
evidence/`; the listening index is `files/test-for-manual-listen-elmatthe/ACT-v0.7.1-edge-concurrency/SAMPLE-INDEX.md`.

| Run | Queue | Logged `Requested workers \| Effective workers` (+ reason) | Peak files in flight | Result |
|---|---|---|---|---|
| BASE-v070 | 01, 05, 08 on `c0896d8`, 8 requested | `Requested workers: 8 \| Effective workers: 1` | 1 | 3 ok, one after another |
| A | 08-blank-focus | `1 \| 1` | 1 | 1 ok; "blank" sent 9/9 |
| B | 02, 06 | `2 \| 2` | 2 | 2 ok |
| C | 01, 02, 03 + PDF | `4 \| 4` | 4 | 4 ok; PDF heading spoken "Chapter five: …" |
| D | 01–08 | `8 \| 8` | 8 | 8 ok, all started within 3 ms, 24.2 s from Start to settled; listening set |
| D-serial | 01–08, 1 requested (speed baseline for D) | `1 \| 1` | 1 | 8 ok, one after another, 123.9 s; same 134 Edge requests and the same words as D |
| E | 04, 06 direct + folder (3 TXT + PDF) | `4 \| 4` | 4 | 6 ok; queued files start as slots free |
| F | 20 short files, 100 requested | `100 \| 16` + `Worker limit: this computer has 16 logical processors (one file per processor).` | 16 | 20 ok |
| G-cancel | 01–08, Cancel at 6 s | `8 \| 8` | 8 | Cancelled; 7 raised `ConversionCancelled` within 4.4 s, no MP3; the 1 finished file kept |
| H-retry | 3 short + 1 empty TXT; empty file filled, then Retry Failed | `4 \| 4`, then `4 \| 1` + `Worker limit: only 1 file is queued.` | 4 | first attempt 3 ok / 1 failed ("No text content"), no MP3 for it; retry re-ran only it → 4 MP3s |
| S-samename | `a/chapter.txt` + `b/chapter.txt` | `2 \| 2` | 2 | 2 ok, distinct names (`…-1.mp3`), each with its own words |
| V-andrew/aria/ava/jenny | 4 short each | `4 \| 4` | 4 | 4 ok each; engine saved with the chosen voice id |
| service burst | 16 and 32 tiny conversions released together (production runner) | — | 16 / 32 | 16/16 and 32/32 ok, 0 retries — the Edge ceiling of 32 is kept |
| GUI smoke | real window, real input: 4 files via Open dialog, `100` typed, Start | `100 \| 4` + `Worker limit: only 4 files are queued.` | — | 4 MP3s; owner's Downloads output untouched |

Every completed output: decodes; units sent to Edge = units expected, and the words sent = the prepared source's
words in order (TXT and PDF, both routes); no request unattributed; no duplicate audio; reruns of a label wrote a new
numbered run folder (`TTS-Audiobook-2`), never over the previous one; no new `epub2tts_*` temp folder left behind.
Final tails 150–160 ms, except `04-glass-orchard` (0.39–0.40 s, which the unchanged v0.7.0 rule keeps and logs as
"please listen to the ending"). App memory peaked at 239 MB (8 workers, run D) and 231 MB (16, run F), against
223 MB for the same eight files on 1 worker; machine CPU touched 100 % only for the 16 simultaneous short encodes of
run F. The eight-file speedup (about 5×, not 8×) is bounded by the longest file: run D ends when `03-the-ninth-bell`
finishes, 23.0 s after the first conversion call.

**Gate on `48f6667`:** `python scripts/verify.py` → `RESULT: PASS` — pytest 12,779 passed, 65 skipped; guarded
v3-planning 457 + v3-supervisor 75 passed; deps, docs, docnames, config (0.7.1) and tree (unchanged during the run)
pass. Evidence (ignored): `files/dev-work/act070-remediation/verify/ACT071-48f6667-run1/`. The docs-only commit that
follows touches only `md-instructions/` and this plan.

## 7. Defects the real runs found (fixed, with tests)

1. **Stacked progress bars in the log.** With several files at once, tqdm auto-positions each bar and draws it with
   newlines and cursor-up codes; the Detailed pane showed raw `ESC[A` characters and runs of empty `[file]` lines
   (run D: 44 escape lines, 163 bare/empty of 279). Fix: `tqdm(..., position=0)` (tqdm docs: `position` is the line
   offset, "automatic if unspecified … useful to manage multiple bars at once (e.g. from threads)"; byte-identical
   output for one bar, verified). Run D's log is now 103 lines, 0 escape codes, one progress line per file. Test:
   `test_the_detailed_log_stays_readable_while_eight_files_convert_at_once` (failed before the fix).
2. **Blank lines labelled.** `QueueWriter` prefixed even empty lines with `[file]`. A blank line now stays blank.
   Test: `test_a_blank_line_stays_blank_rather_than_a_bare_file_label`.

Observed, pre-existing, not changed (flagged for the owner): the Detailed pane keeps the last 400 lines
(`LOG_LIMIT`), does not wrap (at the default window size `Requested workers: 100 | Effective workers: 4` is clipped
at the last digit — maximize to read it), and the label under the progress bar shows an internal id (`occ-000008`)
rather than the file name (also in v0.7.0 screenshots).

## 8. Independent Codex verification brief

*For the review of `3efbb77`, kept for the record. The current brief is §11.*

See `md-instructions/Handoff.md` (current state) for the exact branch/SHA. Audit, independently of this plan's claims:

1. **Process-wide state.** `scripts/tts/epub2tts_edge/runner.py`, `epub2tts_edge.py`: no `os.chdir`; every scratch
   path is inside the per-call `mkdtemp` (`workdir`); the folder is removed on success, failure and cancel. Look for any
   remaining relative path, shared global, or FFmpeg/pydub call that depends on the current folder.
2. **Real concurrency.** `files/tests/test_edge_direct_concurrency.py` and section E of
   `test_tts_worker_concurrency.py` use the real runner/engine with only the network request faked and a
   `threading.Barrier`; confirm they would fail on `c0896d8` (they did: `BrokenBarrierError`). Real-service evidence:
   `files/dev-work/act071/evidence/` (ignored; per-file intervals, peak in-flight, every request's text).
3. **Worker policy.** `scripts/tts/worker_limits.py`: constants trace to measurements (plan §2 F12–F14); memory is never
   invented where unmeasurable; local engines are 1; reasons are truthful. Try adversarial profiles.
4. **Thread safety of libraries.** PyMuPDF serialized (`pdf_extractor._PYMUPDF_LOCK`, all calls); NLTK tokenizer
   built once; pydub/FFmpeg/edge-tts per-call. Anything else shared?
5. **Output safety.** Destinations still planned per occurrence; staging private; failed/cancelled outputs discarded
   only inside the run folder; Retry Failed reruns only failed occurrence ids.
6. **Narration.** `get_book`/`read_book` heading identity (`narrate_title`), consecutive-heading join, legacy-dict rule;
   the regenerated golden (`3ec2f44`) changes only M4B chapter titles. No word filtering exists.
7. **Run plumbing.** `QueueWriter` per-thread whole lines; ETA parallelism (`EtaEstimator.set_parallelism`, default
   1 for every other tool); jittered direct retries (still 3 attempts, max 9 s waiting).
8. **Regressions.** Kokoro/Chatterbox/Qwen3 paths unchanged and capped at 1; folder route unchanged except the CLI's
   worker bound; Windows specifics (resolve of a new folder, handle inheritance of concurrent FFmpeg children).

## 9. Owner manual acceptance (HOME-PC)

Listening (automated checks cannot judge pronunciation or naturalness):

1. Open `files/test-for-manual-listen-elmatthe/ACT-v0.7.1-edge-concurrency/SAMPLE-INDEX.md`; play the files in
   its `listen/` folder in the index's "Listen first" order (`08-blank-focus`, the two ~1-minute samples,
   `04-glass-orchard`'s ending, the PDF by both routes), then the rest.
2. PASS: every "blank" is spoken (nine in `08-blank-focus`, the first being the heading "Blank" followed by a pause);
   headings are spoken once, at the start; no sentence is missing, repeated, cut or out of order; pace, pauses,
   punctuation and proper nouns sound as in v0.7.0. FAIL: any omission, duplication, truncation, wrong-file content,
   clipped ending, or a pause/pace change from v0.7.0.

In the app (launch with `Setup_and_Run-audiobook-creation-tool.bat`, TTS tool):

3. Add Files → the eight files in `sources/`; voice **Edge Male - Steffan (en-US)**; File workers **8**; **Start**.
   PASS: the Detailed tab (maximize the window if a line is cut off at the right) shows
   `Requested workers: 8 | Effective workers: 8`; engine lines are prefixed `[<file>]`, with one "Generating audio
   files" line per file and no stray symbols; all eight finish (8 ok, 0 failed) in roughly the time of the longest
   file, not the sum (measured on HOME-PC: 24 s with 8 workers, 124 s with 1); the run folder holds eight MP3s named
   `<stem>-Edge Male - Steffan (en-US).mp3`.
4. Clear All; Add Folder → `sources/` (folder import); File workers 8; Start. Same PASS (folder route: whole chunks,
   no heading handling — unchanged).
5. Mixed: Add Files (two files) + Add Folder (`sources-folder/`); File workers 4; Start. PASS: `Effective workers: 4`;
   all six succeed; the last two start as soon as the first two finish.
6. Oversized: 20 files from `sources-cap/`, Workers **100**. PASS: `Requested workers: 100 | Effective workers: 16`
   and `Worker limit: this computer has 16 logical processors (one file per processor).`; all 20 succeed.
7. Cancel: 8 files, Workers 8, press Cancel after ~5 s. PASS: the run ends Cancelled within a few seconds; no
   partial MP3 is left for an unfinished file; files that had finished are kept and counted.
8. Retry Failed: Add Files → the four files in `sources-retry/` (one, `cap-09-empty-then-fixed.txt`, is empty);
   File workers 4; Start. PASS so far: 3 ok, 1 failed ("No text content found …"), no MP3 for the empty one. Paste a
   sentence into that file, save, press **Retry Failed**. PASS: the log shows `Requested workers: 4 | Effective
   workers: 1` and `Worker limit: only 1 file is queued.`; only that file runs; it lands next to the other three.
9. Pick another Edge voice (e.g. Jenny) with 4 files and Workers 4. PASS: effective 4, all succeed.
10. Throughout: no pre-existing file anywhere is replaced; Kokoro/Chatterbox/Qwen3 with Workers 8 still show
    `Effective workers: 1` and `Worker limit: <engine> converts one file at a time.`
11. Another drive (added by the remediation; only a real run can prove this): in **Preferences & Data** choose **Use a custom
    folder** on another drive (`D:`), add 4 files, Workers 4, Start, and watch the run folder. PASS: each `…-<voice>.mp3` appears only when
    that file is finished, and plays to its end; a short-lived `.act-tmp-*.part` may be seen beside them and none remains
    at the end. Then put the output folder back.
12. Whole books: queue 2-4 of your own long PDFs or TXT (hours of narration), Workers 4, Start. PASS: the log says
    `Effective workers: 4` unless your free memory is low (it then names the reason); all finish, one or two at a time
    near the end, with `Waiting for memory` in Detailed if they had to take turns; Windows stays usable throughout.
13. Overwrite (owner ruling): open the tool. PASS: **Overwrite existing outputs without asking** is unticked. Empty
    `cap-09-empty-then-fixed.txt` again and run step 8 up to its failed file. Before pressing **Retry Failed**, put the sentence
    back and copy any other MP3 into that run's folder under the name the failed file would take
    (`cap-09-empty-then-fixed-<voice>.mp3`). Press **Retry Failed**. PASS: that file fails, saying it "already exists and
    overwriting is off, so it was left as it is", and your copy still plays as it did. Repeat the whole step as a new run with
    the box ticked before Start. PASS: the retry succeeds and that file now holds the new narration.

## 10. Remediation of the independent review of `3efbb77` (2026-11-03)

The review was BLOCKED. Each finding was reproduced first (`files/dev-work/act071-remediation/logs/repro-before-3efbb77.jsonl`,
ignored). A second, fresh internal review of the fix found twelve more items, listed in §10.4. The owner then ruled that
**Overwrite** stays off unless ticked for a run, which the local engines' path also had to honour.

### 10.1 HIGH-001: the publication contract (`scripts/tts/publication.py`)

| Requirement | How it holds |
|---|---|
| Finished before the name is visible | The encode and its checks finish first; the name is given last |
| Private staging on the destination's filesystem | `.act-tmp-<pid 8 hex><5 hex>.part` beside the destination, `O_EXCL`. A cross-volume file is copied into it; nothing is ever copied onto a final name |
| Atomic | One same-filesystem operation |
| `overwrite=False`, no time-of-check window | The operation itself refuses: Windows `os.rename` (`MoveFileExW`, no replace, no copy), elsewhere `os.link`. `refuse_existing` before synthesis is only a courtesy |
| `overwrite=True` | `os.replace`; the old file is never deleted first and stays valid on any failure |
| Locks, permissions, disk | A real lock is waited out for about 3 s (the staged file, the finished file, the check, the destination), then named. Disk-full is named. An unsupported drive fails with a message; there is no fallback |
| Attempt ownership | Only the staging file this attempt created. `discard_partial` is gone |
| Overwrite (owner ruling) | Unticked by default; frozen in the snapshot, so a retry keeps the run's choice; numbering at planning unchanged. A name taken after planning fails that item, because destinations are frozen |
| Siblings, numbering, destinations, frozen settings, Retry Failed, mirroring, resume, sources | Not touched: destinations are still planned once and frozen. Real-panel tests cover Retry Failed after an interrupted publication on both routes |
| Orphans | `sweep_orphans`: exact name, regular file, owner gone and an hour old (a pid may belong to another computer on a shared folder), or this process with no attempt using it. At each Edge run over the tool's output folder, and by the standalone batch |
| Nothing invalid reported | Edge routes: `check_narration` (not silent, not over the WAV limit) before the encode; `verify_finished_mp3` (a real MP3, the length encoded, not cut short) after. Every route: empty refused at publication |

Routes: `run_conversion_job` (standalone and via the panel), `convert_with_edge_engine`, `convert_single_pdf`,
`run_batch_convert`, and `_convert_with_local_engine` for Kokoro, Chatterbox Turbo and Qwen3-TTS. An AST test forbids `shutil.move`, `os.rename` and `os.replace` in those modules. **Primitive
proof (HOME-PC NTFS, separate processes, 8 racing for one name, 100 rounds):** `os.rename` and `os.link`: one winner every
round, no partial view; the control, `exists()` then `os.replace`: several winners in 42 of 100
(`logs/noclobber-primitives-100.jsonl`). **Cancel:** a narration past its last checkpoint is kept; see Decisions.

### 10.2 HIGH-002: admission (`scripts/tts/worker_limits.py`)

Layers and every number's status are in that module's docstring. Effective memory ceiling = the most files whose synthesis
memory fits beside the largest single assembly, in `available - max(1 GiB, 25 % of RAM)`.

| | Before | After |
|---|---|---|
| Ten `A.` lines (8.649 s of audio in the review's offline run) | 2.5 s | 12.5 s |
| Dense one-page PDF, 15,499 characters | 3,000 characters | its extracted text |
| Eight 160 KB pause-heavy files, 16 GiB machine with 8 free | 2 workers | 1 (about 7 GiB each to assemble, 4 GiB usable) |
| Eight 370,000-character volumes (about 8 hours each, about 4.4 GB each to assemble), 8 GiB usable | 1 worker | 8, assembling in turns |
| Ten real narrations (`logs/estimate-vs-real.jsonl`) | | model / real = 1.42-1.58, never below 1 |

**Measured:** see "Real process memory" in §10.5. **Modelled:**
each file's narration and peak: an estimate, never presented as measured. **Cannot be bounded in advance:** a page a sample
did not read; a source changed after planning; a long paragraph the model did not see (its memory builds during synthesis,
and it is reserved only when joined).

### 10.3 LOW-003 and INFORMATIONAL-004

`log_lines` prints `Worker limit:` only for a reduction and `Worker note:` whenever something unmeasured could have mattered
(not when something else holds the run to one file). A final heading with nothing after it stays unspoken:
`test_a_final_heading_with_nothing_after_it_is_not_spoken` characterizes it, and the five mandatory "blank" sentences,
spoken headings and the speech goldens are unchanged.

### 10.4 What the fresh internal review changed

A quadratic pattern hung planning on a long run of dots, found first (`logs/regex-timing-before.txt`, `-after.txt`), then
from the review: a real lock was not retried (Python's `open` gives no Windows error number); planning was unbounded inside
one PDF and ignored Cancel; a Cancel during the memory wait discarded finished work, depending only on queue order; a source
with no line breaks was outside the gate; unknown memory set no limit; two standalone runs shared a chunk folder and one
could publish the other's audio as a success; a failed encode re-synthesised the whole file three times; the over-24-hour
failure was a bare `struct.error`; a note could leak a reservation; the gate's start figure could go stale; a "cut short"
check allowed 10 %; a lone carriage return was not a line; a length-based estimate ignored the frozen pauses; several tests
did not prove their names. All fixed, except that the review's "flush long paragraphs to disk" was declined (Decisions).

### 10.5 Verification

- **Gate on `c64140a`:** `python -u scripts/verify.py --evidence-dir files/dev-work/act070-remediation/verify/ACT071-REM-c64140a-run1` → `RESULT: PASS`: pytest 13006 passed, 65
  skipped, 38 min 56 s; guarded v3-planning 457 + v3-supervisor 75 passed; deps, docs, docnames, config (0.7.1), tree unchanged.
- **Audio unchanged:** the same sources through `3efbb77` and the final tree, offline with one deterministic clip: MP3 bytes,
  decoded PCM and request text identical on 18 outputs (`logs/identity-result.txt`). No golden changed.
- **Real runs, real panel, this code** (`probes/evidence/R3-D8.json`, `R3-E4.json`, `R2-kokoro.json`, `R2-chatterbox.json`,
  `R2-qwen3.json`): `R3-D8`: 8 direct files, Workers 8: peak 8 in flight, 23.81 s, 8 succeeded. `R3-E4`: 3 direct + 4 folder files, Workers 4: peak 4, 14.86 s, 7 succeeded, every direct file overlapping every folder file. Every planned name present, no staging left, QA folder unchanged. One short file each, Workers 8, effective 1: Kokoro 11.65 s (32.0 s of audio), Chatterbox Turbo 51.58 s (34.2 s), Qwen3-TTS 51.12 s (35.0 s); planned names, no staging.
- **Real process memory:** peak working set above the process's start, FFmpeg children not counted, no network (each request copies one real-format clip through the real runner, engine and folder worker; `logs/memory-measurements-final.jsonl`). One pause-heavy file of 1,799 s: 268 MB, against a 348 MB modelled budget. Eight files of 1,199 s each, side by side with ample memory: 592 MB, against a 791 MB admission budget (the eight individual modelled peaks sum to 2,037 MB), 174 s. The same eight with the gate forcing turns: 189 MB, 476 s. Sources of many hours have not been measured; those figures remain modelled (owner step 12 exercises them).
- **Test doubles changed:** silent fake clips became audible, because silence is now a failure; merges that wrote nothing now
  write, because a success must publish something; tests that read the path handed to a local engine now read where the file
  really lands; `test_a_failed_item_leaves_no_partial_at_its_own_destination`, which codified the deletion by path, was
  replaced by tests that a foreign file survives; tests that assumed Overwrite started on were updated. No test was skipped
  or xfailed; the new publication tests carry two environment conditions (Windows for a real lock, FFmpeg for real
  clips), and neither fired here.
- **Not exercised:** a real second volume, exFAT, network drives (owner step 11 covers the second volume); macOS.

## 11. Fresh independent Codex review brief

Branch `feature/0.7.1-multi-file-workers`, from `c0896d8`. `c64140a` is the code; the commit after it is documentation only.
Verify independently of this plan's claims. The checkout needs its own Python environment with this repo's packages; a short
path; and Git ownership for the user running it. An isolated checkout without them produces provisioning failures, not findings.

1. **Publication and Overwrite.** `scripts/tts/publication.py` and its callers, including the local engines' path. Try to get a
   partial, silent or wrong file under a final name, a replaced file with the box unticked (the default, on a first run or a
   retry), a deleted file that the attempt did not create, or a leftover the sweep wrongly removes.
   `files/tests/test_edge_publication.py`; a real lock and a real junction are used there.
2. **Admission.** `scripts/tts/worker_limits.py`. Try adversarial sources and machines; is any peak still far above what is
   admitted, and can planning stall? `files/tests/test_worker_limits.py`. Is "synthesis memory + the largest assembly"
   sound given the gate?
3. **The gate.** Races, deadlock, fairness, reservation leaks. It wraps joins in `read_book`, the runner's `make_mp3` and
   `merge_mp3s`.
4. **Cancel.** A narration past its last checkpoint is kept, by decision. Is any path left where a finished file is lost, or a
   Cancel never takes effect?
5. **Regressions.** Direct, folder and mixed still overlap; no `chdir`; assembly, pauses, tails and words unchanged; Kokoro,
   Chatterbox Turbo and Qwen3-TTS at one worker; the "blank" and heading behaviour; other tools untouched.
6. **Not a finding, unless you disagree with the reasoning:** the last-heading behaviour (owner's call); the over-24-hour limit
   (pre-existing, flagged); a name taken after planning failing its item rather than being numbered (frozen destinations).
