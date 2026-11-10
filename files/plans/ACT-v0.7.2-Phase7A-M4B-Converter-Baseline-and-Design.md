# ACT v0.7.2 Phase 7A — M4B Converter split: baseline, compatibility manifest and optimization design

Status: **Phase 7A checkpoint (profiling and design only). No production code changed.** Stops for the ChatGPT/owner
architecture review before Phase 7B. The budgets in §8 are proposals, not approved acceptance thresholds.

Authority: the owner's acceptance of Phase 6 at `721c323` and authorization of Phase 7A (2026-11-09; `Decisions.md`), and the
Phase 7A prompt (plan §12.1–12.3, §14 Phase 7, sub-checkpoint 7A). Issue: ACT72-012 (Major).

## 1. Identities

| What | Identity |
|---|---|
| Code under test | working tree at `7ff1439` (scripts unchanged since `35de76a`); the split path (`m4b_commands`, `m4b_plan`, `m4b_probe`, `m4b_winaudio`, `m4b_metadata`, `m4b_destinations`, `m4b_naming`, `ffmpeg_utils`, `output_paths`) is byte-identical to `204c33b`; `m4b_execution` adds only `prune_empty_folders` (ACT72-029) and the panel only messages (ACT72-018/027/028) |
| Compatibility reference | merged v0.7.1 `204c33b` (commit tree `2060dc7f`, `scripts` tree `67f2069d`), extracted read-only with `git archive` into the ignored evidence folder; the owner's checkout, `master` and the branch were not touched |
| FFmpeg (both sides) | 9.0.1 full_build (gyan.dev), the machine's pinned pair; ffmpeg SHA-256 `57c56e36…2d8a`, ffprobe `afe05347…7208`; handed to both code trees explicitly |
| Python | 3.12.10 (the project `.venv`), Tk on a withdrawn root |
| Machine | HOME-PC: AMD Ryzen 7 9800X3D (8 cores, 16 threads), 32 GB, Windows 11 Pro 10.0.26300, Balanced power plan, mains power, system drive a Samsung 990 PRO NVMe SSD |
| Load during the matrix | not idle: `explorer.exe` ≈ 3.7 cores and VS Code ≈ 1 core sustained, and the owner's other applications; each run records the machine's CPU load in the second before it starts (`matrix-progress.log`). Runs of each candidate alternate within every repetition, so both see the same background; the process tree's own CPU-seconds are reported beside wall time because they are far less sensitive to contention |
| Fixtures | 12 deterministic synthetic books from one recipe (`tools/fixtures.py` in the evidence folder, §12; SHA-256 `520af7ae…`): lavfi pink/brown noise plus tremolo tones per channel, AAC-LC by FFmpeg's native encoder, a 600×600 JPEG cover as `attached_pic`, five book tags, chapters with odd millisecond boundaries. Each validated before use: chapter count (no muxer truncation at 500/1,000/2,000), streams, rate/channels, duration, complete decode |

Fixture set: `route10` (10 ch, 66 s), `scale10` (10 × 1.5 s), `scale100`, `scale500`, `scale1000`, `scale2000` (≈1.5 s
chapters), `long6_48` (6 h, 48 × 7.5 min), `long12_24` (12 h, 24 × 30 min), and variants `noelst` (no edit list: priming kept
in the timeline), `mono22k` (22.05 kHz mono), `s48k` (48 kHz), `r96k` (96 kHz). All 44.1 kHz stereo 64 kbps unless named.

## 2. The split path as it runs

Per book, once: one ffprobe (`-show_format -show_streams -show_chapters`, `m4b_probe.probe_source`), a frozen plan (names,
spans, tags, cover, decoder route), one reserved run folder.

Per chapter, sequentially on the worker thread (`m4b_converter._run_conversion` → `m4b_execution.convert_segment`):

| Step | Process | What it costs |
|---|---|---|
| audio pass (`segment_argv`) | 1 FFmpeg | start a process, open the book and parse its index, **decode from 0 to the chapter start and discard it** (output-side `-ss`), decode and encode the chapter (`libmp3lame -q:a Q`) |
| cover pass (`attach_artwork_argv`), Preserve/Replace with a cover | 1 FFmpeg | start, open the MP3 and the book, stream-copy both |
| measurement (`measured_duration`) | 1 ffprobe | start, read the MP3 header |
| staging and publication | none | 2–3 temporary siblings, a drift check, `os.replace` |

So a covered chapter costs three child processes (each with its own `conhost.exe` on Windows: the job counts six), a Strip
chapter two. The Windows xHE-AAC route (`windows_decode`) is different already: one Media Foundation decode per book feeds
every chapter's encoder through a pipe (`PcmTimeline` → `run_argv_streaming` → `pcm_argv`), so it has no prefix term.

## 3. ACT72-012 reproduced and attributed

Every production chapter costs a fixed part (process starts, opening the book, the cover pass, the measurement) plus its own
decode and encode, plus **the decode of everything before it**, thrown away. Fitting each chapter's wall time against its
start (least squares, the first production run of each tier):

| Book | Production: s per hour of prefix | Per-chapter median by quarter of the book (first → last) | C1: s per hour | C1 quarters |
|---|---|---|---|---|
| 6 h, 48 × 7.5 min | **1.42** | 4.1, 5.7, 7.9, 10.3 s | −0.01 | 3.1, 3.4, 2.8, 3.1 s |
| 12 h, 24 × 30 min | **1.56** | 12.5, 17.0, 21.6, 26.8 s | −0.04 | 11.5, 11.2, 11.3, 11.0 s |
| 1,000 × 1.5 s (25 min) | **1.42** | 0.30, 0.40, 0.55, 0.68 s | 0.16 | 0.20, 0.20, 0.15, 0.20 s |
| 500 × 1.5 s | 1.30 | 0.20, 0.25, 0.34, 0.39 s | −0.36 | 0.15, 0.15, 0.15, 0.15 s |
| 1,000, Write none | 1.31 | 0.19, 0.29, 0.44, 0.54 s | −0.25 | 0.09, 0.09, 0.09, 0.09 s |

The slope (1.3–1.6 s per hour of prefix, every chapter) matches the decode rate measured directly: a complete decode runs at
≈2,600–2,800× realtime here (6 h in 7.75 s, 12 h in 16.5 s), i.e. ≈1.3–1.4 s per hour; the `m4b_commands` docstring recorded
1.55 s/h on another build and machine. Summed over a book the prefix term is ≈ N·D/2 of decoding: on the 6-hour book about
200 s of a 337 s run, on the 12-hour book about 215 s of 470 s, on the 1,000-chapter book about 300 s of 653 s (the
rest there is per-chapter process overhead).

**Other contributors, measured (median per chapter, production):**

| Step | Small book | 6 h book | 12 h book | Grows with |
|---|---|---|---|---|
| audio pass (prefix + chapter decode + encode) | 0.04–0.08 s | 6.5 s | 19.2 s | chapter start (prefix) and length |
| cover pass (stream copy; re-opens the book) | 0.03 s | 0.10 s | 0.22 s | **book size** (re-parses the book's index each chapter) |
| ffprobe measurement of the output | 0.03 s | 0.03 s | 0.03 s | nothing |
| preflight probe of the book (once) | 0.03 s | 0.06 s | 0.10 s | book size, once per book |
| harness-visible worker overhead outside chapters | ≤ 0.3 s | ≤ 3 s | ≤ 3 s | — |

Process starts dominate short chapters: a covered chapter runs three children (six processes with their `conhost.exe`), and on
this machine under its background load each start costs tens of milliseconds and varies widely. Write none (no cover, no tags)
saves about 0.15 s per chapter (1,000 chapters: 499 s instead of 653 s).

## 4. Raw figures and comparisons

The real Converter panel ran each book headless in its own process (`tools/bench_run.py`), in a Windows Job Object that counts
every child; A = production, C1/C2 = the benchmark prototype of candidate C (§6). All runs succeeded; every source's SHA-256
was unchanged afterwards; no staged temporary was left behind. "Identical" means every output byte-identical to the first
production run of the same book and settings.

**Matrix** (`analysis.json`; 77 runs, interleaved, under the background load described in §1):

| Book | Route | Runs | Wall median (min–max) | Process-tree CPU | Peak job commit | Peak staged | Heartbeat p99 / max | Identical |
|---|---|---|---|---|---|---|---|---|
| route10 (10 ch, 66 s) | A / A at `204c33b` / C1 / C2 | 5 each | 2.42 / 2.56 / 2.46 / 1.66 s | 2.05 / 1.94 / 1.86 / 1.48 s | 52 / 52 / 78 / 78 MB | 0.3 MB | ≤0.76 / ≤1.24 s | yes / yes / yes / **no** |
| route10, whole book | A | 5 | 0.74 s | 0.59 s | 52 MB | 1.3 MB | 0.14 s | yes |
| scale10 (10 × 1.5 s) | A / ref / C1 | 5 each | 1.81 / 2.84 / 3.52 s | 1.53 / 1.53 / 1.77 s | 51 / 52 / 77 MB | 0.1 MB | ≤0.51 / ≤1.29 s | yes |
| scale100 | A / ref / C1 / C2 | 3 each | 37.7 / 38.7 / 31.6 / 15.8 s | 19.0 / 19.4 / 14.8 / 10.4 s | 55 / 55 / 80 / 79 MB | 0.1 MB | ≤0.13 / ≤1.8 s | yes, yes, yes, **no** |
| scale500 | A / ref / C1 | 2 / 1 / 2 | 215 / 224 / 129 s | 179 / 182 / 76 s | 64 / 64 / 92 MB | 0.2 MB | ≤0.11 / ≤0.29 s | yes |
| scale1000 | A / C1 | 2 each | 653 / 322 s (**2.03×**) | 580 / 175 s | 77 / 107 MB | 0.2 MB | ≤0.11 / ≤1.9 s | yes |
| scale1000, Write none | A / C1 | 1 each | 499 / 192 s (**2.60×**) | 505 / 103 s | 69 / 93 MB | ≤0.2 MB | ≤0.09 / ≤1.34 s | yes |
| long6_48 (6 h, 48 ch) | A / C1 | 2 each | 337 / 151 s (**2.22×**) | 435 / 183 s | 148 / 218 MB | 17 MB | ≤0.03 / ≤0.29 s | yes |
| long12_24 (12 h, 24 ch) | A / C1 | 1 each | 470 / 271 s (**1.73×**) | 599 / 358 s | 251 / 370 MB | 69 MB | ≤0.02 / ≤0.15 s | yes |

**Quieter-period repeats** (`runs/quiet`, `runs/stall`; load before each run recorded, median 15 %):

| Book | A | A at `204c33b` (noise floor) | C1 | C2 |
|---|---|---|---|---|
| route10, 10 runs each | 2.554 s (CPU 2.07) | 2.544 s (CPU 1.91) | 2.412 s (CPU 1.86): −5.6 % | — |
| scale10, 10 runs each | 1.853 s (CPU 1.41) | 1.936 s (CPU 1.41) | 2.307 s (CPU 1.56): **+24 %** median, +14 % fastest-to-fastest | — |
| scale100, 2–3 runs each | 18.9 s; later 35.2 s as load returned | — | 15.0 s; later 31.4 s | 15.2 s at the later load |

**Behaviour under fault** (production and C1 alike):
* Cancel pressed after 400 of 500 outputs: settled in 1.75 s (A) and 1.04 s (C1); no file left; the book's folder pruned.
* An audio FFmpeg killed mid-chapter (6 h book, chapter 3): the chapter is refused, the book taken back, the run
  COMPLETED_WITH_FAILURES; Retry Failed then succeeds (320 s A, 131 s C1) and all 48 files equal a clean run, byte for byte.
* C1's continuous decoder killed after 50 of 100 outputs: the in-flight chapter is refused, the book is taken back, Retry
  Failed succeeds, all 100 files identical. The decoder's exit status is checked at end of stream, so a dead decoder is never
  mistaken for the end of the book.

**Process counts per output** (children started by the worker; `conhost.exe` not counted): A 3.0 with a cover (audio, cover,
measurement), 2.0 under Write none; C1 the same per output plus one decoder per book (and one extra ffprobe in the prototype
that production would not need); C2 2.0.

**Memory.** No route buffers audio: A holds none; C1 holds one 256 KiB block and a one-second tail (≈350 KB at 44.1 kHz
stereo float). What grows with the book is FFmpeg's own index of it: the largest single process peaked at 223 MB commit on the
12-hour book on both routes. C1's job peak is higher (370 MB against 251 MB there) because its decoder holds the book open
while each chapter's cover pass opens it again.

**Disk.** C1 adds nothing: peak staged bytes equal A's (two MP3s of one chapter at most: 69 MB for a 30-minute chapter).

**Unexplained outlier.** One C1 matrix run (100 chapters, a kill that missed) shows the whole harness process idle for
25.9 s outside chapter work, with a 25.7 s gap in the UI heartbeat; its chapters themselves were normal. Five reruns of the
same configuration with a stall timeline showed no stall above 0.25 s, and no other C1 or A run comes close (worst A 1.9 s).
The cause is not established; it is listed for 7B (§9) rather than explained away.

## 5. Compatibility manifest (frozen from production output)

Reference: production code at `204c33b` (contained `git archive`, tree `2060dc7f`) and the working tree, run through the real
Converter panel by `tools/bench_run.py` with FFmpeg 9.0.1 (gyan full build, ffmpeg SHA-256 `57c56e36…`, ffprobe `afe05347…`),
Python 3.12.10, on the validated fixtures in `fixtures/manifest.json`. Every property below was read from produced files
(ffprobe, mutagen, raw bytes) or from the code path that produced them, not from intent.

**Classification: byte identity is stable and is the oracle.** Repeated production runs produced byte-identical MP3s on every
fixture, and `204c33b` matched the working tree byte for byte on the four fixtures compared (route10, scale10, scale100,
scale500) (§4). A
faster route must reproduce every output byte for byte wherever it applies; where it cannot, that case stays on today's route.

| Property | Production behaviour (measured) |
|---|---|
| Container / extension | MP3 elementary stream, `.mp3`. MPEG-1 Layer III at 32/44.1/48 kHz; MPEG-2 Layer III at 22.05 kHz (mono22k). First frame is a Xing frame written by FFmpeg's mp3 muxer, carrying an encoder tag `Lavc63.1.` with encoder delay 576 and the end padding. |
| Codec and encoding | `libmp3lame`, VBR `-q:a <Quality>` (default 2; 0–9 from the panel), `-threads 0`. No bitrate, no resampling option, no filters. |
| Sample rate / channels | The source's rate and channel count when LAME supports the rate (44.1k, 48k, 22.05k measured); otherwise FFmpeg's negotiated rate (96k source → 48k output), resampled on the continuous stream **before** the chapter is cut. Mono stays mono, stereo stays stereo. |
| Chapter count and order | One MP3 per source chapter, in source order (10, 100, 500, 1,000 measured; 2,000-chapter fixture validated). A chapterless book in split mode is one whole-book file (existing contract). |
| Audible boundaries | Chapter *k* is exactly decoded samples `[half_up(S·rate), half_up(S·rate) + half_up(D·rate))`, with `S = "{:.6f}"` of the probed chapter start and `D = "{:.6f}"` of `end − start`, each parsed to integer microseconds (226 chapters on six fixtures, exact sample equality: `selection-probe.jsonl`). Decoding always starts at source time 0 (output-side seek), so every kept sample is fully reconstructed. No gaps or overlaps between consecutive chapters on any fixture (`boundary-model.txt`); a rounding overlap or gap of one sample is possible in principle and must be reproduced, not "fixed". |
| Priming and timeline | With an edit list (FFmpeg-muxed AAC) the decoder's priming is removed and sample 0 is the first real sample. Without one (`noelst`) the 1,024 priming samples are part of the timeline and open chapter 1. MP3 gapless metadata (delay 576 + padding) decodes each chapter back to exactly its sample count (6.000000 s = 264,600 samples measured). |
| Artwork | Preserve and Replace keep the book's attached picture: each chapter is encoded audio-only, then a second FFmpeg pass stream-copies the audio and the picture (`attach_artwork_argv`), giving an ID3v2.3 `APIC` (mjpeg 600×600 here). Write none (Strip) writes no picture. Whole-book mode attaches the picture in its single pass. |
| Metadata | ID3v2.3 when any tag or chapter map is written: Preserve → `TIT2` chapter title, `TPE1`, `TPE2`, `TALB` from the source's allowlist, `TRCK` chapter order, `TSSE Lavf63.1.101`; Replace → typed fields (blank fields absent), `TIT2` chapter title, `TRCK`; Strip → ID3v2.4 header holding only FFmpeg's `TSSE` (FFmpeg's own encoder tag; the Converter writes nothing). Split outputs carry no chapter map. |
| Filenames and layout | `<base>/M4B-Converter-Outputs/M4B-Converter-N/<source stem>/NN - <sanitised chapter title>.mp3`; `NN` zero-padded to `max(2, digits(total))`; `:` and other unsafe characters sanitised (`Chapter 1_ Opening`); non-ASCII kept (`Café`). |
| Publication | Each pass writes a `.act-tmp-…` sibling in the chapter's own folder (plus a `.act-tmp-ffmpeg…log`), then ffprobe measures the result; more than 3 % from the planned span (above 1 s) is refused; an existing destination is refused, never replaced; `os.replace` publishes. Peak staged bytes are a chapter's MP3 or two (measured in `analysis.json`). |
| Collisions | Names are planned once at preflight by one run-wide planner (case-insensitive, `-1`, `-2` suffixes); the run folder number is reserved atomically. Unchanged by any audio route. |
| Cancel | Stops the running FFmpeg (terminate, kill, reap) within the 50 ms poll; the interrupted book's finished chapters are removed and its empty folders pruned (since v0.7.2 ACT72-029; `204c33b` leaves the empty folder); earlier books are kept; the run settles CANCELLED. Pause takes effect between outputs. |
| Retry Failed | A failed book (for example, a killed FFmpeg) is retryable; Retry re-runs that book from its first chapter at the frozen names, with no new probe, plan or folder; the result merges into the run. |
| Source preservation | Sources are never written (`assert_not_input`); every run's results record each source's SHA-256 after the run, compared with the fixture manifest. |

**What a faster route must not change:** any byte of any output where it applies; the Xing frame (a single-pass cover encode
changes its size: candidate C2); the encoder, quality or `-threads` setting; the PCM LAME receives (format, rate, first and last
sample); the separate cover pass; validation (ffprobe measurement and drift guard); staging, refusal and publication; Cancel,
Pause and Retry semantics; names, folders and collision handling.

## 6. Candidate designs

All candidates are judged against the frozen compatibility manifest (§5): byte identity where the
route applies, today's route everywhere else. Numbers marked *measured* come from §4; *estimate* is reasoning.

### A — today's route (reference)
Per chapter: one FFmpeg that opens the book, decodes from 0 to the chapter start and discards it (output-side `-ss`), decodes
and encodes the chapter; one FFmpeg cover pass when a cover is kept; one ffprobe of the result. Correct by construction
(every sample fully reconstructed) and pinned by tests. Cost grows with each chapter's start: the prefix decode term summed
over a book is ~N·D/2 of decoding.

### B — remove redundant work, keep the command shapes
Looked for: repeated probes of the source (none: one preflight probe per book, frozen), repeated chapter/metadata work
(none: frozen plan), per-chapter ffprobe of the output (it *is* the validation; removing it is forbidden), the cover pass
re-opening the book (a few tens of milliseconds; replacing its input with an extracted image is a byte-identity risk for a
small gain), per-pass log temp files (microseconds). B cannot touch the prefix term, which is the defect. Verdict: no change
worth its risk on its own; its small items are listed for 7B only where they come free.

### C — one continuous decode per book, exact per-chapter PCM into the existing encoders
One FFmpeg decodes the whole book once to the AAC decoder's own float samples (`pcm_f32le`, exact); the worker cuts chapter k
as `[half_up(S·rate), +half_up(D·rate))` (the measured output-side-seek selection) and pipes it into one FFmpeg per chapter
that encodes it with the same encoder settings through the existing `pcm_argv` + `run_argv_streaming` seams.
* **C1** keeps the separate cover pass: byte-identical to production on every eligible fixture (*measured*).
* **C2** maps the cover in the encode itself (one process less per chapter): audio frames, tags and decoded samples identical,
  but the leading Xing/Info frame is 208 bytes instead of 522, so files are not byte-identical (*measured*). Owner's call.
* Eligibility (frozen at preflight from the one existing probe): FFmpeg-decoded (not the Windows route), `sample_fmt` fltp,
  sample rate one LAME accepts natively, 1–2 channels with a standard layout, `time_base` 1/rate and `start_pts` 0. Anything
  else stays on A (a 96 kHz source is not byte-identical under C because production resamples the continuous stream before it
  cuts: −100 dB RMS, *measured*).
* Backstops: the decoder's exit status is checked at end of stream (a killed decoder fails the chapter; the book is taken back
  and Retry Failed works: *measured*); the decoded total should equal the probed `duration_ts`; a short feed before the end
  fails the chapter; the drift guard is unchanged.
* Memory: one 256 KiB block plus a one-second tail (≈350 KB) in the worker; the decoder blocks on its pipe (back-pressure).
  Disk: unchanged from A (no spool).
* Cancel: the running encoder is stopped as today; the decoder must also be stopped and reaped (one more owned process).
* Retry: unchanged contract (the whole book again, a fresh decoder).

### D — owned PCM spool (whole book or per chapter)
Decode once to a temporary PCM file, then encode chapters from it. Exactness needs float32 (s16 would change what LAME
receives): a 12-hour stereo 44.1 kHz book is ~15.2 GB of spool; a per-chapter spool is bounded by the longest chapter
(30 min ≈ 635 MB; a 10-hour chapter ≈ 12.7 GB). No speed advantage over C (C already streams; D adds write+read I/O); it adds
disk preflight, cleanup and ownership of very large temporaries. It would only pay if single chapters had to be re-encoded
independently, which no current contract asks for. Verdict: rejected.

### E — reuse the existing streaming seams
The Windows xHE route already decodes once and cuts PCM (`m4b_winaudio.PcmTimeline` → `run_argv_streaming` → `pcm_argv`).
C1 reuses `pcm_argv` and `run_argv_streaming` unchanged. `PcmTimeline` itself is not reusable as is: it is fed by Media
Foundation (Windows-only, xHE-AAC-only, 16-bit), and it cuts by accumulating rounded chapter *durations*
(`bytes_for(end − start)`), which drifts from absolute sample positions by up to half a sample per chapter; C must cut at
absolute positions to match A. So E is realised inside C1 as "same seams, FFmpeg-fed timeline with absolute cuts", not by
routing AAC through Media Foundation.

### Side by side

| Criterion | A (today) | B (redundancy only) | C1 (one decode, cover pass kept) | C2 (one decode, cover in encode) | D (PCM spool) | E (existing seams) |
|---|---|---|---|---|---|---|
| Speed (measured / estimated) | reference | ≈0–3 % (no redundant probe exists) | 2.2× 6 h/48 ch, 2.0× 1,000 ch, 1.7× 12 h/24 ch, 2.6× Write none (*measured*) | C1 plus ≈2× more on many short chapters (100 ch: 15.2 vs 31.4 s, *measured*) | ≤ C1, plus spool write/read I/O (*estimate*) | is C1's mechanism |
| PCM / sample boundaries | defines them | unchanged | identical samples (226/226 chapters; byte-identical files) | identical samples | identical if float32 | identical only with absolute cuts (`PcmTimeline` accumulates rounded durations) |
| Priming and timestamps | decoder from 0; edit list honoured | unchanged | same decode from 0; needs `start_pts` 0, `time_base` 1/rate and no timestamp gaps (eligibility) | as C1 | as C1 | as C1 |
| Codec and quality | libmp3lame VBR q | unchanged | same encoder, settings, input format | same encoder; Xing frame differs | same if float32 | same |
| Peak memory / disk | per-process FFmpeg index; staged 2 chapter MP3s | unchanged | +1 process holding the book (+47 % job peak at 12 h); audio ≈0.6 MB; disk unchanged | as C1, one process fewer per chapter | spool up to 15 GB per 12 h book | as C1 |
| Windows decoder coverage | MF route already one-decode | unchanged | AAC-LC via FFmpeg only; MF route untouched | as C1 | either decoder | MF route is the model, not reused for AAC |
| Cancel / retry complexity | one child per pass | unchanged | one more owned process (decoder) to stop and reap; retry = fresh decoder (*measured* both) | as C1 | spool ownership and cleanup | as C1 |
| Cleanup / publication safety | staged siblings, atomic publish | unchanged | unchanged publication; decoder exit status checked at end of stream | unchanged publication | adds large owned temporaries | unchanged |
| Byte identity | — | yes | **yes** | **no** (Xing frame) | yes if float32 | yes when cut at absolute positions |

### Not candidates
* Moving `-ss` before `-i`: forbidden without new proof on the original priming corpus; C1 needs no seek at all.
* Stream-copying AAC into `.mp3`, changing VBR quality, dropping the cover or the validation: forbidden.
* Running hundreds of encoders in parallel: forbidden. (A small fixed pipeline, decoder alongside one encoder, is what C1 is.)

## 7. Recommended smallest safe optimization (for review; not implemented)

**Candidate C1: one continuous FFmpeg decode per eligible book, cut into exactly the samples today's output-side seek
selects, each chapter encoded through the existing PCM seams; everything after the audio pass unchanged.**

* **Route choice, frozen at preflight** in the `ItemPlan` (as `windows_decode` is), from the one probe that already runs:
  FFmpeg decodes it (not the Windows route, no `aac_at`), AAC-LC, `sample_fmt` fltp, a sample rate LAME takes natively
  (8, 11.025, 12, 16, 22.05, 24, 32, 44.1, 48 kHz), mono or stereo, `time_base` 1/rate and `start_pts` 0, split mode, and long
  enough to pay (a size threshold calibrated in 7B; output bytes are the same either way, so the threshold is invisible).
  Everything else keeps today's route, byte for byte, including its pinned `-ss`-after-`-i` command.
* **The cut** uses integer microseconds exactly as FFmpeg parses the production `"{:.6f}"` strings, rounded half up, at
  absolute positions (not accumulated durations); a one-second tail serves a rounding overlap and a gap is read and dropped.
* **Transport** is `pcm_f32le` (the AAC decoder's own float samples, exact) through `m4b_commands.pcm_argv` and
  `m4b_execution.run_argv_streaming`, which the Windows route already uses; the cover pass, the ffprobe measurement, the drift
  guard, refusal and publication are untouched.
* **Safety:** the decoder's exit status is checked at end of stream and the decoded total is compared with the probed
  `duration_ts`; a short feed fails the chapter, which takes the book back as today; Cancel stops and reaps the decoder as
  well as the encoder; Pause still waits between outputs; Retry Failed re-runs the book with a fresh decoder.
* **Expected effect** (prototype, same session): 2.2× on a 6-hour 48-chapter book, 2.0× on 1,000 chapters, 1.7× on a 12-hour
  24-chapter book, 2.6× on 1,000 chapters under Write none; per-chapter cost no longer grows with position; no extra disk;
  ≈0.6 MB of audio buffered; one more process per book.
* **Not recommended for 7B by default: C2** (the cover in the same encode). It halves C1's time again on many short chapters
  (100 chapters: 15.2 s against 31.4 s), with identical tags, identical audio frames and identical decoded audio, but every
  covered file's leading Xing/Info frame is 208 bytes instead of 522, so the files are not byte-identical. That is the
  owner's call under the 18A amendment, and it can follow C1 later on its own evidence.
* **Not pursued:** attaching the cover from an extracted image (a stream-copy extraction did not reproduce the picture; the
  book-size-dependent part of the cover pass is under 2 % of C1's time on the 12-hour book); a PCM spool (candidate D).

## 8. Proposed frozen performance budgets (calibrated proposals, not approved)

Measured in the same session, production and candidate interleaved, at least three runs each (ten for small books), with an
A-against-A control establishing the noise floor and the machine's load recorded; wall time and process-tree CPU both.

| # | Budget | Plan §12.3 starting point | Proposed after measurement | Prototype measured |
|---|---|---|---|---|
| T1 | Throughput, prefix-dominated long book (6 h, 48 chapters, cover, Preserve) | ≥ 2× | **≥ 2.0× median wall and CPU** | 2.22× wall, 2.38× CPU |
| T1b | Throughput, 1,000 short chapters (cover, Preserve) | ≥ 2× | **≥ 1.8× wall, ≥ 2.0× CPU**: process starts that C1 does not remove dominate here | 2.03× wall, 3.32× CPU |
| T2 | Small books | ≤ 10 % median slowdown beyond noise | **Books below the size threshold take today's route (no change by construction); above it, ≤ 10 % median slowdown on a 66-s 10-chapter book** | route10 −5.6 %; a 15-s 10-chapter book was +24 % on C1, which is why the threshold exists |
| T3 | Growth with position | none attributable to the prefix | **slope ≤ 0.1 s per hour of prefix; last-quarter / first-quarter per-chapter median ≤ 1.15** (6 h and 12 h books) | slope −0.01 / −0.04; ratio 1.01 / 0.96 (A: 1.42 / 1.56 s/h; 2.5 / 2.1) |
| T4 | Memory | buffering bounded independently of duration | **audio held by the route ≤ 1 MiB at any duration; no PCM on disk; job peak commit ≤ production's + one more open of the book by FFmpeg** | ≈0.6 MB; 370 vs 251 MB at 12 h (the decoder's FFmpeg index) |
| T5 | Disk | — | **peak staged bytes no higher than production's** | equal |
| T6 | UI | — | **heartbeat p99 ≤ 0.25 s and no stall over 2 s attributable to the route** across the qualification set | p99 ≤ 0.12 s; one unexplained 25.7 s stall not reproduced (§9) |
| T7 | Cancel | — | **settled ≤ 2 s after Cancel with every owned process reaped** | 1.04 s |
| T8 | Compatibility | unchanged output contract | **every output byte-identical to production on every eligible fixture and mode; ineligible books unchanged** | met on every eligible run |

Adjustments made, and why, before any implementation: T1b lowers the 2× bar to 1.8× wall for very many short chapters,
because there each chapter's three process starts (unchanged by C1, removable only by C2's byte change) are most of the
cost; T2 meets "no small-job regression" by routing rather than by tolerance, because the prototype's fixed per-book cost is
a measurable share of a 15-second book; T4 restates "bounded memory" as bounded *audio* buffering, because FFmpeg's own index
of a book grows with its length on both routes. These thresholds are not to be moved after a failed acceptance run.

## 9. Unresolved decoder and platform qualification

* **Windows Media Foundation (xHE-AAC):** not exercised. No xHE-AAC source can be made with the tools on this machine;
  qualifying it needs a lawful owner-provided sample. The design does not touch that route (it already decodes once).
* **HE-AAC / HE-AAC v2, ALAC, MP3-in-M4B, multichannel, rates LAME does not take (96 kHz measured: differs at −100 dB),
  sources with timestamp gaps:** kept on today's route by the eligibility rule; HE-AAC is excluded only because no fixture
  could be made, not because it is known to differ.
* **FFmpeg builds:** only the machine's pinned 9.0.1 full build. Byte identity between the routes holds per build and must be
  re-proven on whatever build is pinned (including the app-local portable build of a fresh setup).
* **Content:** synthetic noise and tones only; real narration encodes faster or slower than this, so absolute times will
  differ (ratios should not much). An owner-selected lawful book is optional supplementary evidence.
* **macOS** (`aac_at`), Windows 10, non-default DPI: not run. The Tk root was withdrawn, so painting costs are not in the
  heartbeat figures.
* **The 2,000-chapter fixture** is validated (no chapter truncation) but was not converted, to keep the session bounded.
* **Load:** the matrix ran beside a busy desktop (`explorer.exe` ≈ 3.7 cores, VS Code, a game); ratios and CPU-seconds are
  robust to that, absolute wall times are not. 7B's qualification should run in a quiet session.
* **The 25.7 s stall** seen once in a C1 run is unexplained; 7B must instrument and re-run before claiming T6.

## 10. Owner decisions needed before Phase 7B

1. Approve C1 as the design (§7), with its eligibility rule, the size threshold and today's route kept for everything else.
2. Approve amending `ACT.CONVERTER.PRIMING`, whose contract says every chapter command puts `-ss` after `-i`: the new route
   has no seek; its contract would be "exactly the samples the output-side seek selects, files byte-identical", while today's
   route keeps the existing contract and tests.
3. Approve byte identity as the compatibility oracle for eligible books (the manifest's classification).
4. Decide C2: leave it out of 7B (recommended), or accept the Xing-frame difference for the extra speed on short chapters.
5. Approve or adjust the budgets T1–T8, including T1b's 1.8× and T2's routing.
6. Approve implementing the gate's reserved `m4b-scaling` qualification scenario in 7B from this harness and fixture recipe
   (large fixtures generated on demand, about 1.1 GB; roughly an hour and a half of machine time per qualification run).
7. Optionally provide lawful xHE-AAC / HE-AAC samples, or accept those as unqualified for the new route (they stay on today's).

## 11. Phase 6 acceptance and commits

* Starting SHA `721c3237` (Phase 6 closeout, equal to `origin`).
* `7ff1439`: the owner's acceptance of Phase 6 at `721c323` recorded in `Decisions.md`, `Handoff.md` and `Briefing.md`
  (documentation only; the full Windows gate PASS on `35de76a`, `2026-11-09_170309_full_7178`, carried forward under §13.3;
  no gate ran on `721c323` or `7ff1439`). The owner also accepted the `work_area.py` cleanup-guard exception, deferred
  ACT72-030 to a later maintenance release (open and tracked), kept the five cross-tool differences, and confirmed the
  crimson-audiobooks `.gitignore` line as their own.
* The Phase 7A checkpoint commit carries this record, the feature-map and issue-ledger notes and the canonical documents. No
  application source, test, fixture or gate tool changed, and no gate ran for this checkpoint (as instructed).

## 12. Evidence, reproduction and cleanup

Evidence is in the ignored run folder `files/dev-work/verification-gate/outputs/2026-11-09_phase7a_375a/` (not in Git; the
figures above are copied from it): `LEDGER.md`; `tools/` (`fixtures.py`, `bench_run.py`, `winjob.py`, `proto_c.py`,
`selection_probe.py`, `attrib.py`, `matrix.py`, `analyze.py`, `quiet_small.py`, `followup.sh`); `fixtures/` and its
`manifest.json`; `runs/{matrix,quiet,stall,ident,attrib-long6_48,attrib-scale1000,smoke-*}/*/results.json` (every run's
timings, child processes, CPU, commit, heartbeat, staged bytes, source hashes and output hashes); `analysis.json` and
`analysis.md`; `selection-probe.jsonl`; `boundary-model.txt`; `identity-small.txt`; `compatibility-manifest.md`;
`design-candidates.md`; `system-info.json`; `matrix-progress.log` and `quiet-progress.log` (load before every run);
`entry_state.json`, `final_state.json`, `protected-compare.txt`; `cleanup-manifest.json`; `downloads-mistake-cleanup.json`.

Reproduce (from the repository root, with the project interpreter and the pinned FFmpeg):

```text
git archive 204c33b scripts | tar -x -C <evidence>/ref-204c33b
python <evidence>/tools/fixtures.py --ffmpeg <ffmpeg.exe> --out <evidence>/fixtures route10 scale10 scale100 scale500 scale1000 scale2000 long6_48 long12_24 mono22k s48k r96k noelst
python <evidence>/tools/selection_probe.py --ffmpeg <ffmpeg.exe> --fixture <evidence>/fixtures/route10.m4b
python <evidence>/tools/bench_run.py --code scripts --ffmpeg <ffmpeg.exe> --source <evidence>/fixtures/long6_48.m4b --route a --out <evidence>/runs/<label> --hash-outputs
python <evidence>/tools/bench_run.py --code <evidence>/ref-204c33b/scripts ... --route a        (the v0.7.1 reference)
python <evidence>/tools/bench_run.py --code scripts ... --route c1 | c2                          (the benchmark prototype)
python <evidence>/tools/matrix.py ; python <evidence>/tools/analyze.py
python <evidence>/tools/attrib.py --code scripts --ffmpeg <ffmpeg.exe> --fixture <evidence>/fixtures/long6_48.m4b --chapters 0,12,24,36,47 --reps 3 --out <evidence>/runs/attrib-long6_48
```

The tools stay out of Git for this checkpoint: several standing tests police files under the gate folder, and this
checkpoint runs no gate. Phase 7B should promote the fixture recipe, the harness and the oracles, with tests, into the gate's
reserved `m4b-scaling` qualification scenario.

**Containment incident (corrected).** The first smoke run wrote its 10 MP3s into the owner's
`Downloads\Audiobook-Creation-Tool-Outputs\M4B-Converter-Outputs\M4B-Converter-1`: the panel reads the output base from the
live configuration at Start, which the first harness did not set. Exactly those 10 files (matched by SHA-256 to the run's own
record) and the three folders the run had created were removed with `rmdir` only; the pre-existing
`Audiobook-Creation-Tool-Outputs\TTS-Audiobook-Outputs` was not touched (only its parent's modified time changed). The harness
now sets the base through the app's own preference in a redirected settings file, checks it, and refuses any reservation
outside its own folder; no later run wrote outside the evidence folder.

**Cleanup.** 348 bulky outputs of the long runs and the fixture generator's intermediates (4.75 GB) were removed from the
evidence folder (their hashes remain in each `results.json`; `cleanup-manifest.json`); the folder now holds 1.4 GB, mostly
the validated fixtures kept for 7B. No staged temporary, FFmpeg or ffprobe process was left. The owner's protected state
(14 tracked deletions, 4 untracked entries, `bfa7`, the 31 legacy `epub2tts_*` folders, settings, crimson-audiobooks,
Audiobooks-(LIVE)) matches entry exactly (`protected-compare.txt`).
