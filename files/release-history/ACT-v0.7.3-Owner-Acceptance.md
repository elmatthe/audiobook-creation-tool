# ACT v0.7.3 — owner acceptance PASS; merge and Windows packaging authorized

2026-11-12, HOME-PC. Base `origin/master`: `ec79dba358e7a6fa84c90fe44595b9222742a834`.
Branch: `feature/0.7.3-m4b-chapter-recovery`. Candidate identity: 0.7.3.
Resolve the exact candidate commit with `git rev-parse HEAD` in the hotfix worktree;
the local verified launcher records and enforces the committed identity.

## Owner acceptance and authority (2026-11-12)

**Owner-reported PASS**, on application commit
`a2cc65d3f498b5d5fd886c0c01c8780d1e1d6d3b`, using the verified window
`ACT v0.7.3 CANDIDATE | a2cc65d`. The owner confirms the previously failing real
book was recognized through all 33 recovered Nero chapters and its full GUI
conversion succeeded. Multiple additional audiobooks also converted successfully
to chapterized MP3 files. These are the owner's results, separate from the earlier
independent automated evidence below; no new timing or listening checks are claimed.

The earlier failed owner attempt used the original v0.7.2 setup launcher. That
launch-selection problem was resolved through the verified candidate workflow;
no additional production fix was needed. Subsequent bounded native GUI preflight
verified worker module paths, identical probe/planner reports, 33 valid spans,
the recovery message and isolated outputs, then cancelled before encoding.
Nine private runtime guard tests passed. Private evidence remains untracked.

The owner explicitly authorizes administrative closeout, merging PR #15 into
**master**, updating README for v0.7.3, and building/auditing the Windows ZIP.
The recorded focused automated checks and manual acceptance are sufficient for
this narrow hotfix; **no new full verification gate or qualification is required**.
Codex must not repeat the full-book conversion. No application/test changes belong
in this closeout. Windows 11 HOME-PC is qualified; Windows 10 is not separately
qualified, and macOS/Linux remain unqualified for this release.

**GitHub publication stays manual.** Do not create a v0.7.3 tag/release or upload
an asset. The owner will publish the validated ZIP. Keep the v0.7.2 release,
tag and archive unchanged. Merge/packaging source identities and final archive
facts are recorded after those operations; this document does not claim publication.

## Problem and bounded recovery

The private source has two QuickTime chapter samples and 33 Nero entries. FFprobe's
effective list combines contradictory representations, with its first two starts both
formatted as zero; its second label belongs to the final chapter. Both unmodified
production planners reproduced `duplicate_start`, before output reservation.

Normal validation runs first. Valid QuickTime, Nero-only and agreeing dual-table sources
keep the original report and output behavior. For an invalid primary list only, a bounded
read locates a single `moov/udta/chpl` v1 table. Recovery requires a unique audio-track
`tref/chap` reference to a separate QuickTime text track, matching the probed audio ID,
complete mandatory headers and unambiguous box boundaries. The independently read Nero
entries retain stored order and UTF-8 titles and pass the **unchanged** strict validator.
Recovery additionally requires an explicit zero start, one zero-based audio stream with
matching duration and positive sample counts under the existing cut calculation.

No entry is sorted, deduplicated, dropped or nudged. Unsupported, corrupt, incomplete or
ambiguous secondary metadata keeps the original rejection and adds a useful diagnostic.
The original probe is retained in `SourceReport.original_probe` after successful recovery.

Split uses the existing plan, encoders, tags, artwork, numbering and publication rules.
Whole suppresses the contradictory source map and writes the frozen recovered navigation
to its staged MP3 using existing Mutagen. A bounded 256 KiB ID3 reservation covers Nero's
maximum table; the writer preserves that allocation and refuses to resize it, avoiding an
uncancellable move of the large audio payload. Existing metadata options, cancellation,
duration measurement, retry and no-clobber publication remain in force. Strip omits navigation.

Format references: [FFmpeg MOV reader](https://ffmpeg.org/doxygen/trunk/mov_8c_source.html),
[Mutagen ID3 frames](https://mutagen.readthedocs.io/en/latest/api/id3_frames.html).
No dependencies, FFmpeg supervision, shared publication, Maker, Editor or TTS changes.

## Focused verification

Commands ran in `files/run-temp/m73`, using the original checkout's existing Python
(`..\..\..\.venv\Scripts\python.exe`), pytest, and the existing FFmpeg/ffprobe 9.0.1 pair.
All pytest commands include `-q -p no:cacheprovider` and an owned `--basetemp` under
the worktree's `files/run-temp/`. The only warning was the existing pydub/audioop deprecation.

| Modules / selector | Result | Basetemp |
| --- | --- | --- |
| `test_m4b_chapter_probe.py`, `test_m4b_chapter_validation.py`, `test_m4b_timeline_partition.py`, `test_m4b_conversion_plan.py`, `test_m4b_chapter_boundaries.py`, `test_m4b_probe_encoding.py` | 331 passed | `chapters-focused` |
| `test_m4b_nero_recovery.py` | 44 passed | `nero-reviewed-green` |
| `test_m4b_execution.py`, `test_m4b_publication_order.py`, `test_m4b_nero_execution.py` (before the final header-reservation check) | 131 passed | `execution-focused` |
| `test_m4b_nero_execution.py` (final header reservation and maximum table) | 7 passed | `nero-padding-green` |
| `test_m4b_execution.py -k 'whole or strip or output_args'` (after header reservation) | 12 passed, 83 deselected | `exec-args-final` |
| `test_m4b_retry.py -k 'split_retry or retry_reuses_the_exact_plan_object or retry_probes_nothing or retry_reserves_no_second_run_directory or retry_never_deletes_an_unknown_file or attempt_gets_fresh_controls'` | 8 passed, 71 deselected | `retry-focused` |
| `test_config.py -k project_version_drift` | 1 passed, 67 deselected | `version-focused` |

The configuration-only selector also emitted pydub's unverified-FFmpeg warning inside the
restricted sandbox; real-media selectors ran with the existing proved system pair available.

Tests include a generated six-second AAC M4B whose actual QuickTime sample table is
damaged independently of Nero, plus real valid QuickTime-only, Nero-only and agreeing
dual-table controls. Both the anonymous 2-QT/33-Nero reproduction and real generated
conflict failed before integration and passed afterwards. Invalid/decreasing/duplicate/
out-of-range Nero starts, bad duration, lost audio extent, corrupt UTF-8/headers/boxes,
ambiguous references, audio-ID mismatch and zero-sample spans fail closed. Independent
review found and corrected the bounded safety gaps. An in-memory mutation removing the
audio-ID check was caught without changing source files.

Real MP3 outputs prove recovered Whole navigation, Preserve/Replace/Strip, artwork byte
preservation, ID3v2.3, exact audio bytes through maximum-table navigation writes, Cancel
after the write, failed-write retry and no-clobber safety. Recovered split outputs through
one decode match seek outputs byte-for-byte after decoding and match independently
decoded source samples. No historical tests or thresholds were weakened.

## Private actual-book evidence

Original Split and Whole failure reproduced: **YES**. Corrected preflight accepts all
33 Nero chapters, with every timestamp/title matching the prior independent inspection.
Coverage is exactly `[0, 29277.275011]` seconds. All spans are positive and contiguous;
the existing cuts cover exactly **1,291,127,828 declared audio samples** without gaps or
overlaps. Output tracks are 1–33. Source SHA-256, size and mtime remained unchanged.

The packet guard correctly retains seek-per-chapter for this particular book: packets
hold 1,291,128,832 samples while the stream declares 1,291,127,828. Its guard was not
weakened. The small generated recovery book separately proves the continuous route.

Three private two-second production conversions at source times `0`, `13344.6816553`
and `29275.275011` passed. Each decodes to 88,200 stereo frames at 44.1 kHz; correlations
against an independent short seek with decoder priming were 0.999636, 0.999667 and
0.999833. Non-silent content, timing, retained artwork and title tags were checked.
Excerpts, source hash, titles and full probe evidence remain local and untracked.
These automated checks do not claim an independent full-book conversion, decode or
human listening verdict. Full-book GUI conversion is accepted on the owner's report above.

## Recorded owner launch and acceptance procedure

The procedure below is retained as the tested workflow, not a request to repeat the
completed owner test. The owner's PASS above supersedes the earlier acceptance hold.

From the **original HOME-PC repository root**, run in PowerShell:

```powershell
& .\.venv\Scripts\python.exe .\files\run-temp\m73-private\launch_candidate.py
```

This local identity-checking wrapper uses the supported direct `scripts/launcher.py`
entry point in the feature worktree. It verifies the exact recorded commit and source
hashes, version 0.7.3, imported module paths, existing Python and verified system FFmpeg.
It records `files/run-temp/m73-private/last-launch.json` before opening the application.
A narrow native launch smoke checks this same process and closes its own window.

Settings were copied into the worktree, with only its last tool and output base changed.
Owner settings, v0.7.2 installation, environments and installed models are preserved;
no dependencies or models are installed or copied. Converter needs no voice engines.
Candidate outputs go under the original checkout's **`files/run-temp/m73-output/`**.
Run options start from ACT's existing defaults: select the usual options at conversion.

1. Launch the verified v0.7.3 candidate and import the previously rejected M4B.
2. Select **Split by Chapters** and the usual settings; run the full conversion.
3. Confirm successful completion and 33 outputs with correct numbering and titles.
4. Listen across first, middle and final chapter endings/beginnings for missing or duplicated audio.
5. Verify the original M4B SHA-256 against the local baseline; optionally try a normal book.
6. The owner has now reported **PASS** and explicitly authorized merge and Windows packaging.

Limitations: narrowly recognized MOV/chpl v1 layouts only; uncertain provenance remains rejected.
Whole ID3 navigation uses normal millisecond precision; audio cuts keep Nero starts through the
existing sample calculation. No full gate, GUI journey suite, scaling/engine/low-memory/fresh-Windows
qualification was run for v0.7.3. Codex did not repeat the full-book conversion.
Windows packaging is authorized; GitHub publication is reserved for the owner.
