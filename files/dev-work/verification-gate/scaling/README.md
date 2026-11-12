# m4b-scaling qualification

The M4B Converter's split route at scale (v0.7.2 Phase 7B, ACT72-012): the one-decode continuous route
(`scripts/m4b/m4b_continuous.py`) against the frozen budgets and the pinned production outputs. It is a qualification
scenario: it never runs in a routine mode, takes about three hours of machine time, and should run in a quiet session.

```text
.venv\Scripts\python.exe files/dev-work/verification-gate/verify.py --mode qualification --scenario m4b-scaling
```

The gate supervises `qualify.py` under its own job and budgets (`verification.json`, stage `qualification`) and reports
the scenario's `verdict.json`: PASS, FAIL, or BLOCKED when a prerequisite is missing (the application's M4B code, or an
FFmpeg build the reference was not pinned on). The runner's exit status must agree with its verdict, and the gate takes
a PASS only when the verdict bears it out and holds the whole scenario: at least one run, every check passed, the
runner's own `identity.json` naming the run's HEAD, and every check `verification.json` requires of this scenario's PASS
(`pass_requires`: 79 checks over 207 runs, each budget's checks by name or by family). A check that is missing was not
passed (v0.7.2 Phase 9, review finding P9-03).

| File | What it is |
|---|---|
| `recipe.py` | The deterministic book recipe (lavfi noise and tones, AAC-LC, odd-millisecond chapters, cover, tags), Phase 7A's command lines unchanged; each book is validated before use. |
| `reference.json` | Per exact FFmpeg/ffprobe pair: every recipe book's SHA-256, and per book and settings one digest over the production seeking route's outputs (pinned from runs of the v0.7.1 reference `204c33b`, and of the v0.7.2 tree where its seeking route is unchanged). |
| `bench_run.py` | One contained, measured run of the real Converter panel (see its docstring). A run folder so deep that the run's own `TEMP` would pass 248 characters is refused: Windows cannot start a process with a longer one (`CreateProcess` never returns). |
| `staging.py` | What the application has staged under the run's output base, read exactly: the census T5 is judged from, and the directory watch it is held to. |
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
  reads every owned temporary's real size at each moment the total can only fall next. The 0.5 s sampler stays as a
  witness: it must never see more than the exact reading, or something lowered the total without being read.

**T5 since the Phase 9 independent review** (finding P9-04). Two things in Phase 8's exact reading were wrong, and both
are corrected in `staging.py` and `qualify.resource_checks`:

* *It read before two helper functions only* (`discard_temporary` and the publication of `shared.output_paths`), so a
  temporary removed any other way lowered the total unread. The reviewer made a whole extra copy of a chapter inside
  the publication and unlinked it directly: 154,048 bytes were staged and T5 read 92,520. The census now reads before
  **every** removal, rename, truncation and writing-open of an owned temporary that this process makes, heard as
  Python audit events, which are raised before the operation whichever function, module or thread asks for it. Beside
  that it keeps Windows' own report of every removal and rename under the output base (`ReadDirectoryChangesW`), by any
  process and through any interface, and a decrease that no reading preceded makes the figure incomplete. A temporary
  that is gone or smaller at a reading without an operation that announced it does the same.
* *It judged a budget nobody approved.* The frozen T5 is "peak staged bytes no higher than production's". Phase 8
  compared the staged media with no allowance and FFmpeg's diagnostics files apart at 1.05 x, so a larger total could
  pass (the reviewer showed one nine bytes over). T5 is now the frozen sentence: the exact peak of **everything**
  staged, against the largest exact peak of the same session's seeking runs, with no allowance. The staged media is
  still also compared exactly on its own, which can only add a failure.

A staged file is media unless the run handed it to a child process as its output sink; then it is that child's
diagnostics, recognised by the file's identity on the volume. A name proves nothing: `.act-tmp-audio.log` that no child
was given is media. No link is followed, and a link among the temporaries fails the reading. A temporary nobody saw
created under this base in this run fails it too. The record says each of these things, and a record that does not say
is never taken as clean (`qualify.staging_problems`).

What cannot be heard is a file shortened through a handle that is already open (`file.truncate()`, a memory map). The
census reports any temporary the application opens for writing other than to hand it to a child, and any temporary found
smaller than before; and a test pins, from the Converter's source, that it has no such code.

Two things follow from holding the total to the byte. FFmpeg writes file paths into its diagnostics, so the runs
compared must have output paths of one length; the scenario's run labels guarantee it and T5 fails if they differ. And
FFmpeg ends a pass's diagnostics with a status line whose speed figure varies in length, so two identical runs can
differ by a few bytes at the peak. The seeking route's figure is the largest of its runs; a one-decode run that reads a
byte or two more than every seeking run of its book is a FAIL of this scenario, reported as one and never rerun until it
passes. The measured spread is in the Phase 9 remediation evidence.

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
the book plus 1 MiB; T5 peak staged bytes no higher than the seeking route's; T6 heartbeat p99 at most 0.25 s and no stall over 2 s; T7 Cancel settled within 2 s,
every owned process reaped; T8 every output equal to the pinned reference, ineligible books on the seeking route. The
12-hour book's ratio is reported, without a throughput budget. The budgets are frozen in `qualify.py` and are not moved
after a failed run.

**Another FFmpeg build** is not qualified by this one: pin it first (regenerate the books with `recipe.py`, run the
seeking route of `204c33b` on each, record the digests), or keep that build's books on the seeking route.
