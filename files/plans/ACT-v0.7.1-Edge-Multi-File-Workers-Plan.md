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
    near the end, with `Waiting for memory` in Detailed if they had to take turns, or `assembled on disk` if one could not fit; Windows stays usable throughout.
13. Overwrite (owner ruling): open the tool. PASS: **Overwrite existing outputs without asking** is unticked. Empty
    `cap-09-empty-then-fixed.txt` again and run step 8 up to its failed file. Before pressing **Retry Failed**, put the sentence
    back and copy any other MP3 into that run's folder under the name the failed file would take
    (`cap-09-empty-then-fixed-<voice>.mp3`). Press **Retry Failed**. PASS: that file fails, saying it "already exists and
    overwriting is off, so it was left as it is", and your copy still plays as it did. Repeat the whole step as a new run with
    the box ticked before Start. PASS: the retry succeeds and that file now holds the new narration.

14. Fresh-install layout (found by the second review; a known defect, for your decision): on a copy with Kokoro not installed, make the window as small as it goes (920x600), and pick a Kokoro voice. Today Start and everything below it are out of view until the window is made taller. Say whether you want it fixed; any larger window is fine.

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

## 12. Remediation of the fresh independent review of `e19527e` (2026-11-04)

The review: HIGH-001 **PASS** on the exercised Windows NTFS contract; HIGH-002A and HIGH-002B **BLOCKED**. Both were reproduced first, with the reviewer's own recipe
(`files/dev-work/act071-rem2/logs/repro-before-e19527e.json`, ignored; `repro_findings.py` beside it), to its figures exactly.

### 12.1 What changed

| Finding | Before | After |
|---|---|---|
| 002A sizing: the reviewer's 80-page PDF, fully read | longest paragraph 209.1 s; working budget 98.6 MB; 8 workers on 8 GiB | 16,667.4 s, as the real paragraph; 2.57 GB; 1 worker, memory named as the reason |
| 002A sizing: an ordinary book | | still 8 workers: paragraphs that finish are not joined |
| 002A runtime: a paragraph too long to hold | builds up in memory, then waits at the gate holding it | writes FLAC as it grows; holds at most `SYNTHESIS_HELD_PCM_BYTES`; there is no paragraph join to wait at |
| 002A runtime: one enormous clip | decoded whole, before any gate | never comes into memory (`clip_to_flac`) |
| 002B: first assembly, 0 bytes free | admitted, with a warning | waits, then `AssemblyMemoryError`; nothing entered, nothing left held |
| 002B: first assembly, too large for what is free | admitted, with a warning | assembled on disk |
| 002B: synthesis already using the memory | invisible: only reservations were counted | read every time, from the operating system |

The rule is in `worker_limits`'s docstring and the reasoning, with what was rejected, in `Decisions.md` 2026-11-04. Files: `tts/disk_assembly.py` (new), `tts/worker_limits.py`, `tts/pdf_extractor.py`,
`tts/epub2tts_edge/epub2tts_edge.py`, `tts/epub2tts_edge/runner.py`, `tts/batch_convert.py`; in `tts/publication.py` one check became its own function, and HIGH-001's contract is otherwise untouched.

### 12.2 The evidence (all in `files/dev-work/act071-rem2/`, ignored)

- **The same audio.** Real Edge audio: 41 real requests, 3 voices, TXT and PDF, both routes; memory, disk, forced spills and forced long clips gave one MP3 (`logs/real-audio-identity-final.json`, on `743572c`). That folder case is one chunk, so 6 more requests compare a 3-chunk source, in 2 voices, across the pause between chunks: identical (`logs/real-audio-folder-chunks.json`). `e19527e` against this tree on the ordinary
  route: 18 outputs identical in MP3 bytes, PCM and request text (`logs/identity-final.json`, `logs/identity-final-result.txt`). The 9 folder outputs are one chunk each of one stub clip, so they vouch for request text and that path, not for 9 different audios. No golden changed.
- **Real process-tree memory** (`logs/memory-final-*.json` and `memory-before-*`; the new route on `743572c`; sampled every 10 ms, children included, by the reviewer's method; working sets, so a paged-out commit peak would not show). Told 1 GiB is free of 8:

| Narration | Route | Added during assembly | Added over the whole run | SHA-256 |
|---|---|---:|---:|---|
| 2 hours, ordinary | `e19527e` | 680 MB | 689 MB | `6559aa56…` |
| 2 hours, ordinary | now | 30 MB | 151 MB | `6559aa56…` |
| 4.6 hours, the reviewed paragraph | `e19527e` | 2,297 MB | 3,069 MB | `92e3781e…` |
| 4.6 hours, the reviewed paragraph | now | 30 MB | 327 MB | `92e3781e…` |

  An earlier run on this logic gave 31 and 32 MB for assembly (`memory-after-*`), which is why 32 MB is the figure quoted elsewhere. What is left of the whole-run figures is not audio: `logs/where-memory-goes-final.json` puts the clip step itself at +1 MB (+2 MB earlier), and about 100 MB of the 4.6-hour figure is the measuring script's own fake clip. With plenty free, both narrations still assemble in memory (`final-*-roomy`).
- **Do the tests bite?** 41 of 41 mutations caught, each by a named test (`logs/mutations.log`; `mutate.py` works on private copies with the real FFmpeg). A no-change control passes with nothing skipped: the first attempt had no FFmpeg pin in its copies, so
  most tests skipped and the mutants looked alive, which the control exposed. Survivors then found three real gaps, now closed: narrations whose ending the tail policy never cut; a check that read a header and not the file; and a build-dependent default codec. One check turned out redundant, and went.
- **Real HOME-PC runs on this code, `743572c`** (`probes/evidence/R5-D8.json`, `R5-E4.json`): 8 direct files, Workers 8: peak 8, 25.54 s, 8 succeeded. 3 direct + 4 folder files, Workers 4: peak 4, 15.79 s, 7 succeeded.
- **Gate on `743572c`:** `python -u scripts/verify.py --evidence-dir files/dev-work/act070-remediation/verify/ACT071-REM2-743572c-run1` → `RESULT: PASS`: pytest 13085 passed, 65 skipped, 50:48; guarded v3-planning 457 + v3-supervisor 75 passed; deps, docs, docnames, config (0.7.1), tree unchanged.
- **The first gate run failed:** on `18d6a5f`, 1 failed, 13,084 passed, 65 skipped (`files/dev-work/act070-remediation/verify/ACT071-REM2-18d6a5f-run1`). `test_no_guard_over_production_modules_still_walks_scripts_with_a_raw_rglob` caught the new assembly guard walking `scripts/` directly, where it would also read machine-local files. The guard now uses `source_probe.application_python_files`; no exemption was added, and `743572c` changes only `test_assembly_on_disk.py`. Two added mutants prove it still reaches the direct and folder sites, and an existing one the chapter join.

### 12.3 Limits, stated

Physical memory was never actually exhausted, and no long real book has been run end to end: the long narrations above use real FFmpeg and a real encode, with a synthetic tone for speech. Disk full is injected. The disk route on a second volume, exFAT and network drives is not exercised (a folder route's working file is beside its output), and macOS was not run. On a machine whose free memory cannot be read, an assembly over the 2 GiB assumption now uses disk.

### 12.4 Found on the way, flagged, not changed

Four tests fail in a checkout without the optional voices; Codex reproduced them on `c0896d8`, and they pass in this machine's gate. See `Handoff.md`. One of them is a real, narrow layout defect at exactly 920x600 with Kokoro selected and not installed (owner step 14).

## 13. Fresh independent Codex review brief (replaces §11)

Branch `feature/0.7.1-multi-file-workers`, from `c0896d8`. `18d6a5f` is the code, `743572c` corrects one test in it, and the commit after that is documentation only. Verify independently of this plan's claims. The checkout needs its own Python environment with this repo's packages, a pinned FFmpeg pair and the NLTK data; a short path; and Git ownership for the user running it. Without the optional voices installed, expect the four failures of §12.4; they do not need rediscovering, but disagree if you think they are more than that.

1. **The two findings.** Rerun your `fresh_probes.py` recipe. Is the plan right about real paragraph formation (`pdf_extractor._join_pages`), and does anything still let memory grow past what the gate decided?
2. **Hold it to its claim of the same bytes.** `tts/disk_assembly.py` says it gives pydub's file. Try formats, edge lengths, real audio, ends that round past the last frame. A different byte anywhere is a finding: this route exists to be indistinguishable.
3. **The disk route's own failures.** A full disk, a killed FFmpeg, a process killed mid-assembly, a locked or read-only working folder, a name taken meanwhile. Publication must still be HIGH-001's: try to get anything under a final name that should not be there.
4. **The gate.** Races, fairness, a reservation leak, a wait that never ends, Cancel during each wait. Is the three-way decision sound? `DISK_ASSEMBLY_BYTES` is a measured figure with a margin: try to exceed it for real.
5. **The spill.** Paragraphs, sentences of many clauses, a long clip at each position (title, first, comma, last words of a chapter, last words of the book), zero pauses, resume with a leftover file.
6. **Regressions.** Direct, folder and mixed overlap; ordinary narrations byte-for-byte as `e19527e`; HIGH-001 unchanged; local engines at one worker, untouched.
7. **Not a finding, unless you disagree with the reasoning:** a plan that stays conservative though synthesis would now fit more (`Decisions.md`); the failure at under 64 MiB free for five minutes; temporary disk space about the size of the uncompressed audio. And everything §11 listed.

## 14. Remediation of the independent R2 review of `e0aab03` (2026-11-04)

The review: HIGH-001 and HIGH-002A **PASS**, disk assembly byte-identical, regressions clean; HIGH-002B **BLOCKED** by R2-1, a real allocation failure that hung a whole run for ever. The owner accepted R2-1 as in scope and blocking, not as pre-existing. Everything measured below is in `files/dev-work/act071-rem3/` (ignored): `r2-review-evidence/` and `r2-review-probes/` (the review's own), `runs/pre-fix/` (the failure, kept), `runs/chain2/` (the numbered results on the final code, `664d8b6`; its `00-` and `99-code-hashes.txt` show the code did not change while it ran), `runs/final3/`, `runs/panel/`, `probes/`.

### 14.1 The cause, and why the obvious fixes do not work

`Popen.communicate` with two pipes on Windows reads each on a Python thread. When memory runs out while FFmpeg's output is read, the stdout thread dies of `MemoryError` and nothing reads that pipe again: FFmpeg blocks writing to it, and `communicate` waits for ever for the stderr thread, which is waiting for FFmpeg. Nothing is raised. pydub decodes and exports through exactly that call, from one place in each of two modules; plain Python and FFmpeg hang the same way with none of this tool's code (`runs/`, the review's `p7c-control.log`). So catching `MemoryError` cannot help (it is on another thread), a timeout on a thread leaves the process blocked, and a better memory check still loses to memory that goes after the check.

### 14.2 The design

| Part | What it does |
|---|---|
| `tts/ffmpeg_watch.py` | A `Supervised` process has no threads of its own. Output is read by the thread that asked for it, so `MemoryError` is raised where it can be handled, and that thread kills the process on its way out. Stderr goes to a temporary file, so it cannot block. One watchdog looks at every live process and kills one that has stalled or been cancelled, which also ends a blocking read. |
| The seam | `ffmpeg_watch.install()` replaces the `subprocess` name in `pydub.audio_segment` and `Popen` in `pydub.utils`. pydub's commands, and so its audio, are unchanged, no call site can be missed, and `test_what_pydub_uses_is_what_was_replaced` fails if a new pydub starts FFmpeg another way. `disk_assembly` uses `Supervised` directly. Audited: `from_file`, `from_mp3`, `export`, `mediainfo_json` on both routes. Left alone, on purpose: `_run_ffmpeg` for CLI-only M4B (`subprocess.run` with no pipes, so it cannot deadlock this way, but it has no deadline), `generate_voice_samples.py`, which is dev-only. |
| `worker_limits.assemble` | The one way to assemble, given both routes (an AST test counts the three callers). An allocation failure in memory, however it surfaces, gives back the reservation (`AssemblyPlace.to_disk`, which wakes waiters) and assembles the same parts on disk, with no new request to the service. The disk route is tried at most twice, the second time after the files holding memory have finished (at most the gate's wait, at least 2 s). Then `AssemblyMemoryError`, in words a person can act on. |
| Inside synthesis | A clip's decode, a paragraph's join and a chapter's pause fall back the same way, so hours of paid-for speech are not thrown away over one small allocation. Anything else out of memory is named too: never again a blank `MemoryError:`, and classed local, so never synthesised again by itself. |
| What is read | Physical less `memory_reserve`; commit (`ullAvailPageFile`) less `COMMIT_RESERVE_BYTES` (1 GiB); a Job Object's process or job limit, where one applies and can be read (`QueryInformationJobObject`), less `LIMIT_MARGIN_BYTES` (32 MiB). The tightest wins. A reading that is unavailable is left out. To disk, only the bare amount is required, with this process's part alone (`DISK_ASSEMBLY_PROCESS_BYTES`, 24 MiB) compared with a per-process limit, FFmpeg having its own. |
| Reservations | An allocation is in those readings as soon as it is made, so what is counted is what is reserved less what this process has allocated since the first reservation began (`AssemblyGate._claimed`). Where this process's usage cannot be read, all of it counts, which only waits longer. |
| The gate's lock | Notes run outside it. A note that fails no longer stops the work: the log may be out of memory too. |

### 14.3 The deadlines

Defaults, in `ffmpeg_watch` and `worker_limits`. Measured with the real gate, runner and FFmpeg, and a really suspended FFmpeg (`NtSuspendProcess`) for a stall; a shortened constant where marked, because a test does not wait five minutes.

| Situation | Deadline | Measured |
|---|---|---|
| FFmpeg makes no progress, no Cancel | `STALL_SECONDS` 300 s, then that file fails, named | 6.31 s with the constant at 6; those waiting behind it went on and matched the reference |
| Too little for even the disk route, nothing here to wait for | `ASSEMBLY_MEMORY_WAIT_SECONDS` 300 s, **for the whole queue** | 8 files, constant at 6: all 8 ended together, at 6.25 s. Before: one after another, 48 s for the same 8; by the same arithmetic 40 minutes at the default on 8 workers, 2.67 hours on 32 |
| Cancel, speech still to come, waiting or in FFmpeg | One poll (0.25 s) | Suspended FFmpeg: 0.25 s |
| Cancel, finished narration waiting for its turn or memory | Goes to disk at once | All 3 published in 10.08 s (direct) and 11.80 s (folder), while others held memory; bytes as the reference |
| Cancel, finished narration, no room even on disk | `CANCEL_FINISH_WAIT_SECONDS` 30 s, then says it was not saved | 30.41 s |
| Cancel, finished narration, FFmpeg no longer progressing | `CANCEL_STALL_SECONDS` 30 s, then says it was not saved | 30.08 s (direct), 30.07 s (folder), 30.00 s (a decode, folder) |
| Cancel, finished narration, progressing but long | `CANCEL_FINISH_SECONDS` 600 s in all | Test with the constant at 1 s. Not measured at full length: 4.6 hours took 31 s here, which scales to about 3 minutes for 24 hours |

### 14.4 The results

**Before and after**, the same scenario on an exact copy of `e0aab03` (`runs/pre-fix/`) and on the fix. Three files in `run_conversion_job` or `convert_single_pdf`, an hour each, real FFmpeg, startup commit measured (about 1,136 MB) and the limit set above it. A parent outside the limit, with the child and all it starts in its own kill-on-close job, gave each 240 s.

| Scenario | `e0aab03` | Fix |
|---|---|---|
| 60 MB headroom, real gate | **Hung** at 240 s | 3 of 3 published, 21.2 s |
| 60 MB, gate told it fits, direct | **Hung** at 240 s | 3 of 3 published, 16.4 s |
| 60 MB, gate told it fits, folder | **Hung** at 240 s | 3 of 3 published, 13.5 s |

**The whole matrix on the fix** (`runs/chain2/02-matrix.txt`, 30 scenarios, 57 files published): nothing hung; every run ended by itself, no reservation left, no FFmpeg of ours surviving, nothing at all left behind in the output folder or temporary files, and never more than one pass of requests (nothing asked for twice). Every published MP3 matches the unlimited reference (`db037d42…` direct, `4d85d49b…` folder):

- 25, 60, 100, 200 and 300 MB with the gate told it fits, so the in-memory route really meets the limit and route selection cannot hide it, on direct, folder and mixed queues.
- 60, 100 and 200 MB on the real gate: it reads the limit and chooses disk (`peak in_memory` 0). A limit on a whole job (300 MB, FFmpeg included) is read and respected too.
- Memory going after the gate said yes (a real ballast, started once a file was admitted): fell back with the same bytes when 70 MB stayed free; a named failure when nothing did.
- Workers plus waiters with Cancel, a stalled holder with those waiting behind it, a starved queue of 8.
- A limit below what the process needs is refused as `invalid` by the probe, never reported.

**The real panel under a real limit** (`runs/chain2/03-panel-lowmem.txt`): real Tk, importer, worker pool and settlement; 4 files, direct and folder: at 60, 100 and 200 MB forced in memory (6 fallbacks each) and 100 MB on the real gate, all `SUCCEEDED` with the same bytes as the unlimited panel run; Cancel with one in memory and one waiting settled in 11.45 s; a starved queue of 8 settled in 6.97 s (wait 5 s), each file's one-line message saying why.

**Memory** (process tree, children included, peak private commit as well as working sets): assembling in memory now peaks **lower** than before, because output no longer doubles while it is read: 2 hours in one part 662 MB (993 MB at `e0aab03`), 4.6 hours 1,522 MB (2,281 MB). The budget is unchanged, so it is conservative here: 0.63 of it. Disk 26.8 MB at 4.6 hours against the 64 MiB budget, this process's part 12.7 MB against 24 MiB. HIGH-002A held: a long paragraph 71.0 MB (`e19527e` 1,357 MB) and a 2-hour clip 38.0 MB (1,001 MB), with the same SHA-256 as `e19527e`; and under a real 1,300 MB limit the paragraph completes, at 71.8 MB, where `e19527e` fails. Eight files on disk at once 229 MB.

**The same audio** (`runs/identity-result.json`): the review's own harness against its own results on `e0aab03`, config by config: **470 of 470 outputs identical in MP3 bytes and requests**, 280 on offline clips and 190 on 84 clips of real Edge audio (2 voices) recorded during R2. That includes a new config in which every paragraph file, chapter file and MP3 runs out of memory at its one in-memory export (70 outputs, 350 forced fallbacks). A 2-hour narration on the folder route and a 4.6-hour one on the direct route: memory and disk one SHA-256, the same as at `e0aab03`.

**Publication and concurrency:** the review's failure probes, with their two seams moved (`runs/chain2/07-p6.txt`): 47 of 49 as expected. The other two end acceptably: an output folder removed during assembly is made again and a complete file published, and a killed folder-route decoder is retried once and publishes a valid file. Real kills mid-assembly (`08-p9.txt`): no final name in any. 8 processes racing for one name, 12 rounds each (`09-p12.txt`): one winner without Overwrite, all complete with it, no bad payload, no staging left. Real HOME-PC panel, real Edge (`12-real-edge.txt`): 8 direct on Workers 8, peak 8, 8.42 s, 8 succeeded; 3 direct + 4 folder on Workers 4, peak 4, 9.47 s, 12 of 12 pairs overlapping; 8 direct forced to disk, peak 8, 7.98 s, the same durations; 4 + 4 with Cancel at 4 s, settled in 5.47 s with 4 valid files and no staging.

**Do the tests bite?** 78 of 78 mutants of this code caught, with a no-change control that passes with nothing skipped (`runs/chain2/13-mutations.txt`). They include the old hang itself, which `test_the_old_hang_is_what_this_test_would_see` also keeps as a permanent negative control: pydub back on the raw module, the same limit, and the hang must be seen with the stacks the review found. Survivors on the way found real gaps, now closed: tests that passed without the waiter ever waiting, Cancel behind a head that keeps waiting, the stall deadline with a failing cancel check, and one no-op (clearing frames the end of the `except` block had already released), which went. The control also caught a new test depending on the order of the tests before it.

**What tracing the leftovers found** (`664d8b6`). The first chain ran on `f29281d` and its matrix counted two scenarios with files left behind, which the test then filtered out by extension. Traced instead of explained away, they were a real defect: a failed pydub export leaves two temporary files, the first holding the whole narration as a WAV, and nothing else knows their names; and on the direct route that export's frames kept its output open, so Windows refused to delete the work folder. Both are fixed, a fallback now removes them before the disk route needs the room, and the test requires nothing at all to be left. The gate on `f29281d` was stopped on purpose and is not evidence; everything above is `664d8b6`.

**Gate:** the first on `664d8b6` **failed four tests**, none of them the known optional-voice ones and none a production defect (`files/dev-work/act070-remediation/verify/ACT071-R2-664d8b6-run1`, kept). The targeted runs had not reached them. A guard read the suffix gate of `run_conversion_job` by AST, and the remediation had moved it to `_convert`; the allow-list of production modules did not have the new `ffmpeg_watch.py`; and two new tests imported `runner` inside the test, where `test_epub_retirement`, which purges `tts.epub2tts_edge` and leaves a fresh copy in `sys.modules`, gave them a runner on another engine than the one the stub had patched. `b185186` corrects these in the two test files and changes no production file (`cmp` of the hashes with `runs/chain2/00-code-hashes.txt`), so the evidence above stands. No guard was loosened: the first now reads both functions and also requires the job to call `_convert`, with the same exact set, and the second puts one more module under the EPUB guards. Negative controls in the order the full suite runs them (`runs/gate-fix/controls.txt`): the inner import brought back, EPUB let through, `_convert` bypassed, the module off the list, a retired import in the new module, a work folder held open and a changed reason all fail; no change passes. The final gate, on `b185186`, **passed**: 13,200 passed, 65 skipped, nothing failed, none of the skips in `test_low_memory.py`, and the tree unchanged during the run (`files/dev-work/act070-remediation/verify/ACT071-R2-b185186-run1`).

### 14.5 Existing tests changed, and why

None was skipped or xfailed. `test_every_production_assembly_reads_the_gates_answer` became `..._goes_through_assemble_with_both_routes`, a stronger check of the new one path. `test_a_note_that_fails_never_leaks_the_reservation` now also requires the work to carry on: a deliberate change. The full-disk test now expects the named error. Cancel-during-the-wait tests now require the narration to be finished while the other file still holds its place, where they required it to wait. Four spies moved from `reserve` to `place`, two of them onto a private gate, because `monkeypatch` restores an attribute set on an instance by leaving the bound method there, which hid later patches of the class. One test's stubs had to allow for `MemoryError` now going on to disk.

### 14.6 What the review found, and what became of it

| Finding | Disposition |
|---|---|
| R2-1, the hang | **Fixed** (§14.1-14.4) |
| Blank `MemoryError:` | **Fixed**: named everywhere on both routes, and one line in the panel |
| Large files left after a kill | **Partly fixed.** A run now removes an interrupted run's `.tmp_chunks/<ours>`, in the tool's own output folder, only with this tool's exact name, its owner gone and untouched for the stale age. **Left, for the planned hardening:** `%TEMP%\epub2tts_*`, `tts_direct_*` and pydub's temporary files after the program itself is killed, up to about the size of the narration: not swept, because nothing here should delete from `%TEMP%` without an ownership design of its own |
| Disk-full wording, no check before starting | **Fixed**: named, with where and how much, and refused before starting when it can be seen not to fit. A real full disk is still injected |
| Serial starvation | **Fixed**: one deadline for the queue |
| Note under the gate's lock | **Fixed** |
| Empty `.tmp_chunks` | **Fixed** |
| Whole-file retry after a killed decoder | **Kept, bounded at 2**: a damaged clip is worth asking for again. A decoder out of memory is now local and is not |
| `NoAudioReceived` at 4 concurrent requests in R2's fetch | Recorded only: looks service-side, and not reproduced on any panel run here |
| Four optional-voice failures; Kokoro at 920x600 | Untouched, as instructed: pending hardening. This checkout has those voices installed, and all four passed in both gates here; a checkout without them should expect the four of §12.4 |
| CLI-only M4B `_run_ffmpeg` | Left unsupervised and recorded: `subprocess.run` with no pipes cannot deadlock this way, but it has no deadline. Not on the Edge routes |

### 14.7 Limits, stated

Allocation failure is real but confined to one process by a Job Object: a whole machine's commit was never exhausted, so what other programs do at that point is not observed. A full disk is injected. Second volume, exFAT, network drives and macOS were not exercised; on macOS memory is unreadable, so the gate assumes as before, and the watch and fallback are written for POSIX but unrun there. A long real book has not been run end to end, nobody has listened yet, and Kokoro, Chatterbox Turbo and Qwen3-TTS were not synthesised here: their modules are unchanged, one-worker dispatch is by test, and pydub's seam reaches their exports too, which adds only the stall deadline. The evidence chain ran on `664d8b6`, the last commit to change production code; the gate on `b185186`, which changes two test files on top of it.

### 14.8 What the owner will see differently

> **Superseded in v0.7.2 (owner instruction of 2026-11-04, plan `ACT-v0.7.2-Windows-Hardening-...`, Phase 1).** Cancel now stops
> every active file promptly, finished narration included: no assembly, encode, fallback, retry or publication after the latch,
> and nothing unfinished is saved. §9 step 7's original expectation ("the run ends Cancelled within a few seconds") is the
> contract again. The paragraph below is the v0.7.1 behaviour as it was measured and shipped, kept as history.

The steps of §9 stand. One expectation changes: Cancel on a long book whose narration is already finished no longer ends in a few seconds. It assembles that narration on disk and saves it, which takes as long as that takes, up to 10 minutes, or says in the log that it was not saved.

### 14.9 After v0.7.1

The owner's 50-question requirements consultation (hardening, verification gate, feature map, logging, metadata, M4B performance and more) is the next planning priority once v0.7.1 is accepted and merged. Source: `files/plans/reference-handoff-of-mc-answers/markdown-handoff-prompt-50-multiple-choice-questions-for-gpt-work-chat.md` (untracked, on HOME-PC only; register in its §4). None of it is in this work. Where its sequencing differs from this checkpoint, see `Handoff.md`.

## 15. Fresh independent Codex review brief (replaces §13)

Branch `feature/0.7.1-multi-file-workers`, from `c0896d8`. Production code last changed at `664d8b6`; `b185186` corrects two test files, and the gate ran on it; the commit after that is documentation only. This is the independent review that stands between the branch and the owner's acceptance. The previous one (R2, `e0aab03`) passed HIGH-001 and HIGH-002A and blocked HIGH-002B on R2-1, so weight the work toward R2-1 and what its fix touched, but reach your own verdict on all three. Verify independently of this plan's claims. The checkout needs its own Python environment with this repo's packages, a pinned FFmpeg pair and the NLTK data; a short path; and Git ownership for the user running it. Without the optional voices installed, expect the four failures of §12.4. A fresh clone has neither the ignored evidence nor the review's probes: on HOME-PC they are in the owner's checkout under `files/dev-work/act071-rem3/`, to be read, not changed. A targeted run should include `test_epub_retirement.py` and keep the suite's order: it purges `tts.epub2tts_edge` and leaves a fresh copy behind, and the first gate here failed on what targeted runs had missed.

1. **R2-1.** `files/tests/low_memory_probe.py` is the harness; `test_low_memory.py` the cases. Try other headrooms, a limit on the whole job, memory going at other moments. Does anything still hang? `test_the_old_hang_is_what_this_test_would_see` must keep seeing the hang when the seam is undone.
2. **Any FFmpeg outside the watch on these routes?** Any way for a reservation to stay held, or for a waiter not to be woken?
3. **The readings.** Is `ullAvailPageFile` right to use as it is, and is `_claimed` sound when synthesis is growing too?
4. **Cancel.** Each deadline in §14.3. Is anything finished discarded silently, or anything unfinished published?
5. **Not regressed:** HIGH-001, HIGH-002A, bytes (`r2-review-probes/p3_engine.py`), direct/folder/mixed overlap, pacing, headings, the "blank" handling, endings, filenames, Overwrite, one worker for the local engines.
6. **Not a finding, unless you disagree with the reasoning:** `%TEMP%` leftovers after a kill, CLI-only M4B `_run_ffmpeg` and the optional-voice failures (§14.6); and everything §13 listed.
