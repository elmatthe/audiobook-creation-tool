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

**Budgets** (Phase 7A record section 8, approved for 7B): T1 6 h/48 chapters at least 2.0x median wall and process-tree
CPU; T1b 1,000 chapters at least 1.8x wall and 2.0x CPU; T2 below the threshold the seeking route, above it at most 10 %
slower beyond same-session noise; T3 per-chapter slope at most 0.1 s per hour of prefix and last/first quarter at most
1.15; T4 at most 1 MiB of audio held, no PCM on disk, job peak within the seeking route's plus the decoder's own plus
1 MiB; T5 staged bytes no higher; T6 heartbeat p99 at most 0.25 s and no stall over 2 s; T7 Cancel settled within 2 s,
every owned process reaped; T8 every output equal to the pinned reference, ineligible books on the seeking route. The
12-hour book's ratio is reported, without a throughput budget. The budgets are frozen in `qualify.py` and are not moved
after a failed run.

**Another FFmpeg build** is not qualified by this one: pin it first (regenerate the books with `recipe.py`, run the
seeking route of `204c33b` on each, record the digests), or keep that build's books on the seeking route.
