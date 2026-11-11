# m4b-scaling qualification

The M4B Converter's split route at scale (v0.7.2 Phase 7B, ACT72-012): the one-decode continuous route
(`scripts/m4b/m4b_continuous.py`) against the frozen budgets and the pinned production outputs. It is a qualification
scenario: it never runs in a routine mode, takes about three hours of machine time, and should run in a quiet session.

```text
.venv\Scripts\python.exe files/dev-work/verification-gate/verify.py --mode qualification --scenario m4b-scaling
```

The gate supervises `qualify.py` under its own job and budgets (`verification.json`, stage `qualification`) and reports
the scenario's `verdict.json`: PASS, FAIL, or BLOCKED when a prerequisite is missing (the application's M4B code, or an
FFmpeg build the reference was not pinned on). The runner's exit status must agree with its verdict.

| File | What it is |
|---|---|
| `recipe.py` | The deterministic book recipe (lavfi noise and tones, AAC-LC, odd-millisecond chapters, cover, tags), Phase 7A's command lines unchanged; each book is validated before use. |
| `reference.json` | Per exact FFmpeg/ffprobe pair: every recipe book's SHA-256, and per book and settings one digest over the production seeking route's outputs (pinned from runs of the v0.7.1 reference `204c33b`, and of the v0.7.2 tree where its seeking route is unchanged). |
| `bench_run.py` | One contained, measured run of the real Converter panel (see its docstring). |
| `winjob.py` | Job Object accounting for a benchmark process tree. |
| `common.py` | FFmpeg identity, the fixture cache, one contained run, digests, the owner-state snapshot. |
| `qualify.py` | The scenario: identity, containment, fixtures, the budget matrix, faults, the stall study, the verdict. |
| `calibrate.py` | The one-time calibration of the small-book threshold, with its decision rule fixed in the file. |

**Large media** lives only in the ignored cache `files/dev-work/m4b-scaling-cache/` (about 0.6 GB) and is accepted only
when its SHA-256 equals the pinned one; a missing or different book is remade by the recipe. Nothing large is committed.
Each run's produced MP3s are hashed and then deleted; every run keeps its `results.json` in the run folder.

**Containment.** Every benchmark run proves, before anything is converted, that the application's configured output base
(set through its own preference in a redirected settings file, read back from the live configuration and resolved by the
application's resolver) lies inside that run's own folder, and refuses otherwise; every reservation is checked again. The
owner's Downloads output tree is compared before and after the whole scenario. A run also proves, before it starts, that
nothing in it can open the file manager (`bench_run.neutralize_shell`): the Converter reveals its output folder when a
run ends, and attempt 1 of the qualification let every run do it (about 200 Explorer windows; the owner's shell crashed
twice; `os.startfile` held the Tk loop for up to 36.9 s). The requests are recorded, never performed, and the open
file-manager windows are counted before and after the scenario.

**Measurement notes.** Windows counts a pipe write as a write, so T4 takes the pipe bytes the harness counted exactly
(the decoder's stream, the encoders' feed) off the job's write bytes before comparing with the seeking route. The
encoder fault kills the K-th encoder from the feed after its first block of audio, because a short chapter's encoder
exits long before any fixed delay. Each run's log line gives the machine's load before and during it and this run's own
share, so contention is visible rather than guessed; the qualification should run while nobody uses the machine.

**How T4 and T5 are measured** (v0.7.2 Phase 8 remediation; the budgets did not move). Three things the harness read
were not the Converter, and each failed or nearly failed a run on the 1,000-chapter book:

* *The job's peak commit.* Windows keeps charging a job for an exited process while anyone holds a handle to it (about
  77 KB each here). The harness kept every child's `Popen` object, so 155 MB of that book's 236 MB "peak" was its own
  bookkeeping, different by up to 1.5 MB between identical runs, against a 1 MiB allowance. A child's figures are now
  read when it ends and it is let go (`bench_run.Child`), so the figure is what the job's live processes hold.
* *One more FFmpeg.* Windows starts a console host (`conhost.exe`) for every hidden console child. The decoder's lives
  as long as the decoder, so it is part of what one more FFmpeg open of the book costs the job. The harness finds it
  (`winjob.Job.children_of`) and T4's envelope is the seeking route's peak, the decoder at its own peak, that one
  console host at its own peak, and 1 MiB for the audio. Nothing else is allowed for, and nothing that was not measured.
* *Staged bytes.* The total is at its peak for a few milliseconds per chapter, at the end of the cover pass; a sample
  every 0.5 s mostly misses it, so two routes that stage the same files read different "peaks" by chance. The harness
  now reads every owned temporary's real size at each moment the total can only fall next (just before a temporary is
  discarded and just before a staged file is published: `bench_run.StagingCensus`). Staged media is compared exactly,
  with no allowance, and the seeking route's own runs must agree with each other to the byte. FFmpeg's diagnostics
  files are read at the same moments but apart: at its default verbosity FFmpeg lists the book's chapters into them
  (123 KB per pass on 1,000 chapters) and their length differs by a few bytes between identical runs, so they are held
  to the 1.05 x this scenario applies to writes. The 0.5 s sampler stays as a witness: it must never see more than
  the exact reading, or something lowered the total without being read.

"No PCM on disk" keeps its total comparison (the job's writes less the two counted pipes, at most 1.05 x the seeking
route's) and gains the direct figures for the two processes that touch the audio: every byte the decoder wrote is its
stream or its own diagnostics file, and the application wrote nothing beyond its feed to the encoders but what it writes
on the seeking route as well. `qualify.resource_checks` judges all of it from the runs' summaries;
`qualify.py --smoke` rehearses it on the 100-chapter book, and `--smoke --rehearse resources --code <a copy of scripts>`
measures a copy with a planted defect (its verdict is SMOKE, never PASS).

**Budgets** (Phase 7A record section 8, approved for 7B): T1 6 h/48 chapters at least 2.0x median wall and process-tree
CPU; T1b 1,000 chapters at least 1.8x wall and 2.0x CPU; T2 below the threshold the seeking route, above it at most 10 %
slower beyond same-session noise; T3 per-chapter slope at most 0.1 s per hour of prefix and last/first quarter at most
1.15; T4 at most 1 MiB of audio held, no PCM on disk, job peak within the seeking route's plus one more FFmpeg open of
the book plus 1 MiB; T5 staged bytes no higher; T6 heartbeat p99 at most 0.25 s and no stall over 2 s; T7 Cancel settled within 2 s,
every owned process reaped; T8 every output equal to the pinned reference, ineligible books on the seeking route. The
12-hour book's ratio is reported, without a throughput budget. The budgets are frozen in `qualify.py` and are not moved
after a failed run.

**Another FFmpeg build** is not qualified by this one: pin it first (regenerate the books with `recipe.py`, run the
seeking route of `204c33b` on each, record the digests), or keep that build's books on the seeking route.
