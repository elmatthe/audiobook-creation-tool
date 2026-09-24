# Audiobook Creation Tool — Decisions (ADR log)

Append-only. Newest entries on top. Each entry: date, decision, why, signed by whoever made it.

---

## 2026-09-24 -- A Chatterbox chunk's pathological internal silence is a raw, stochastic model artifact, not an assembly or chunking defect; a bounded per-draw retry masks it without guaranteeing it away

During the v0.6.5 Phase 8 macOS listening gate the maintainer confirmed two
real Chatterbox artifacts flagged by the Mac bounded-validation run (Male 1,
13.75 s; the second one mislabeled "Male 2" in review but mechanically
confirmed as Male 3, 7.98 s -- four independent checks: manifest order,
production code's own frozen_voice_id, the engine's transcript log, and an
independent ffprobe duration match).

Applying the same exact-zero-vs-model-floor technique the v0.6.1 Plan 4
Phase 12 chunking investigation used (2026-08-18): assembly's `np.zeros` gaps
survive MP3 decode as literal zero samples; model output never does. Neither
flagged silence was anywhere near an exact-zero run -- both live entirely
inside one raw `model.generate()` draw (Male 1: chunk 21; Male 3: chunk 10,
segment 1). Unlike the Phase 12 defect, neither chunk contains a raw newline
or any pattern the splitter misses -- `split_for_chatterbox` is working
correctly. This is a Chatterbox Turbo sampling artifact (unseeded,
temperature 0.72), not a chunking bug.

A bounded reproduction (4 repeated draws per flagged/control segment, same
voice/reference/settings, no seed) showed it is **stochastic**: Male 1's
flagged text reproduced 0/4 (consistent with its original "rare" Windows
characterization); Male 3's flagged text reproduced **2/4** -- a materially
elevated rate for that specific sentence.

**Fix: `chatterbox_synth._generate_checked` retries a demonstrated
pathological internal silence (4.0 s below -50 dB, the same definition
Phase 8's final-acceptance harness uses) up to 3 times, keeping the first
clean draw; if every attempt is still defective, the last attempt is kept
and logged, never silently dropped (P8/P9). `_synthesize_chunk` reaches
every draw -- the whole-chunk path and each colon-segment path -- through
this helper. No generation parameter, text, or voice/reference changed
(P1).** Regression coverage: `test_chatterbox_silence_retry.py` (10 tests).

**Honest before/after result, not oversold: the fix works exactly as
designed but does not guarantee zero recurrence.** Re-running the identical
sample after the fix: Male 3 came back clean (no retry needed that draw).
Male 1 still showed a **new** pathological silence -- 11.99 s, landing in
the *same* chunk 10 / segment 1 as Male 3's original defect, a second
different voice failing on the identical text after the retry fired and
exhausted all three attempts (confirmed in the transcript). This is a
suggestive, still-small-sample signal that this one sentence carries an
elevated cross-voice risk, not yet confirmed as a distinct root cause and
not investigated further here.

**Ruling: accepted as a real mitigation, not a guarantee (P6 -- maintainer
decides next step).** The residual-risk decision (accept it, raise the
retry bound, or treat chunk 10's text as a separate follow-up) is the
maintainer's, recorded at the Phase 8 macOS gate in Handoff.md rather than
decided here.

---

## 2026-09-23 -- Kokoro's longer pause after a prose colon is accepted as model-native; an isolated colon-to-comma A/B showed no audible improvement and is not integrated

During the v0.6.5 Phase 8 maintainer listening gate (plan Section 9), the
maintainer separately tested an isolated colon-to-comma text substitution for
Kokoro voices, hypothesizing it might shorten Kokoro's longer model-native
pause after a prose colon. This is a different pause than the already-
approved Chatterbox structural-colon normalization from Phase 5 iteration 5
(integrated Phase 6) -- that candidate is unrelated and unaffected by this
finding. The isolated Kokoro candidate produced no audible improvement.

**Ruling: REJECTED, not integrated (P1, P6).** Kokoro's longer pause after a
prose colon stands as accepted, model-native behavior. No Kokoro code,
segmentation, or assembly changed as a result. This finding is preserved so a
later phase or a fresh agent context does not repeat the same rejected
experiment.

---

## 2026-09-22 -- v0.6.5 Phase 7 closed (maintainer PASS at e1c416a); Phase 8
Windows final-voice evidence runs through the real TTS panel job path

**Decision.** (1) Recorded: the maintainer passed the final Phase 7 Windows
layout/functional review at `e1c416abf5267490fc5c40367f9aa67de6c4eb6f`.
(2) Phase 8's final listening evidence is produced by a new `--final-acceptance`
mode of the existing `generate_voice_samples.py`, not a new tool. Unlike the
Phase 1 `--quality-suite` (direct engine calls, raw Edge audio), it drives a
headless `TtsPanel` through `run_job()` with the panel's defaults, so what the
maintainer hears is exactly what a user's run produces. Only the output base is
redirected, to gitignored `files/dev-work/`.

**Why.** Section 9 is final acceptance of the integrated product. Evidence from a
side path could hide a defect in the Phase 6 assembly or P14 dispatch that users
would hear.

**Mechanical bounds are catch-nets, not quality thresholds (P3, P6):** 8-25
chars/s, no internal silence over 4 s, no full-scale samples, strict decode,
container vs. decoded duration within 0.5 s. All 35 files met them; listening
still decides.

**Noted, not acted on:** about 1.4 GB of private-memory growth per Chatterbox
run inside one process (flagged for Phase 9), and the known 160 kbps effective
cap at 24 kHz (earlier ruling unchanged). `scripts/verify.py`: PASS (7624 passed, 57 skipped).

-- Implemented by Claude Code per the maintainer's Phase 8 (Windows portion)
authorization, 2026-09-22

---

## 2026-09-22 -- v0.6.5 Phase 7 final layout refinement: beside Activity the TTS
workflow is one vertical column with a compact Sources; Activity takes the rest

**Decision.** Per the maintainer's screenshot feedback on the responsive
redesign: whenever Activity is beside the workflow, sections 1, 2 and 3 are one
top-anchored vertical column -- never Voice & Audio beside Output & Run. The
imported list shows at most WIDE_LIST_ROWS = 8 rows there (fewer when the
height needs them, never below IMPORTER_FLOOR_ROWS = 2) and scrolls locally
instead of stretching. The workflow column is its measured natural width plus
at most WORKFLOW_BREATHING = 48 px, replacing the earlier one-third-of-spare
rule; Activity takes all remaining width and the full height (1331 of 1920 px
on HOME-PC, up from 829).

**Why.** The workflow reads as a sequence (sources, voice/audio, output/run),
and side-by-side sections broke that order on the very windows where space was
plentiful. A tall list with few files was empty space that pushed sections 2
and 3 away from Sources; a queue that long is better scrolled. Width beyond what
the workflow's fixed-size controls need was empty band; the log turns it into
readable lines.

**The one exception.** At the supported 920x600 minimum, Activity drops beneath
the workflow and sections 2 and 3 still share a row. Measured, it is the only
arrangement that fits: the vertical workflow's floor alone is 655 px against
580 px of content height, and the two columns' natural widths exceed the
window. The maintainer's instruction to preserve the minimum layout governs
there, and a test pins the measured reason.

**Unchanged.** Every capability and behavior; no TTS, audio, import, output-
planning or job-control code changed. `scripts/verify.py`: RESULT: PASS (full pytest 7616 passed, 57 skipped).

**Not touched in this drop:** the `99195a2` trailer (left for a separate
authorization), Phase 8 (unauthorized). Phase 7 is not marked passed.

-- Implemented by Claude Code per the maintainer's final Phase 7 layout-
refinement authorization, 2026-09-22

---

## 2026-09-22 -- v0.6.5 Phase 7 UI/UX redesign: the TTS panel becomes four sections
arranged responsively from measured sizes (workflow left, Activity right when
both fit; stacked below that)

**Decision.** Per the maintainer's redesign request after the Phase 7 manual
review, the TTS panel is recomposed into 1. Sources, 2. Voice & Audio,
3. Output & Run, and Activity (the one persistent Summary | Detailed log). The
arrangement is chosen by `TtsPanel._choose_layout` as a pure function of the
panel's size, using natural sizes measured from the live widgets
(`_measure_layout`): two columns only when the workflow and Activity both fit
at their natural widths and the workflow's floor fits the height; sections 2
and 3 side by side whenever the width allows; otherwise Activity drops beneath
the workflow. No whole-tool scrollbar in any arrangement.

**Why these rules, not a fixed ratio.** The maintainer's 60/40 was offered as a
starting point, not a requirement. The workflow's controls are fixed-size, so
spare width in that column is empty band -- the exact complaint about the old
full-width Voice/Audio bands. So each column first gets its natural width and
the spare width goes one third to the workflow, two thirds to the log
(workflow/log widths 517/477 at 1024x720, 602/648 at 1280x900, 1061/829 at
1920x1009, where sections 2 and 3 sit side by side). The one content-chosen number is
the log's minimum width, LOG_WIDTH_CHARS=52, sized to a typical Detailed line;
every other threshold is measured, so the breakpoints follow real fonts and
scaling. On HOME-PC that puts the 1024x720 launcher default in the two-column
layout and the 920x600 minimum in the stacked one.

**Why the column width is set explicitly.** Wrapped captions re-wrap to their
section's width, which makes a column's request follow its allocation. Left to
grid weights, the workflow column ratcheted wider on every resize and squeezed
the log below its natural width (found and measured during this drop). Wrap
widths now come from the layout arithmetic, and the workflow column's width is
set by `_size_columns`. Regressions are mutation-checked.

**Correction to the previous entry.** The remediation entry below recorded the
log as "900x61 px (a real, multi-line, readable region)" at 920x600. That
measured its size without checking it was inside the window: it sat at
y=650-711 in a 600 px window, fully off-screen. This redesign supersedes that
claim; the log now shows ~4 lines at 920x600 and ~37-56 lines on larger
windows.

**Unchanged.** Every capability and behavior listed in the redesign request:
unified PDF/TXT queue and its options, voice/setup-required behavior, bitrate,
requested workers with truthful effective reporting, Edge rate / Kokoro speed /
no Chatterbox control, Resume, Overwrite, Start/Pause/Resume/Cancel/Retry
Failed, progress + ETA, one persistent log with the transcript in Detailed
only, Clear Log, Open Output Folder, output planning, and all Phase 5/6 audio
and worker behavior. No timing/trim control was reintroduced and no voice
preset changed. `scripts/verify.py`: RESULT: PASS (full pytest 7602 passed, 57 skipped).

**Not touched in this drop:** Phase 8 -- not started, unauthorized. Phase 7 is
not marked passed; the maintainer's screenshot/manual UI review is outstanding.

-- Implemented by Claude Code per the maintainer's Phase 7 UI/UX redesign
authorization, 2026-09-22

---

## 2026-09-21 -- v0.6.5 Phase 7 remediation: TTS's Summary/Details view and its
separate "Engine output" box are consolidated into one persistent
job_ui.SummaryDetailsView, matching the MP3 Tool/M4B Maker/M4B Metadata Editor

**Decision/implementation.** The maintainer's manual Phase 7 gate ran and came
back FAIL: the TTS panel showed two separate log regions -- the JobAdapter's
own internally built Summary/Details notebook, plus a second, standalone
"Engine output" `scrolledtext.ScrolledText` immediately below it -- duplicating
and fragmenting run information and wasting the vertical space the previous
layout-refinement pass had just fought to recover. The correction: TTS adopts
the exact persistent-view pattern the MP3 Tool, M4B Maker and M4B Metadata
Editor already use, while keeping the panel's own classic (no design-system
theme) styling -- this was a structural fix, not a visual-parity pass.

**1. One view, built once, handed to every adapter.** `self.log =
job_ui.SummaryDetailsView(self, theme=None, height=2, details_label=
"Detailed", limit=LOG_LIMIT)` is built in `__init__` and gridded at row 4 in
place of the deleted "Engine output" `LabelFrame`/`ScrolledText`; `_install_
jobs` passes `views=self.log` into every run's `JobAdapter`, so the adapter
never builds or grids its own view and history survives a rebuild. `LOG_LIMIT
= 400` and `DIVIDER_MARK = "────"` are the same constants the three
sibling tools already use, copied rather than reinvented.

**2. `shared/job_ui.py` gained one additive method: `SummaryDetailsView.
append_detail()`.** No existing method could write to Details alone --
`append()` always writes both panes, which conflicts directly with keeping raw
engine chatter out of Summary. `append_detail()` mirrors `append()`'s
freeze-then-extend-then-trim-then-redraw contract exactly, touching only the
Details history. Backward compatible: every existing caller of `append()`,
`set_summary()`, `set_details()`, `divider()` and `clear()` is unchanged.

**3. Engine transcript routing.** The worker->GUI `_log_q` "log" kind already
carried both raw stdout/stderr (via `QueueWriter`, `contextlib.redirect_
stdout`/`redirect_stderr`) and the worker's own milestone strings (`_RunContext.
log`, e.g. "[12:00:00] file.txt -- completed", "Requested workers: N |
Effective workers: N") -- both were already going into one visual box before
this drop, so no worker-side code changed. Only the panel's own routing
changed: `_append_engine_output()` line-buffers this channel across drain
ticks and calls `self.log.append_detail()` with complete lines only, and
`_flush_engine_output_buffer()` catches a trailing partial line when a "done"
message ends the run, so nothing already reaching the log is lost. Summary is
unaffected by any of this: it is still exactly job_control.project_summary's
own state/progress/warnings/failures/completion projection, driven from the
job event stream and nothing else.

**4. Row weights: row 3 (shared run controls) pinned, row 4 (the log)
absorbed its weight.** Row 3 held Summary/Details until this drop, which made
weight=2 (elastic) the correct choice; now it holds only the JobAdapter's
fixed-height control bar and status view, so weight=0 is correct and row 4
rose from weight=4 to weight=6 to receive the difference, exactly the "give
the recovered space to the one log" instruction this drop was scoped to.
`_hold_job_area_open()` was rewritten to measure `controls.frame`/
`status.frame` directly rather than call `JobAdapter.minimum_height()`, which
still unconditionally adds `views.minimum_height()` regardless of whether the
caller owns those views -- with `views` now external to `job_area`, that
method would misattribute row 4's own floor onto row 3.

**5. A real floor-computation bug was found and fixed, not merely designed
around.** Both `_hold_job_area_open()` and `_hold_log_open()` read their
target widgets' `winfo_reqheight()` immediately after those widgets were
built, in the same call that built them, before Tk's geometry manager had
necessarily settled a real value in place of a small-but-positive placeholder
-- which is well above zero, so the existing `floor <= 0` retry guard never
fired. Measured directly: row 3's floor landed at ~10 px (needed: 93 px) and
row 4 got no floor at all, so the log collapsed to a real, mechanically
measured 1x1 px sliver at the 920x600 minimum -- worse than the *previous*
drop's already-accepted "compresses to effectively nothing" trade-off for the
old Engine output box, not an improvement on it. Both methods now force an
idle-task pass unconditionally before their first measurement, matching the
pattern `_hold_importer_open()` already used. Corrected and mechanically
re-measured at the exact 920x600 minimum: log 900x61 px (a real, multi-line,
readable region), job area 900x93 px, importer 900x163 px, options form
920x331 px, Start row 304x41 px; at 1280x900 the log grows to 1260x108 px.
Zero overlaps among the five top-level bands at either size.

**6. Tests.** `files/tests/test_job_ui.py`: 5 new focused tests for
`append_detail` (details-only, multi-line, freeze-then-extend interaction with
a live Summary re-render, divider interaction, limit). `test_tts_compact_ui.
py`: 5 existing tests fixed for the new `self.log` shape (no longer a raw Text
widget), plus 2 new tests (exactly one Notebook and no "Engine output" widget
anywhere in the tree; the floor-computation regression at 920x600).
`test_tts_jobs.py`: a new "P. Summary/Detailed log consolidation" section (7
tests) proving persistent-view identity across an adapter rebuild, raw log
lines and a partial unterminated line both landing in Detailed only, a real
run's transcript in Detailed while Summary carries only its own completion
wording, history surviving both a retry and a second fresh run with the
correct divider text, and Clear Log emptying both panes without touching the
frozen `RunResult`. `test_tts_importing.py`/`test_tts_worker_concurrency.py`:
4 pre-existing tests updated from `panel.log.get(...)` to `panel.log.details`.
Full TTS + job_ui sweep: 465 passed. Full `pytest`: 7582 passed, 57
skipped, zero failures. `scripts/verify.py`: RESULT: PASS. No TTS synthesis,
audio quality, timing, worker, importing or output-planning behavior changed.

**Not touched in this drop:** Phase 8 -- not started, unauthorized. The
maintainer's manual Windows layout/functional smoke gate -- this entry
records implementation and mechanical verification only, not that gate's
outcome, which remains outstanding and is explicitly not claimed here, and
Phase 7 is explicitly not marked passed by this entry.

-- Implemented by Claude Code per the maintainer's Phase 7 remediation
authorization, 2026-09-21

---

## 2026-09-21 -- v0.6.5 Phase 7 (final layout-refinement pass): the options
form's canvas/scrollbar is gone; adopts the M4B Converter/MP3 Tool's own weighted-
row scheme for the 920x600 minimum

**Decision/implementation.** Per the maintainer's request for one final Phase 7
layout-refinement pass (no TTS/audio/concurrency behavior change) before the
manual Windows gate: the options form's own canvas/scrollbar machinery -- which
the Compact UI pass (previous entry) had already shrunk to ~445 px but not
removed -- is gone entirely, and the panel's five top-level rows now use the same
weighted-row scheme this codebase already uses for the identical problem in the
MP3 Tool and M4B Converter.

**1. Investigated before editing.** A real, unconstrained `TtsPanel` was measured
directly (`winfo_reqheight()` per band) before any change: the options form's own
canvas/scrollbar contributed no real value at 445 px against bands that, added
together (importer 275 + Start row 41 + job area 259 + log 124 = 699 px), already
exceeded the 600 px minimum on their own -- meaning simply removing the canvas
without also adopting a real compression scheme elsewhere would have made the
panel need a *bigger* window, not fit a smaller one.

**2. The options-form canvas/scrollbar is removed entirely.** `frm` (Voice/
Engine + Audio/Processing + run options) is now an ordinary `ttk.Frame` gridded
directly at row 1 -- no `tk.Canvas`, no `ttk.Scrollbar`, no `<Configure>`
rebinding, no `enable_mousewheel` call. Verified directly: zero `tk.Canvas`
widgets exist anywhere in the panel (`files/tests/test_tts_compact_ui.py::
test_no_canvas_anywhere_in_the_panel`), matching the MP3 Tool's own established
convention for this exact situation (`test_no_whole_tool_scrollbar_only_local_
ones`, `assert widgets_of(panel, tk.Canvas) == []`).

**3. Row weights now match the M4B Converter's own scheme for the same problem**
(`m4b_converter.py`, `rowconfigure(0, weight=4)` / `(1, weight=0)` / `(2, weight=0)`
/ `(3, weight=2)` / `(4, weight=4)`): the imported queue (row 0) and the engine
log (row 4) carry the weight and compress/scroll locally; the options form
(row 1) and the Start/Open Output Folder/Clear Log row (row 2) are pinned at
weight=0, never squeezed below what their controls ask for; the shared run
controls' row (row 3, Summary/Details/progress) gets weight=2 and a measured
floor (below).

**4. Two floor-protection methods were added, both adopting the exact mechanism
the M4B Converter already uses and already has a dedicated shared-infrastructure
test for (`test_job_ui.py::test_the_views_keep_one_readable_line_however_hard_
they_are_squeezed`):**
- `_hold_job_area_open()` mirrors the M4B Converter's own method of the same
  name near-verbatim: measures `JobAdapter.minimum_height()` (shared, already
  tested infrastructure) and sets `rowconfigure(3, minsize=...)` so Summary
  never collapses to a sliver. TTS never had this protection before this pass
  -- a genuine fix, not merely a port.
- `_hold_importer_open()` and `_hold_log_open()` are new (no direct prior-art
  method to mirror, since `ImportAdapter` exposes no `minimum_height()` of its
  own): the first protects the imported queue's Add Files/Import Folder/Include
  Subfolders and import-status rows (both weight=0 inside `ImportAdapter.
  frame`) from being squeezed below their own request when the *outer* queue
  row is compressed -- without it, a real defect was found and fixed during
  this pass: `grid` does not clip a child to a cell smaller than its own
  request, so the effect of an unprotected floor was those controls
  **overlapping** the Voice/Engine section below them, not merely shrinking.
  The second gives the engine-output log a floor of two visible lines (this
  codebase's own "at least two rows" bar for variable-length regions,
  e.g. plan §11 / `test_m4b_layout.py`), rather than letting weight=4 alone
  compress it to a single, effectively-invisible pixel.

**5. Further compaction, all textual/spacing only (no behavior change):**
`details_height` (Summary/Details) and the engine-output log's own visible-line
count both dropped from 8/8 to 4/4, matching the M4B Converter's own already-
accepted values exactly (not an invented number). The options form's footer
paragraph (five sentences restating what the per-backend notice/status labels
already say live) is now one line naming only the default voice; the workers
caption and the Edge-rate caption are both shortened to fit one wrapped line
each. LabelFrame/row padding tightened from 8-10 px to 6 px throughout the form.
Net effect: the form's own `winfo_reqheight()` fell from ~445 px (previous entry)
to 331 px.

**6. Mechanically verified, not just estimated.** A real, sized `TtsPanel`
(packed to fill its window, exactly as the real launcher does) was measured at
both the supported minimum (920x600) and a larger window (1280x900):
zero overlaps among the five top-level bands at either size; every primary
control (Add Files/Import Folder, voice dropdown, bitrate, workers, Start, Open
Output Folder, Clear Log) stays mapped and reachable at both sizes; backend
switching (Edge/Kokoro/Chatterbox) still shows exactly the one correct rate
control at the 920x600 minimum specifically. At 920x600: options form 920x331
(its full, protected request), importer 900x163, Start row 304x41, job area
900x141 (close to its measured Summary floor), engine log compresses to
effectively nothing -- an accepted, explicit trade-off, since the log is
precisely the kind of "may continue to scroll internally" region §11 already
allows, and it recovers immediately at any window taller than the exact
minimum (38 px of visible log at 1280x900).

**Verification.** `files/tests/test_tts_compact_ui.py` section D was rewritten:
the two tests that depended on the now-removed canvas were replaced with tests
proving zero canvases exist, every scrollbar belongs to a locally-scrolling
widget, the form is a plain pinned frame, the form stayed compact (< 400 px,
down from the previous entry's < 1000 px bound), no top-level band overlaps
another at 920x600 or 1280x900 (parametrized, with real geometry/deiconify/pack
-- an unmanaged or withdrawn panel reports meaningless `winfo_rootx`/`ismapped`,
so the test explicitly packs and deiconifies before measuring, mirroring
`test_mp3_tool_layout.py`/`test_m4b_layout.py`'s own convention), and backend
switching's rate control at the 920x600 minimum specifically. Two existing
tests whose assertions named the old, now-shortened caption text were updated
to the new wording. Full `pytest`: 7568 passed, 57 skipped, zero failures.
`scripts/verify.py`: RESULT: PASS. No TTS/audio/concurrency behavior was
touched; the real production-path smoke campaign (recorded separately, this
same date) was not re-run, since nothing on that path changed.

**Not touched in this drop:** Phase 8 -- not started, unauthorized. The
maintainer's manual Windows layout/functional smoke gate itself -- this entry
records implementation and mechanical verification only, not that gate's
outcome, which remains outstanding and is explicitly not claimed here.

-- Implemented by Claude Code per the maintainer's Phase 7 final layout-
refinement authorization, 2026-09-21

---

## 2026-09-21 -- v0.6.5 Phase 7: Compact TTS UI -- pause/trim controls removed
from user-editable state; the per-voice policy behind them is unchanged

**Decision/implementation.** Per the maintainer's authorization for the plan's Section
10 compacting pass, the TTS panel's user-facing surface is reduced to exactly the
bands Section 10 specifies, with no change to any approved TTS/audio/concurrency
behavior from Phases 1-6.

**1. Removed from user-editable state:** sentence/paragraph/title/chapter pause,
end-silence, trim threshold, and trim-edge-chunks. Their Tk StringVar/BooleanVar
backing (`sentence_ms_var`, `paragraph_ms_var`, `title_ms_var`, `chapter_ms_var`,
`end_pause_var`, `trim_edge_chunks_var`, `trim_dbfs_var`) and the "Pause timing" and
two provenance-scoped ("files added directly" / "imported from a folder") LabelFrames
are gone entirely, along with the now-unused `_parse_pause_ms`/`_parse_trim_dbfs`
input-validation helpers they existed only to serve.

**2. The maintainer-approved per-voice policy behind those controls is unchanged.**
`voice_registry.VoiceEntry.timing_preset` still varies per voice exactly as before
(e.g. Edge Andrew's 820/870 ms sentence/paragraph pause vs. Steffan's 800/850) --
`epub2tts_gui.TtsPanel.run_job` now reads it directly from the registry at run time
instead of from a widget, so the values a run actually uses are byte-identical to
before, just no longer editable. `voice_registry.py`'s own module docstring is updated
to state this plainly (its `timing_preset` keys no longer name live Tk StringVars).

**3. Retained exactly as Section 10 specifies:** the unified PDF/TXT queue/importer,
voice dropdown and backend/setup-required status, MP3 bitrate, the requested
file-worker control with P14's truthful effective-cap reporting, and the one
rate control the selected backend actually supports -- Edge shows a "%"-rate entry,
Kokoro shows its speed spinbox, and **Chatterbox now shows neither** (previously the
Edge-rate entry was shown, inertly, regardless of backend -- a real "fake control"
this pass corrects, not a new restriction). The Edge rate control is captioned
honestly: it has only ever affected folder-imported Edge conversions (the direct/rich
engine has never accepted a rate parameter), a pre-existing asymmetry now stated
rather than left implicit.

**4. Bitrate and workers are no longer framed as provenance-specific.** Both already
applied to every queued item regardless of direct-vs-folder origin (bitrate always
did; workers did so precisely because Phase 6 unified dispatch), so the two old
LabelFrame headings implying otherwise were already misleading before this pass. Both
now live in one consolidated "Audio / Processing" LabelFrame (§10 Band 3), alongside
the rate control, ordered after a new "Voice / Engine" LabelFrame (§10 Band 2) so the
backend-dependent rate control's own band follows the choice that determines it.

**5. Resume and Overwrite** (neither explicitly named in Section 10's table, neither
in its Remove column) are kept, moved together into one small "run options" row
rather than left split across the two retired provenance-specific groups.

**6. Added: Clear Log and Open Output Folder**, bringing this panel to parity with
the sibling MP3/M4B tools that already have both (`mp3_tool.py`, `m4b_converter.py`,
`m4b_maker.py`, `m4b_metadata_editor.py`). Neither is a processing option and neither
locks through the shared matrix, matching those tools' own convention exactly.
`open_output_folder` reveals this run's own reserved directory once one exists, or
the tool's parent folder before any run -- reusing `output_paths.ensure_tool_parent`
and `shared.subprocess_utils.reveal_in_file_manager`, both already used by the
sibling tools for the identical purpose.

**7. Layout.** No whole-tool scrollbar: the options form keeps the one internal
scroll canvas it already had before this phase (unchanged architecture), and no
second canvas/scrollbar wraps the panel itself. Removing the entire pause/trim band
and merging two LabelFrames into one measurably shrank the scrollable form (a real,
mechanical Tk measurement: 445 px, down from the ~1300 px the form's own prior
comment documented) and the panel's always-visible bands (importer + Start row +
job area) measure ~575 px total -- comfortably under the shared 920x600 minimum
window (`shared.ui_theme.MIN_SIZE`) the launcher already applies. This is a
mechanical proxy, not the mandatory Windows manual layout/functional smoke gate,
which remains outstanding.

**Verification.** Two pre-existing tests that asserted the removed StringVars
directly (`test_tts_importing.py::test_the_voice_dropdown_still_applies_a_timing_
preset`, `test_chatterbox_integration.py::test_selecting_a_chatterbox_voice_applies_
its_timing_preset`) were rewritten to prove the same underlying per-voice values
still reach the frozen run params with no widget in the path, rather than asserting
on removed attributes. New `files/tests/test_tts_compact_ui.py` (18 tests) covers:
removed attributes/helpers/wording are gone; the consolidated Audio/Processing band
holds bitrate/workers/rate; exactly the backend-supported rate control is shown per
voice (Edge/Kokoro/Chatterbox, parametrized); Clear Log and Open Output Folder behave
correctly and are not registered as processing options; no second outer scrollbar
exists; and the real, mechanical form-height/fixed-band-height measurements above.
Full `pytest`: 7561 passed, 57 skipped, zero failures. `scripts/verify.py`:
RESULT: PASS.

**Not touched in this drop:** Phase 8 (final voice acceptance + macOS validation) --
not started, unauthorized. The mandatory Windows manual layout/functional smoke gate
this phase's own instruction requires is also still outstanding -- this entry records
implementation and mechanical verification only, not that gate's outcome.

-- Implemented by Claude Code per the maintainer's Phase 7 (Compact TTS UI)
authorization, 2026-09-21

---

## 2026-09-21 -- v0.6.5 Phase 6: bounded file-worker concurrency (P14) implemented;
a real os.chdir race discovered and fixed in the Edge direct/rich engine

**Decision/implementation.** Per the maintainer's authorization to close the audio-
integration subtask and execute only the file-worker/concurrency subtask, P14 is now
implemented: concurrency exists only between whole source files (never inside one
file's own synthesis units), and effective workers are resolved at run start rather
than trusting the raw requested count.

**1. Direct and folder items now share one pool and one resolved worker count.**
`epub2tts_gui._RunContext.run_all_items` replaces the old two-phase design
(`run_direct_items` -- strictly sequential, one at a time -- followed by
`run_folder_items`/`convert_folder_items` -- pooled, folder-only). Every queued item,
regardless of provenance, now goes through one `ThreadPoolExecutor` sized by one
resolved effective-worker count. A direct Edge file still takes the rich chapter/
pause engine and a folder-derived Edge file still takes the chunked batch worker
(P10 -- provenance selects the engine, never audio quality); Kokoro/Chatterbox take
the same engine call regardless of provenance, as before.

**2. `resolve_effective_workers(requested, queued_files, backend)`** is the one place
the cap is computed: `min(requested, queued_files, backend_safe_ceiling,
device_safe_ceiling)`, floored at 1. Backend-safe ceilings are unchanged from the
pre-existing folder-pool code (Edge 32, Kokoro 8, Chatterbox 1 -- a correctness
constraint, not a tuning choice). The device-safe ceiling is new: read from the real
machine's `os.cpu_count()` (via a small patchable seam, `_cpu_count()`), not an
invented formula -- Edge (network-bound locally) is offered up to one worker per
logical core, Kokoro (sustained local CPU inference per file) is offered half the
cores, leaving headroom for the OS/UI/FFmpeg either way. An oversized request (e.g.
"100") degrades safely to whatever the machine/backend/queue can actually support and
is never silently ignored: `run.log` always states
"Requested workers: X | Effective workers: Y".

**3. A real, previously-latent bug was found and fixed while implementing this:**
`epub2tts_edge.runner.run_conversion_job` isolates one conversion's relative-path
scratch files (`part1.flac`, `sntnc0.mp3`, `FFMETADATAFILE`, etc.) by `os.chdir`'ing
into a private temp directory for the whole call. This was safe only because direct
Edge items were previously guaranteed to run one at a time; `os.chdir` is process-wide
state, not thread-local, so two concurrent direct Edge conversions would have raced,
each potentially writing one book's chapter/paragraph scratch files into the other's
temp directory. Fixed with `runner._CWD_ISOLATION_LOCK`, serializing only that
chdir'd critical section -- not the whole engine, so a folder-derived Edge file or any
Kokoro/Chatterbox file dispatched to a different pool worker still runs fully
concurrently with a gated direct Edge file (neither of those paths ever calls
`os.chdir`). A conversion that is cancelled while queued behind this lock re-checks
`cancel_check()` immediately on acquiring it, so it never starts a whole new
conversion no one wants, even though the wait itself cannot be interrupted early (the
same "indivisible operation" contract every other checkpoint in this codebase already
accepts). Rewriting the vendored engine to take an explicit working directory instead
of relying on cwd would remove the need for this lock entirely, but that is a larger
change to vendored internals than this bounded subtask justifies (P11/P14).

**4. A second, related correctness gap in the pre-existing folder-only pool was
fixed while unifying it:** the old code broke out of its results loop and called
`future.cancel()` on remaining futures as soon as it noticed a cancellation, but
`future.cancel()` only succeeds for a future that has not yet started -- an
already-running task's eventual successful result was then silently discarded when
the pool's context manager finished waiting for it, leaving a real output file on
disk that the run never counted, logged, or could offer for retry. The new unified
loop drains every submitted future's result unconditionally; nothing is silently
dropped because the run was cancelled overall.

**5. Chatterbox investigated for a bounded >1-file proof, per the plan's own
conditional instruction, and found not justified.** `chatterbox_synth._get_model`
caches exactly one model instance per device; `load_conditionals` mutates that
instance's `.conds` attribute in place immediately before each `generate()` call --
a genuine shared-mutable-state race if two files' conversions overlapped, not a
theoretical concern. Making two concurrent files safe would require either a second
~3.86 GiB model instance per extra worker (disproportionate VRAM/RAM cost the plan
explicitly warns against) or an invasive rearchitecture of the pinned wheel's
stateful conditioning mechanism -- both out of proportion for this bounded subtask.
**Chatterbox's cap remains 1**, verified directly: a real test drives two files with
two distinct reference voices at a requested worker count of 4, and confirms the
second file's engine call never starts while the first is in flight.

**6. Pause/Cancel/Retry Failed all remain correct under concurrency.** Pause is still
honoured at the same cooperative boundary (`controller.checkpoint()`) each task hits
before starting real work, now shared by every item regardless of provenance. Four
existing tests in `test_tts_jobs.py` that assert exact pause/cancel *ordering* between
two direct files now explicitly pin `workers_var.set("1")` (matching a convention this
codebase already established for one folder-based pause test) -- they test the
boundary semantics, not worker count, and pinning isolates that concern cleanly rather
than leaving them to race real concurrency. Retry Failed needed no change: neither
change here is a new user-facing option, so `epub2tts_gui.freeze_tts_options` is
unaffected and a retry still replays the original frozen `RunSnapshot` untouched.

**Verification.** New `files/tests/test_tts_worker_concurrency.py` (25 tests):
`resolve_effective_workers` at representative 1/2/4/oversized requests and backend
differences; the unified dispatch still routes every item through its correct engine;
truthful requested-vs-effective logging including an oversized-request case; real
overlap proof for folder-Edge and Kokoro under workers=2/4; the Chatterbox
non-overlap proof; a proof that a success finishing during cancellation is still
recorded, not orphaned; and two focused tests against the real
`runner.run_conversion_job` proving the new cwd-isolation lock actually prevents two
direct conversions from being inside `read_book` at once, and that a conversion
cancelled while queued behind that lock never starts real work. Full `pytest`: 7542
passed, 57 skipped, zero failures. `scripts/verify.py`: RESULT: PASS.

**Not touched in this drop:** Phase 7 (Compact TTS UI) -- the workers spinbox's
1-16 range and its display are unchanged; showing the resolved effective count in the
UI itself belongs to that later phase, not this one.

-- Implemented by Claude Code per the maintainer's Phase 6 concurrency-subtask
authorization, 2026-09-21

---

## 2026-09-21 — v0.6.5 Phase 6: approved Phase 5 audio changes integrated into
production (Edge PCM assembly + i.e./e.g. fix; Chatterbox structural-colon normalization)

**Decision/integration (not a new listening judgment — implements verdicts already
recorded below, in this same file).** Per the maintainer's authorization to close Phase 5
and execute only the Phase 6 AUDIO-INTEGRATION subtask, the following previously-approved-
but-unintegrated candidates are now live in production:

1. **Edge direct/rich PCM-domain assembly** (approved iteration 1/4, below):
`epub2tts_edge.read_book`'s per-sentence/per-sub-chunk trim/intra-pause/sentence-pause work
now stays in memory as pydub `AudioSegment` objects, from the raw Edge network bytes through
to each paragraph's own FLAC export, removing the 3-5 avoidable intermediate lossy MP3
re-encodes per multi-sub sentence that existed before. Paragraph/chapter FLAC and the final
single lossy encode (`make_mp3`/`make_m4b`) are unchanged.
2. **NLTK/Punkt `abbrev_types` extension** (approved iteration 2/4, below):
`epub2tts_edge.sent_tokenize` now wraps a deep-copied Punkt tokenizer with "i.e"/"e.g" added
to its `abbrev_types` set, fixing the false sentence-boundary split with zero regression on
any other false-boundary marker. NLTK's own shared cached tokenizer is never mutated (a
deep copy is extended instead).
3. **Chatterbox structural-colon normalization** (approved iteration 5, below):
`chatterbox_synth._structural_colon_punc_norm` replaces the pinned wheel's own blanket
colon-to-comma replacement, preserving structured colons (times, ratios, `://` URL schemes)
while retaining today's prose-colon-to-comma behavior. Applied by monkeypatching
`chatterbox.tts_turbo.punc_norm` at model-load time (`_ensure_structural_colon_patch`,
called from `_instantiate_model`) -- the installed wheel is never edited on disk, and the
patch is idempotent (applied once per process).
4. **Terminal pause-supersede candidate remains rejected** (iteration 3 verdict, below) --
current pause constants/stacking are completely untouched by this integration.
5. **Chatterbox HTTPS URL pronunciation remains model-native/deferred** (iteration 6
finding, below) -- no dictionary/word hack was added; this residual issue is unchanged.
6. **Current Chatterbox generation settings (`generation_params()`) are unchanged. Kokoro
is unchanged.**

**Direct-vs-folder audio-quality semantics unified.** Before this integration, the Edge
direct/rich path performed multiple avoidable lossy MP3 re-encodes per multi-sub sentence
while the Edge folder/batch path (`batch_convert.merge_mp3s`) already decoded each network
chunk once and performed exactly one final lossy encode. Both paths now share the same
contract: raw Edge network audio is decoded once and assembled in PCM, with exactly one
final lossy encode producing the output artifact. Segmentation/pause granularity between
the two paths remains intentionally different (a separate, larger, unauthorized scope --
plan Section 15 explicitly forbids the previously-rejected sentence-pause-parity rewrite
without new evidence); "quality semantics" here means the no-avoidable-lossy-generation
contract, not identical segmentation.

**Retry Failed reproduces the original attempt.** Neither integrated change is a new
user-facing option -- both are unconditional engine-internal behavior with no new field in
`epub2tts_gui.freeze_tts_options`. `retry_failed` re-uses the original frozen `RunSnapshot`
rather than re-reading configuration, so nothing about this integration can behave
differently between an original attempt and its retry.

**Verification.** Full `pytest` suite: 7517 passed, 57 skipped, zero failures (611-623s).
`scripts/verify.py` -> **RESULT: PASS** (pytest/deps/docs/docnames/config all PASS). New
tracked tests: `files/tests/test_edge_direct_pcm_assembly.py` (9 tests -- zero intermediate
MP3 encodes during `read_book`, valid decodable output, pause values preserved, the
i.e./e.g. fix proven against production's own tokenizer with no regression on any other
false-boundary marker, and proof NLTK's shared cached tokenizer is never mutated) and
`files/tests/test_chatterbox_colon_integration.py` (9 tests -- structural colons preserved,
prose colons still converted, byte-parity with the real wheel's `punc_norm` on non-colon
text as a future-wheel-version drift guard, patch-helper idempotency/narrowness, and a
static guard that `_instantiate_model` still calls the patch). `test_segmentation_source_
span.py`'s and `test_chatterbox_punc_norm_evidence.py`'s "found, not fixed" sections were
updated (docstrings only, no assertion changed) to document that they exercise the raw,
unpatched upstream/stock behavior that motivated -- and remains distinct from -- the
now-integrated production fix.

**Not touched in this drop:** the Phase 6 file-worker/concurrency subtask (explicitly out
of scope for this run -- a hard stop per instruction).

-- Integrated by Claude Code per the maintainer's Phase 6 audio-integration authorization
(implementing verdicts already recorded below, not a new subjective judgment), 2026-09-21

---

## 2026-09-21 — v0.6.5 Phase 5 iteration 6 finding: residual Chatterbox URL pronunciation is
model-native under the pinned tokenizer; no general structural candidate justified

**Finding, not a fix (investigation-only; no production file changed, no generation parameter
tuned, no candidate built or integrated).** Per the maintainer's iteration 5 verdict (below), the
approved structural-colon candidate was used as the baseline for this diagnostic, so colon
corruption is no longer a variable.

**1. Mechanical localization, source URL → approved normalization → tokenizer text/tokens →
generation input, across a 10-case diagnostic matrix** (scheme presence/absence/word choice,
domain-only, path-only, a generic path word, query-string punctuation, and a domain-dot-at-a-real-
sentence-boundary control), all using the real production tokenizer loaded from the pinned model:
- The scheme word (`"https"`/`"http"`) tokenizes as a single, ordinary, unfragmented token in every
  case — not the rarity/fragmentation pattern that would explain an unstable reading by itself.
  (`"ftp"`, untested by the maintainer, does fragment into two tokens — noted, not pursued further.)
- `"://"` is a single dedicated token, confirmed present and unchanged regardless of scheme choice —
  the approved colon candidate's fix holds.
- Path and query punctuation (`/`, `-`, `?`, `=`, `&`) all tokenize as clean, ordinary, unambiguous
  single tokens in every variant tested — no fragmentation or structural anomaly found there.
- **The one confirmed structural fact:** the domain-boundary `"."` in `"example.com"` is the *same
  token id* as an ordinary sentence-final period, in every variant tested, with or without a scheme,
  with or without a path. The pinned tokenizer gives the model no signal distinguishing "this period
  ends a domain" from "this period ends a sentence."
- The original test URL's `"lighthouse-log"` path fragmenting into `"l"` + `"ighthouse"` was
  confirmed to be an artifact of that specific English word's rarity in this vocabulary, **not a URL-
  structural issue** — a generic path word (`"page"`) tokenizes as one clean token in the identical
  position.

**2. No general structural candidate is justified.** The domain-dot/sentence-dot token identity is
real, but no permitted normalization can resolve it: any change that would make the model reliably
render a domain dot differently from a sentence-ending dot amounts to inserting a pronunciation cue
(effectively spelling out "dot"), which is a forbidden word-substitution/phonetic-respelling
technique, not a structural rule. Every other URL component (scheme word, `"://"`, path, query
punctuation) already tokenizes cleanly with no fixable ambiguity to target. **Per the phase's explicit
fallback, this stops here rather than forcing a workaround: the residual URL-reading imperfection is
best classified as model-native** (an inherently rare "read a URL aloud" utterance shape, and/or the
model's own acronym/domain-dot handling) — not a text-normalization gap this investigation can close.

**Consequences:** No candidate was built; no A/B was run; no tracked test was added (the finding
requires loading the real pinned model/tokenizer, which does not belong in the ordinary fast tracked
suite, matching how other model-requiring findings — e.g., the Phase 3 Male-1 gap analysis — were
handled: documented as evidence, not promoted to a tracked test). The disposable diagnostic script
and its full output remain at `files/dev-work/v0.6.5-phase5-chatterbox-url-diagnostic/`
(gitignored). This closes the URL-pronunciation thread for Phase 5 unless new evidence (e.g., a
demonstrated case with a genuinely different failure shape) reopens it; per instruction, this does
not move to generation-parameter research in this run.

— Investigated by Claude Code per the maintainer's Phase 5 authorization; no maintainer ruling
required (investigation-only, no subjective judgment made), 2026-09-21

---

## 2026-09-21 — v0.6.5 Phase 5 iteration 5 verdict: approved structural-colon candidate carried
forward for later integration; HTTPS URL pronunciation still fails

**Decision.** Having listened to all three seeded A/B pairs from the fifth Phase 5 A/B experiment
(the structural-colon-preserving `punc_norm` candidate against the pinned wheel's own blanket
colon-to-comma replacement, on `chatterbox-male-1`), the maintainer reported, per seed and per test
case:

- **Seed 0: B preferred. Seed 1: B preferred. Seed 2: B preferred.**
- **6:45 / 7:15: B PASS. 3:1: B PASS. Ordinary prose colon: B PASS.**
- **HTTPS URL: still FAIL** (both A and B render it incorrectly — the colon fix did not resolve the
  URL specifically).
- **Overall: B preferred.**

**Ruling: carry the structural-colon normalization candidate forward for later Phase 6
integration. Do not integrate it yet.** The residual URL failure is carried into a further,
targeted Phase 5 iteration (recorded separately above) rather than blocking this candidate's
approval — the colon fix demonstrably resolved times, ratios, and prose colons; the URL's remaining
problem is evidently a separate, additional issue.

— Decided by maintainer (Elijah Matthew) after listening to the Phase 5 iteration 5 A/B artifacts;
recorded by Claude Code, 2026-09-21

---

## 2026-09-21 — v0.6.5 Phase 5 iteration 5 finding: the pinned chatterbox-tts==0.1.7 wheel corrupts
structural colons before tokenization; a structural (non-word-specific) candidate fixes it, not adopted

**Finding, not a fix (investigation-only; no production file changed, no generation parameter
tuned).** Traced Phase 4's cleared-for-segmentation times/ratio/URL pronunciation inconsistency one
level deeper, into the exact installed `chatterbox-tts==0.1.7` wheel `chatterbox.tts_turbo` uses.

**1. Root cause: `chatterbox.tts_turbo.punc_norm()`, called unconditionally immediately before
tokenization inside `ChatterboxTurboTTS.generate()`, performs a blanket `text.replace(":", ",")`
with no context awareness.** This is internal to the pinned wheel — nothing in `chatterbox_synth.py`
does this or could prevent it without intercepting `punc_norm` itself. "6:45" becomes "6,45"; "3:1"
becomes "3,1"; "https://example.com" becomes "https,//example.com", destroying the URL scheme
separator. Tokenizer-level proof (not just string-level): "6:45" tokenizes to `[21, 25, 2231]` but
what the model actually receives, "6,45", tokenizes to `[21, 11, 2231]` — token 25 (":") replaced by
token 11 (","), a real change to the model's input. The URL case loses a dedicated single token for
"://" (1378) entirely, re-tokenizing into unrelated pieces instead.

**2. This is a different symptom from the historical Phase 12 finding already recorded in
`chatterbox_synth.py`'s own comments** ("a text-only fix is impossible... the pause therefore has to
come from assembly"). That investigation was about recovering *pause duration* after a prose colon
(every spacing variant collapses to the same comma, so `COLON_PAUSE_MS`/`split_at_prose_colon`
supply the pause at the assembly level instead, unchanged by this finding). This finding is about
*pronunciation correctness* of structured digit:digit and URL-scheme colons, which
`split_at_prose_colon` never touches (no whitespace follows those colons, so they reach `generate()`
unprotected).

**3. A structural, non-word-specific candidate was built and evaluated, not adopted.** A colon is
replaced with a comma only when followed by whitespace or end-of-string (a prose colon — the same
principle `chatterbox_synth._PROSE_COLON` already uses elsewhere in this codebase); a colon
immediately followed by a non-whitespace character (any digit:digit form, any `://` URL scheme, or
any other structural use) is left untouched. One general regex rule, not a dictionary, not special-
cased to any exact string. Verified: preserves all four structural cases tested (both times, the
ratio, the URL) and leaves the ordinary prose-colon case byte-for-byte identical to today's behavior
(tokenizer ids confirmed identical for that case). Verified against the real, unmodified production
chunking of `quality_corpus.DIFFICULT_SHORT`: the candidate's output differs from the real wheel's
at exactly the 4 structural-colon character positions across the 4 real chunks, and nowhere else.

**4. Evaluated across 3 matched seeds (`chatterbox-male-1`, real reference conditioning, current
production `generation_params()` unchanged) for a small repeated set rather than one pair, since
generation is stochastic.** All 6 files (3 seeds × 2 sides) produced valid, non-clipping audio;
durations stayed in the expected 74–82 s range for this text at this voice. No listening verdict was
requested or given in this finding — evidence only, per the plan's investigation order.

**Consequences:** `files/tests/test_chatterbox_punc_norm_evidence.py` added (6 tests, all passing,
no model/network required — pure text-function tests) documenting the found defect and the
ordinary-prose-colon non-defect, in the same "found, not fixed" spirit as the existing Ascended/
Tamar and NLTK i.e./e.g. guards. No `chatterbox_synth.py` line changed; the installed wheel was never
edited on disk. The candidate remains a Phase 5 finding only — whether to adopt it (and by what
mechanism, since it cannot be shipped by editing the pinned third-party wheel) is a decision for a
later Phase 5 iteration or Phase 6, not made here.

— Investigated by Claude Code per the maintainer's Phase 5 authorization; no maintainer ruling
required (investigation/candidate-evaluation only, no subjective judgment made), 2026-09-21

---

## 2026-09-21 — v0.6.5 Phase 5 iteration 4 verdict: combined Edge candidate (PCM assembly +
abbrev_types segmentation) APPROVED for Phase 6 integration, not integrated yet

**Decision.** Having listened to the neutral-labeled A/B pairs on both `difficult_short` and
`structural_stress` from the fourth Phase 5 A/B experiment — production's Edge direct/rich path
against the two approved candidates combined (PCM-domain assembly, one final encode; NLTK
`abbrev_types` i.e./e.g. fix; current pause behavior unchanged) — the maintainer **preferred
candidate B on both texts.**

**Ruling:** the **combined Edge candidate is APPROVED for later Phase 6 integration**:
1. PCM-domain direct/rich assembly with one final MP3 encode.
2. NLTK/Punkt `abbrev_types` extension for i.e./e.g.

**Current production terminal-pause behavior remains unchanged** (iteration 3's candidate stays
rejected). **Do not integrate any Edge candidate yet** — Phase 5 continues (Chatterbox work is next)
before any Phase 6 integration phase begins. The disposable build scripts and evidence for all four
Edge iterations remain under `files/dev-work/v0.6.5-phase5-*-ab/` (gitignored), for reference when
Phase 6 integration is eventually authorized.

— Decided by maintainer (Elijah Matthew) after listening to the Phase 5 iteration 4 A/B artifacts;
recorded by Claude Code, 2026-09-21

---

## 2026-09-21 — v0.6.5 Phase 5 iteration 3 verdict: terminal pause-supersede candidate REJECTED

**Decision.** Having listened to the neutral-labeled A/B pairs for both test texts
(`structural_stress` and `two_chapter`) from the third Phase 5 A/B experiment — current production's
stacked terminal silence (paragraphpause + chapter_trailing_pause + end_of_book_pause, ~5.9–5.97 s)
against the candidate that lets `end_of_book_pause` supersede the lower-level pauses at the book's
terminal boundary (~3.0–3.1 s) — the maintainer reported **no preference on either text and could
not perceive a meaningful difference.**

**Ruling: the terminal-pause-supersede candidate is NOT approved for integration.** Current
production pause behavior — including the terminal stacking the candidate targeted — is
**preserved unless later evidence justifies revisiting it.** This is a rejection, not a deferral:
future Phase 5 work should not re-propose the same candidate without new evidence.

**What remains approved:** only the two candidates from iterations 1 and 2 (PCM-domain assembly;
NLTK `abbrev_types` i.e./e.g. extension) — both still unintegrated, pending further Phase 5 work
(including a combined-compatibility check) before any Phase 6 integration.

— Decided by maintainer (Elijah Matthew) after listening to the Phase 5 iteration 3 A/B artifacts;
recorded by Claude Code, 2026-09-21

---

## 2026-09-21 — v0.6.5 Phase 5 iteration 2 verdict: NLTK abbrev_types i.e./e.g. segmentation
candidate approved for later integration, not integrated yet

**Decision.** Having listened to the neutral-labeled `A.mp3` (current production Punkt
segmentation, which false-splits at "i.e."/"e.g.") and `B.mp3` (the same production code with
`sent_tokenize` swapped for NLTK's own default Punkt model plus `"i.e"`/`"e.g"` added to its
existing `abbrev_types` set — no new dependency, assembly/encoding held constant) from the second
Phase 5 A/B experiment, the maintainer **preferred candidate B**, noting the audible difference was
subtle, and preferred **B's slightly shorter/more natural gaps.**

**Ruling:** carry the NLTK/Punkt `abbrev_types` candidate forward for later integration. **Do not
integrate it yet** — Phase 5 continues with further isolated experiments before any integration
phase begins.

**What this does and does not authorize.** This is a listening verdict on the mechanically
demonstrated difference (10 vs. 8 sentences on `DIFFICULT_SHORT`; identical trailing silence and
segmentation on every other corpus item; ~1,842 ms shorter duration from two fewer 800 ms
sentence-pauses; ~0.1 dB dBFS difference, consistent with assembly being held constant) — it does not
by itself authorize touching `epub2tts_edge.py`, does not combine with the iteration 1 assembly
candidate (also approved, also not yet integrated), and does not open Phase 6. The disposable build
script and evidence remain at `files/dev-work/v0.6.5-phase5-segmentation-ab/` (gitignored), for
reference when Phase 6 integration is eventually authorized.

— Decided by maintainer (Elijah Matthew) after listening to the Phase 5 iteration 2 A/B artifacts;
recorded by Claude Code, 2026-09-21

---

## 2026-09-21 — v0.6.5 Phase 5 iteration 1 verdict: Edge PCM-domain assembly (candidate B) approved
for Phase 6 integration, not integrated yet

**Decision.** Having listened to the neutral-labeled `A.mp3` (real production direct/rich assembly)
and `B.mp3` (the same raw Edge network audio, same segmentation, same pause constants/order, same
final format, reassembled in a PCM/lossless domain with exactly one final MP3 encode instead of A's
3–5 avoidable intermediate re-encodes per multi-sub sentence) from the first Phase 5 A/B experiment,
the maintainer **preferred candidate B — it sounds clearer.**

**Ruling:** carry candidate B forward as the **approved** assembly candidate for later Phase 6
integration. **Do not integrate it yet** — Phase 5 continues with further isolated experiments
(segmentation, pause policy, Chatterbox) before any integration phase begins.

**What this does and does not authorize.** This is a listening verdict on the *mechanically
demonstrated* difference (196 vs. 61 MP3 encode generations for the measured corpus item; 1.56 dB
speech-only level shift; identical duration, trailing silence, and segmentation otherwise) — it does
not by itself authorize touching `epub2tts_edge.py`, does not combine with any other Phase 5
variable (segmentation, pause values), and does not open Phase 6. The disposable build script and
evidence remain at `files/dev-work/v0.6.5-phase5-edge-ab/` (gitignored), for reference when Phase 6
integration is eventually authorized.

— Decided by maintainer (Elijah Matthew) after listening to the Phase 5 iteration 1 A/B artifacts;
recorded by Claude Code, 2026-09-21

---

## 2026-09-20 — v0.6.5 Phase 4 findings: a real NLTK/Punkt false-split on Edge's direct path;
Male-1's gap and slow cadence are model-native, not segmentation

**Finding, not a fix (Phase 4 is investigation-only per plan §15; no production file changed, no
generation parameter tuned).** Proved source-span coverage across all four segmentation paths and
traced every demonstrated Phase 1/3 Chatterbox defect to its cause, per the plan's explicit
investigation order (segmentation/context first, generation-parameter tuning only later and only if
authorized).

**1. Source-span coverage proven for all four current paths, two of which had no runtime guard
before this phase.** New `files/tests/test_segmentation_source_span.py` (37 tests) proves, against
the real QA corpus, that `chatterbox_synth.split_for_chatterbox`, `batch_convert.split_into_chunks`,
`kokoro_synth.split_into_chunks`, and the Edge direct/rich path's own NLTK `sent_tokenize` +
`intra_sentence_chunks` composition all preserve every non-whitespace character, in order.
Chatterbox already enforced this in production (`ChunkPlanError`); the other three did not.

**2. One real, demonstrated segmentation defect was found, specific to Edge's direct/rich path.**
That path inserts an audible 800 ms `sentencepause` after every NLTK `sent_tokenize` boundary, and
Punkt incorrectly treats "i.e." and "e.g." as sentence-ending abbreviations on the plan's
`DIFFICULT_SHORT` false-boundary corpus — splitting one continuous sentence into three, each
boundary earning an unwanted mid-sentence pause. "vs." and every title abbreviation (Dr./Mr./Mrs./
Prof.) are handled correctly by the same tokenizer on the same text, so this is a specific, narrow
gap, not a general failure. Chatterbox's final packed chunks never split any of the 13 false-boundary
markers (over-splitting at the sentence level is harmless there — packing rejoins consecutive units
with a plain space and no pause, absent a coincidence with the 300-char ceiling); Edge folder/batch
and Kokoro never split this corpus item at all (under both ceilings). The defect is therefore
Edge-direct-path-specific: the other three paths never pause per NLTK sentence.

**3. A bounded pysbd evaluation was performed and is not adopted.** The i.e./e.g. finding meets the
plan's bar for comparing NLTK/Punkt against pysbd. pysbd was installed only into an isolated
`pip install --target` scratch directory under `files/dev-work/` — never added to
`requirements.txt`, never imported by production code or by the tracked test suite — and run against
the identical corpus: zero false splits at "i.e."/"e.g." and no regression on any of the other 12
markers, with content-preservation intact. This is real, evidence-backed grounds for Phase 5's
decision gate (adopt pysbd, patch an abbreviation exception list, or accept the gap as-is); no
dependency was added and no code path was changed.

**4. Times, a ratio, and the HTTPS URL reach every engine's model input as one intact, unsplit
string.** "6:45", "7:15", "3:1", and `https://example.com/lighthouse-log` survive whole in all four
paths — the prose-colon rule correctly excludes them because none has whitespace immediately after
its colon. Since the text is byte-identical across voices, any cross-voice reading inconsistency for
these strings is necessarily model-native sampling behavior, not a segmentation or context-loss
defect. No dictionary replacement, per-word hack, or source-text rewrite was made or considered.

**5. Chatterbox Male-1's ~11.8 s gap (Phase 3: localized to generation output) does not reproduce on
identical input, confirming model-native sampling rather than a structural/chunk defect.** Real
production `chatterbox_file_to_mp3` was re-run against the exact `LONGER_STRESS` text for
`chatterbox-male-1`, instrumented to scan each chunk's own raw PCM for internal quiet spans before
MP3 encoding. Result: 51 chunks, zero raw newlines survived into any `generate()` call (the v0.6.1
Phase 12 fix still holds), and zero chunks produced an internal quiet span ≥3 s anywhere — the exact
class of anomaly Phase 3 found. This run's own reconstructed timeline places chunk 10 of 51 at
130.540 s–151.895 s, almost exactly bracketing Phase 3's original 140.520 s–152.300 s gap — strong
circumstantial localization to that chunk's text (clean prose, one ordinary mid-sentence colon, no
newline/ellipsis/dialogue quote), which rendered normally this time. The same clean text and the
same deterministic chunk boundaries produced the anomaly once and not the next time: this rules out a
chunk-boundary or segmentation cause and is consistent with rare, non-deterministic model-sampling
behavior, unlike the historical Chapter 1144 newline defect, which was 100% text-reproducible.

**6. Male-1's slower cadence is cleared of a segmentation cause by the same logic.**
`split_for_chatterbox` takes no voice parameter, so chunk boundaries, chunk count, and total
inserted pause time are identical across Chatterbox voices for the same text. Yet the Phase 1
manifest shows Male-1 consistently renders ~13–15% more total duration than Female-1 for the exact
same text across three different-length samples (76.00 vs 67.12 s; 335.86 vs 294.77 s; 730.40 vs
637.80 s) — a consistency across text lengths far exceeding what the one isolated 11.8 s anomaly
could explain, pointing to a genuinely slower per-word speech rate as an inherent characteristic of
that voice's reference conditioning: model-native, not segmentation-driven.

**Consequences:** No `chatterbox_synth.py`, `batch_convert.py`, `kokoro_synth.py`, or
`epub2tts_edge.py` line changed; no generation parameter tuned. `files/tests/test_segmentation_source_
span.py` added (37 tests, all passing) — content preservation (20), false-boundary marker survival
in Chatterbox and Edge folder/batch (14), and one test documenting (not asserting as correct) the
NLTK i.e./e.g. false split, in the same spirit as the existing Ascended/Tamar guards (P9): expected to
need updating if a future phase fixes it. Phase 5 inherits three real decisions: whether to address
the NLTK false split (pysbd is now an evidenced, non-adopted candidate); how to treat Male-1's slower
cadence and rare silence anomaly (both model-native — mitigation, if any, is generation-parameter
research, or accept as inherent voice character); and that no segmentation remedy exists for the
times/URL pronunciation variance, so P9's no-hack rule leaves it either accepted or unaddressed.

— Investigated by Claude Code per the maintainer's Phase 4 authorization; no maintainer ruling
required (investigation-only, no subjective judgment made), 2026-09-20

---

## 2026-09-20 — v0.6.5 Phase 3 findings: Edge's direct/rich path has a demonstrable avoidable-re-encode
defect; Chatterbox Male-1's ~11.8s gap is generation output, not assembly

**Finding, not a fix (Phase 3 is investigation-only per plan §15; no production file changed).**
Root-caused, with mechanical instrumentation rather than arithmetic guesswork, the trailing-silence
and re-encode questions plan §6/§7 raised about Edge's three assembly paths, and localized (without
opening Phase 4's text-correlation work) the Chatterbox Male-1 long-silence class of defect.

**1. Edge's direct/rich path (`epub2tts_edge.py`) re-encodes the same sentence audio 3–5 times
before the paragraph ever reaches lossless FLAC.** `trim_tts_chunk_file` and `append_silence` are
both pure PCM edits (trim silence; append digital zeros) but both write back through
`_export_audio`, which re-encodes to MP3 purely because the temp file's extension is `.mp3`. A
temporary instrumentation wrapper around `_export_audio`/`run_edgespeak` (removed immediately after
one measurement call; no production line touched) counted, on a real run: raw-network(1) →
trim-reencode(2) → pause-reencode(3) for a plain sentence, and up to 5 generations for a
comma/ellipsis/dash-split one. `folder_batch` (`batch_convert.merge_mp3s`) needs only 2 (raw +
one unavoidable merge-encode to stitch independently-fetched network chunks) — the same overhead its
historical v0.5.0-era reference already carried. This is the *identical* anti-pattern this codebase
already found and fixed for both other engines: Chatterbox's own code comment records measuring
5.67 dB of SNR lost to one unnecessary MP3 generation before switching to assemble-in-PCM/encode-once
(v0.6.1 Plan 4 Phase 12); Kokoro already does the same. Measured confirmation: speech-only dBFS
(leading/trailing silence excluded, so this cannot be silence dilution) is −19.20 dBFS raw, −19.66
dBFS folder/batch, **−21.32 dBFS direct** — a genuine ~2.1 dB shift consistent with the maintainer's
"more noticeable background/static" report on the direct path specifically.

**2. The three-path trailing-silence progression (raw 860 ms → folder/batch 3,930 ms → direct
5,860 ms) is fully explained by configured constants stacking, not a bug in any single constant.**
Direct's 5,860 ms = `paragraphpause` (850 ms, baked into the last sentence) + `chapter_trailing_pause`
(2,000 ms) + `end_of_book_pause` (3,000 ms) = 5,850 ms configured + ~10 ms natural residual, confirmed
stage-by-stage by the same instrumentation. Folder/batch's 3,930 ms = the raw chunk's own ~860 ms
tail + `CHUNK_PAUSE_MS` (50 ms, applied unconditionally even after the last chunk) +
`END_RECORDING_SILENCE_MS` (3,000 ms) = 3,910 ms predicted vs. 3,930 ms measured. Left as an open
question for Phase 4/5: `chapter_trailing_pause`/`end_of_book_pause` each fire only once per real
book (the true last chapter), so this 5.86 s stack may be an artifact of testing a short
single-chapter QA item rather than a defect that shows up in a real multi-chapter book — not tested.

**3. Chatterbox Male-1's confirmed ~11.8 s internal near-silence is generation output, not
assembly/silence-insertion, not encoding, and not duration/container handling.** Localized (no
resynthesis — read the existing Phase 1 evidence file) to
`files/dev-work/quality-suite/chatterbox_chatterbox-male-1/longer_stress.mp3`, 140.520 s–152.300 s
(11,780 ms, matching "~11.8 seconds" exactly), using the same exact-zero-sample-run-vs-model-floor
technique the v0.6.1 Plan 4 Phase 12 silence audit used to separate assembly's inserted `np.zeros`
(which survive MP3 encode as literal digital zero) from the model's own near-silent output (never
exact zero). The span is 99.5% non-exact-zero, RMS −66.79 dBFS against ≈−26 dBFS in the immediately
surrounding speech, with a measurable −32.7 dBFS peak — not digital silence, and not bordered by any
assembly-inserted exact-zero run (the file's only long exact-zero run is its intentional 3.05 s
terminal end-silence). Same *class* of defect as the historically-diagnosed Chapter 1144
dialogue-quote sentence-boundary case, but the specific text cause was deliberately not chased —
that correlation work belongs to Phase 4, per the plan's explicit investigation order.

**4. Kokoro inspected, confirmed clean, not touched.** `kokoro_synth.py` already assembles every
chunk in PCM and encodes to MP3 exactly once, matching Chatterbox's fixed pattern; no defect found,
nothing retuned.

**Consequences:** No `voice_registry.py`, `epub2tts_edge.py`, `batch_convert.py`,
`chatterbox_synth.py`, or `kokoro_synth.py` line changed. Two disposable, gitignored QA scripts were
written under `files/dev-work/` (`v0.6.5-phase3-edge-audit/instrument_direct_path.py`,
`v0.6.5-phase3-chatterbox-audit/localize_silence.py`) for Phase 5 to reuse when A/B-testing a
candidate PCM-domain redesign of the direct/rich path's trim/pause steps — no candidate was selected
or integrated. Phase 4 inherits: the Male-1 text-correlation question, and whether the direct path's
silence stacking is a real-book problem. Phase 5 inherits: the demonstrated avoidable-re-encode
finding as its leading Edge assembly candidate.

— Investigated by Claude Code per the maintainer's Phase 3 authorization; no maintainer ruling
required (investigation-only, no subjective judgment made), 2026-09-20

---

## 2026-09-20 — MP3 Time calculations and validation use fully decoded audio duration

**Decision (maintainer-authorized MP3 defect remediation on the v0.6.5 branch; no phase
advance).** Keep the public `mp3_processing.ffprobe_duration_seconds` name for compatibility,
but replace its header-only ffprobe query with a full decode through the existing proved
FFmpeg and hidden-console subprocess wrapper. Map `0:a:0`, rebuild timestamps using
`asetpts=N/SR/TB`, encode PCM to the null muxer, and read the final machine-readable
`out_time_us` in seconds. This measures actual decoded samples after decoder delay/padding,
without retaining PCM or per-frame JSON in Python and without writing temporary audio.

Require exit zero, no error-level stderr, positive duration and `progress=end`; use `-xerror`
to stop on decoding errors. Disable speculative stream-info decoding with
`-nofind_stream_info`: malformed source cover images are discarded by the MP3 Tool and
must not invalidate otherwise good audio. Audio decoding itself remains strict. The same
measurement applies before trim endpoints are calculated and when staged/combined audio is
validated. Existing tolerances, transforms, metadata rules and atomic publication stay intact.

**Why.** A 49-track Write ID3 +0.1 run failed only its split author-note source: its Info
header claimed 17,612 frames / 3,680,757 bytes, but the first piece held 16,306 frames and the
companion the other 1,306; their combined MPEG byte counts matched the retained header exactly.
Quick ffprobe and Mutagen both reported 460.068571 s, whereas only 425.940658 s decoded. The
transformation correctly produced 426.040658 s and tag/artwork writes did not alter the audio.
Zero Time also false-failed; -0.1 targeted an endpoint beyond EOF and removed nothing. Combine
shares that endpoint calculation, so a fallback only after failed Write ID3 validation would
leave a real trim defect. Broadening tolerance, swapping to Mutagen/stream.duration, and
special-casing this source were rejected. No FFmpeg upgrade is needed.

**Tradeoff and proof.** A full sequential decode costs more than reading a header, but observes
the exact audio available to the operation, catches decode errors and works for CBR/VBR and
headerless inputs. On this Mac all 49 real originals measured in about 21 s. Production
stage/tag/validate reproductions at +0.1/zero/-0.1 changed decoded sample counts by exactly
+4,410/0/-4,410. The 24-case synthetic regression in `test_mp3_duration_authority.py` uses raw
PCM length independently, includes MPEG-1 Info and MPEG-2 Xing splits and Combine FAST/Safe,
and refuses genuinely shortened output even when its header still claims the correct length.
No source or failed-run evidence was modified. Windows shares the implementation; its runtime
acceptance remains pending. No v0.6.5 listening or phase gate is superseded.

**Signed:** maintainer (diagnosis approved and implementation directed 2026-09-20);
implemented by the AI session on that authorization.

---

## 2026-09-20 — v0.6.5 Phase 2 closeout: original Male-3 candidate approved and registered; the
bounded pitch-retry variant rejected and its machinery removed entirely

**Decision (v0.6.5 Phase 2, final maintainer ruling).** After hearing both the original Male-3
candidate sample and the §14 bounded pitch-retry variant, the maintainer's ruling: **Male-4 —
approved, unchanged.** **Male-3 original candidate — approved.** **Male-3 pitch-retry variant —
rejected:** "I prefer the original voice exactly as it was before the retry." This supersedes the
2026-09-20 entry below on Male-3's disposition only; that entry's account of what the retry was and
how it was built stands as an accurate historical record of a rejected approach, not of anything
still in the codebase.

**1. Original Male-3 is registered exactly as its untouched candidate sample, with no pitch or
timbre adjustment reaching production.** `chatterbox_synth.REFERENCE_VOICES["chatterbox-male-3"]`
binds to the already-recorded `Male-3.mp3` hash (never recomputed — the source file was never
written to at any point in Phase 2, including during the retry), and `voice_registry.VOICES` gains
`chatterbox-male-3` / "Chatterbox - Male 3" immediately before `chatterbox-male-4`, using the same
shared, unmodified `_chatterbox_preset()` as every other Chatterbox row. `REFERENCE_VOICES` grows
from five to six; the registry total moves from 15 to 16 rows. `CANDIDATE_REFERENCE_VOICES` is now
`{}` — both candidates resolved — but is kept in place as reusable infrastructure for whatever
future candidate a later phase introduces; it is explicitly not retry-specific and was not removed.

**2. The rejected retry's machinery is deleted outright, not deprecated.** Because the maintainer's
own words ("no longer represents supported behavior") ruled out keeping it as dead code behind a
flag, `generate_voice_samples.py` loses `MALE3_RETRY_PITCH_RATIO`, `MALE3_RETRY_SUBDIR`,
`_pitch_shift_preserve_tempo()`, `render_male3_pitch_retry()`, and the
`--chatterbox-male3-pitch-retry` CLI flag with its dispatch branch. `CHATTERBOX_CANDIDATE_VOICE_IDS`
is now `()`. New regression tests in `test_chatterbox_candidates.py` assert each of those symbols
and that CLI flag are gone, so the rejected path cannot silently reappear. The reusable
candidate-evaluation path itself (`run_chatterbox_candidate_evaluation`, the `--chatterbox-candidates`
flag, the candidate text/subdir helpers) is untouched — it is generic infrastructure, not the
rejected mechanism.

**3. No other voice or generation behavior was touched.** Chatterbox generation parameters, pacing,
segmentation, and conditioning logic for every other voice are unchanged; only the registration
state of Male-3 moved from candidate-only to production.

**Consequences:** Twelve tracked test files' Chatterbox-count/voice-count assumptions moved from
15/5 to 16/6 (retargeted, never weakened): `test_chatterbox_boundaries.py`,
`test_chatterbox_candidates.py`, `test_chatterbox_engine.py`, `test_chatterbox_evaluation.py`,
`test_chatterbox_integration.py`, `test_epub_retirement.py`, `test_fatal_diagnostics.py`,
`test_mp3_finalization.py`, `test_tts_importing.py`, `test_tts_jobs.py`, `test_tts_smoke.py`,
`test_voice_labels.py`. Full suite: 7428 passed, 57 skipped, 0 failed, in 9:53; `compileall` clean.
Both `Male-3.mp3` and `Male-4.mp3` re-verified byte-for-byte unchanged against their registered
hashes immediately before this closeout. Phase 2 is fully complete; Phase 3 requires its own
separate authorization.

— Decided by maintainer (Elijah Matthew); implemented by Claude Code, 2026-09-20

---

## 2026-09-20 — v0.6.5 Phase 2 §14 remediation: Male-4 approved and registered; Male-3 rejected for
a single bounded pitch-only retry on a scratch reference-conditioning clip

**Decision (v0.6.5 Phase 2, §14 manual-gate-failure/rollback protocol).** The maintainer's listening
verdict against the two candidate WAVs: **Male-4 — approve.** **Male-3 — reject for bounded retry
only:** "otherwise good, make it ever so slightly deeper... only a very small timbre/pitch
reduction. Do not otherwise change its pacing, generation settings, clarity, or character."

**1. Male-4 is now a registered production voice, exactly as approved.** Moved verbatim from
`chatterbox_synth.CANDIDATE_REFERENCE_VOICES` into the production `REFERENCE_VOICES` (same
`source_name`, same hash — no hash was recomputed, the source file was never touched) and appended
to `voice_registry.VOICES` as `chatterbox-male-4` / "Chatterbox - Male 4", using the exact shared,
unmodified `_chatterbox_preset()` every other Chatterbox row uses (no per-voice tuning, per §6).
`REFERENCE_VOICES` grows from four to five; the existing frozen-set test
(`test_mp3_finalization.py::test_the_settled_chatterbox_values_are_untouched`) is updated to five
with an explanatory comment, not weakened. The registry total moves from 14 to 15 rows; every
count/index-based test across nine files was retargeted to match.

**2. Male-3's retry is a pitch-only adjustment to a scratch copy of its reference-conditioning
clip, never to `Male-3.mp3` and never to the cached production derivative.** New
`generate_voice_samples.render_male3_pitch_retry()` reuses `chatterbox_synth.build_reference_clip`
(the same 15s leading-window extraction production uses) to make a scratch copy, applies a single
ffmpeg `asetrate`+`atempo` pitch shift (no new dependency — ffmpeg is already required and already
the exact binary `build_reference_clip` shells out to) to that copy only, and conditions the model
on the shifted copy directly via `model.prepare_conditionals()` — bypassing the cached
`derivative_path`/`conditionals_path` identity system entirely, so no other voice's cache and no
global generation parameter is touched. Generation itself uses the unmodified
`generation_params()` (current production temperature/top_p/top_k/repetition_penalty) and the same
`CHATTERBOX_CANDIDATE_TEXT` every other candidate reads.

**3. The bounded value: `MALE3_RETRY_PITCH_RATIO = 0.97`** (~3% lower, roughly half a semitone) —
a single value, not a ladder, per the explicit instruction to try one minimal adjustment before
considering anything broader. A real ffmpeg math error was caught and fixed before this value was
trusted: the first attempt used `atempo=pitch_ratio`, which lengthened the reference clip's
duration by ~6.3% instead of preserving it; the corrected filter (`atempo=1/pitch_ratio`) was
verified to hold duration to within 0.05% (15.0000s → 15.0075s) before the real retry was run.

**4. Output goes to a clearly distinct filename beside the original candidate sample, which is
never regenerated or overwritten.** `chatterbox-male-3-pitch-retry.wav`, alongside the untouched
original `chatterbox-male-3.wav`, both under `files/test-for-manual-listen-elmatthe/
chatterbox-candidates/` (gitignored). The retry's own scratch artifacts (the plain and pitch-shifted
reference-conditioning clips) live under `files/dev-work/male-3-pitch-retry/`, separate from any
listening artifact.

**Consequences:** `CHATTERBOX_CANDIDATE_VOICE_IDS` now holds only `chatterbox-male-3`; Male-4 is
removed from the candidate pool entirely (it is production now, not pending). Nine tracked test
files' Chatterbox-count assumptions moved from four to five approved voices, and
`test_chatterbox_candidates.py` was substantially rewritten to reflect Male-4's departure from
"candidate" status and to add coverage for the new retry mechanism (mocked — no real recording,
model, or ffmpeg call). Male-3 remains unapproved and unregistered; only the maintainer's next
listening pass decides whether this one bounded adjustment is sufficient.

— Decided by maintainer (Elijah Matthew) per the plan's §14 protocol; implemented by Claude Code,
2026-09-20

---

## 2026-09-20 — v0.6.5 Phase 2: multilingual Edge voices removed; Male-3/Male-4 evaluated on a
separate candidate path that reuses the production reference/conditioning machinery without
touching it

**Decision (v0.6.5 Phase 2 — voice inventory + Chatterbox candidates).**

**1. `en-US-AndrewMultilingualNeural` and `en-US-AvaMultilingualNeural` are removed from
`voice_registry.VOICES` entirely**, not relabeled or deprecated in place, per the plan's final
voice inventory (Section 3). Fourteen rows remain: five Edge, five Kokoro, four Chatterbox.
Ordinary Andrew and Ava are unaffected. Every count-based test that assumed sixteen/twelve/seven
rows (`test_tts_smoke.py`, `test_voice_labels.py`, `test_chatterbox_boundaries.py`,
`test_chatterbox_evaluation.py`, `test_chatterbox_integration.py`, `test_chatterbox_selected_tuning.py`,
`test_epub_retirement.py`, `test_fatal_diagnostics.py`, `test_tts_importing.py`, `test_tts_jobs.py`)
was updated to the new counts/indices; none had its actual invariant weakened.

**2. Male-3/Male-4 get a genuinely separate evaluation path, not a widened historical one.**
`chatterbox_synth.REFERENCE_VOICES` (the four approved, production voices) is frozen at exactly
four entries — an existing test already pins this
(`test_mp3_finalization.py::test_the_settled_chatterbox_values_are_untouched`) and continues to.
The two candidates live in a new, separate `CANDIDATE_REFERENCE_VOICES` dict instead.
`get_reference_voice(voice_id)` now checks `REFERENCE_VOICES` first, then
`CANDIDATE_REFERENCE_VOICES` — the one seam every existing reference/derivative/conditioning
function (`resolve_reference`, `prepare_reference_clip`, `derivative_path`, `conditionals_path`,
`voice_availability`) already goes through, so candidates get the exact same hash-binding,
derivative-caching and P8 safety contract as the four approved voices for free, with no
duplicated machinery and no risk of a parallel implementation drifting from the original.

**3. Candidates render under current production generation settings
(`generation_params()`), not the historical Phase 9 temperature
(`phase9_evaluation_params()`).** The plan (Section 5) is explicit that candidates are judged
against what an audiobook actually sounds like today, not the historical approval contract the
four-voice evaluation must keep reproducing untouched. `run_chatterbox_evaluation` (the historical
four-voice command) is not modified at all; `run_chatterbox_candidate_evaluation` is a new,
independent function reusing only the generic, already-shared table/report formatters
(`format_chatterbox_table`, and a candidate-specific report wrapper with its own approval-language
footer). Both candidates read the same evaluation sentence the four approved voices did
(`CHATTERBOX_CANDIDATE_TEXT = CHATTERBOX_EVAL_TEXT`), so the comparison is about the voice, not a
different script.

**4. Hashes computed and cross-verified by two independent methods (certutil and Python
hashlib) on HOME-PC, 2026-09-20, against the maintainer-placed files:**
`files/Chatterbox-Voice-Uploads/Male-3.mp3` →
`0bb698d934515c690b97c85922dcfb61a0e2e07f07fd66b4e0b2e8ca13c292c4`;
`files/Chatterbox-Voice-Uploads/Male-4.mp3` →
`1db9bb339748edede0b8d6a20171ea0672e59914516e49fd9b1b910cc6f028f5`. Both files were only ever
read, never written to; `git status` shows no change under `files/Chatterbox-Voice-Uploads/`, and
the hashes were re-verified identical immediately after the candidate WAVs were rendered.

**5. No tracked test touches the real recordings.** Every existing Chatterbox test stubs
`resolve_reference`/`prepare_reference_clip`/etc. at the engine seam rather than reading real
files (`protected_uploads_dir()` monkeypatched to `tmp_path`); the new
`files/tests/test_chatterbox_candidates.py` follows the same convention, so the suite runs
identically on a machine that has never seen the two candidate recordings. Hash verification
against the real files is a one-off manual check recorded here and in `Handoff.md`, not a tracked
test — consistent with how the four approved voices' real files were never asserted against in
the tracked suite either.

**Consequences:** `voice_registry.VOICES` is untouched by this drop — no `chatterbox-male-3` or
`chatterbox-male-4` row exists there, and none will unless and until the maintainer's listening
gate (Section 5) returns a `YES` for a given candidate in a later phase. `REFERENCE_VOICES`
remaining frozen at four is a private implementation detail of `chatterbox_synth.py`, not
something Phase 2 is scoped to change.

— Decided by maintainer (Elijah Matthew) per the plan; implemented by Claude Code, 2026-09-20

---

## 2026-09-20 — The chapter-title remux pins its movie timescale, an ffmpeg error is a failure at any exit status, and chapter validation reads structure, not titles

**Decision (v0.6.4 defect, bounded remediation carried onto `feature/0.6.5-tts-quality-refactor`
as a cherry-picked fix commit; no v0.6.5 plan phase is affected).** Three rules, each protected by
a real-FFmpeg test in `files/tests/test_m4b_chapter_remux_timescale.py` and the Editor engine
suite:

1. **`shared.metadata.apply_chapter_titles` passes `-movie_timescale 1000`
   (`CHAPTER_REMUX_MOVIE_TIMESCALE`) and stays `-c copy`.** FFmpeg 9's mov muxer defaults the
   movie timescale to the lcm of the mapped streams' timescales; with 44.1 kHz audio beside a
   1/90000 cover-art video stream the chapter text track lands at 4,410,000 ticks per second and
   every chapter longer than INT_MAX / 4,410,000 ≈ 487 s is dropped from it with exit status 0.
   1000 is what every earlier FFmpeg wrote, what the sources themselves carry, and what the
   Editor's outputs must keep carrying. The M4B Maker's concat maps audio only (lcm 44100, ~13.5 h
   per chapter) and is not changed; the Editor's remux is the one path that maps the cover video.

2. **A `-loglevel error` ffmpeg step that prints anything did not succeed.** At that level the
   only thing ffmpeg can print is an error, and the muxer's "Application provided duration … is
   invalid" was printed and ignored while the exit status said 0. `_run_chapter_remux_step`
   raises `ChapterRemuxError` on any stderr; the copy under edit is untouched and the temporary
   sibling removed. Scoped to the chapter remux — no other ffmpeg call site changed.

3. **Staged validation compares chapter structure with the source.** `validate_chapter_structure`
   requires the same chapter count, boundaries equal within 10 ms (a 1/44100 source rescaled to
   1/1000 moves at most half a millisecond), and — exactly when the remux ran
   (`chapter_titles_retitled`, the same predicate `stage_book` uses) — a QuickTime chapter text
   track with one sample per chapter; when it did not run, the track must simply be unchanged, so
   a `chpl`-only source stays valid. ffprobe merges `chpl` and the text track by id, which is why
   titles alone passed a one-sample track whose surviving title sat at id 0.

**Why the tests missed it.** Every generated fixture had chapters of a few seconds, the Phase 13
positional chapter edit ran on a 50-second fixture, and the real hour-per-chapter file received no
chapter edit. The new fixtures are 660 s with a cover and a 600 s chapter; the negative control
forces the pathological timescale explicitly so the proof does not depend on the host FFmpeg's
default.

**Signed:** maintainer (investigation, remediation and carry-forward directed 2026-09-20);
implemented by the AI session on the maintainer's authorization.

---

## 2026-09-18 — v0.6.4 confirmed merged (PR #11); v0.6.5 identity reassigned to the TTS Quality
Refinement plan; the displaced Plan 9 scope is preserved and marked DISPLACED — FUTURE ALLOCATION
UNASSIGNED

**Decision (v0.6.5 — TTS Quality Refinement, Phase 0).** Fresh `git fetch origin` confirmed
`origin/master` advanced to `1f9bdcf347edaad36d68e237933d3ac6036d0a42` — the merge commit for pull
request #11, merging `feature/0.6.4-m4b-maker-metadata-editor` (tip `f5f3926`). v0.6.4 is therefore
**confirmed merged**, superseding every "not merged" statement recorded in `Handoff.md` and the
Master Index as of the v0.6.4 Phase 15 closeout — those statements were accurate when written and are
not being called wrong, only overtaken by the maintainer's subsequent integration decision.
`feature/0.6.5-tts-quality-refactor` was created from that verified `origin/master` and Phase 0's
baseline/audit work is recorded in `Handoff.md`.

**The v0.6.5 identity is reassigned.** The 2026-07-31 roadmap and every later note through the
2026-09-17 v0.6.4 closeout (including this file's own 2026-09-17 entry) assigned v0.6.5 to **Plan 9 —
remaining Windows UI conversion, macOS parity, QA, docs, and packaging** (proposed filename
`0.6.5-ui-parity-hardening-release.md`). The maintainer has now opened v0.6.5 as a different,
unrelated plan instead: `md-instructions/0.6.5-tts-quality-refactor.md` ("TTS Quality Refinement",
v4 Final), scoped to `scripts/Universal/tts/` audio-quality/UI work, on
`feature/0.6.5-tts-quality-refactor`. Plan 9 was never drafted and no code was ever written against
it, so nothing is reverted — only the version-number binding moves.

**Explicit maintainer ruling on disposition (2026-09-18):** preserve Plan 9's full scope intact —
conversion of all remaining Windows tool panels (TTS Audiobook, M4B Converter, Cover Image Resizer),
macOS parity, full regression/long-run drills, release-package launch testing, and the final
version/tag/release checkpoint — but mark it **"displaced / future allocation unassigned"** rather
than inventing a new version, branch, or plan number for it now. Plan 9 remains real, approved-scope
future work; it simply has no version identity until a later, separate maintainer decision assigns
one.

**Why:** The maintainer chose to spend the v0.6.5 identity on the TTS quality work now rather than on
Plan 9, and preferred to leave Plan 9's renumbering as a genuinely separate future decision rather
than have this Phase 0 checkpoint guess at a v0.6.6 (or later) slot, a branch name, or a sequencing
relative to other future work.

**Consequences:** `don't-delete/Audiobook-Creation-Tool-v0.6.x-Approved-Plan-Series-Map.md` and
`don't-delete/Audiobook-Creation-Tool-v0.6.x-Master-Implementation-Plan-Index.md` each gain a dated
supersession note recording this exact reassignment, following their own existing append/supersede
conventions; neither document's original 2026-07-31/2026-08-03 text is rewritten. Every other
reference to "Plan 9" throughout both documents (ownership of DPI awareness, `.DS_Store` packaging,
the M4B Converter's `920×600` clipping, the three remaining classic panels, the Combobox/title-bar
theming review, the final release-package gate) is unaffected — Plan 9 still owns all of it; only its
"= v0.6.5" binding is removed. No production behavior changed in this checkpoint.

— Decided by maintainer (Elijah Matthew), recorded by Claude Code, 2026-09-18

---

## 2026-09-17 — v0.6.4 closeout: the M4B Maker and M4B Metadata Editor's approved product contracts, and the macOS minimum is 1024×800

**Decision (v0.6.4 — M4B Maker + M4B Metadata Editor, Phase 14 closeout).** Both M4B tools are
rebuilt on the shared multi-Book foundation, accepted on Windows (2026-09-15, Phase 12) and on macOS
(2026-09-15, Phase 13), and these are the rules that outlive the temporary plan that carried them.
Each was approved during the plan, is implemented, and is protected by tests. The Plan 6 Decision
Register 1–55 under `don't-delete/` is not reopened or rewritten; where this entry departs from a
numbered decision or from the 2026-07-31 roadmap, the departure is recorded here as a later, dated
supersession and the original text stands as history.

**One coordinated drop, one branch — the old roadmap split is superseded.** By maintainer ruling on
2026-09-13 the two tools were delivered together as **v0.6.4** on
`feature/0.6.4-m4b-maker-metadata-editor`, replacing the roadmap's "Plan 7 / v0.6.3 Drop 2 = M4B
Maker alone" and "Plan 8 / v0.6.4 = MP3 Tool + M4B Metadata Editor", the later "v0.6.4 Maker, v0.6.5
Metadata Editor" proposal, and the Master Index §15 branch names `feature/0.6.4-m4b-maker` /
`feature/0.6.5-m4b-metadata-editor`. The MP3 half of the old Plan 8 had already shipped in the v0.6.3
focused MP3 redesign. The old Plan 9 assignment — v0.6.5 = final visual parity, hardening, packaging
and release — is unchanged. The two tools remain **two tools**: separate business models, separate
Tk-free engines, no shared processing base class, no generic "M4B mega-tool".

**One foundation, reused rather than re-implemented.** Both panels are thin Tk composition layers
over the same shared authorities the MP3 Tool consumes: `shared/book_workspace(_ui)` (Book identity,
navigation, Shared → Book precedence, `has_meaningful_work`, frozen run capture, retry dispositions),
`shared/importing` + `import_coordination` (the scan), `shared/job_control` + `job_ui` (one
`JobController` / `JobReporter` / `JobAdapter` / `LockGroup` per batch, one `SummaryDetailsView`),
`shared/output_paths` (reservation, sanitiser, collision planner, containment),
`shared/image_capabilities` (the one HEIC probe) and `shared/numbering.SuccessNumbers`. Structural
tests pin that every authority is defined in exactly one module and that no second workspace,
controller, coordinator, reservation, planner, event stream or pump class exists anywhere. Two things
are shared by the M4B family only: `mp3_tools/m4b_artwork(_ui)` (the M4B cover service and its Tk
control) and `mp3_tools/m4b_staging` (the private-staging / atomic-publication pattern both engines
delegate to). `BookNavigator` gained an opt-in action subset so a consumer may offer fewer Book
actions; its default is unchanged for the MP3 Tool.

**M4B Maker: one Book = one directory of MP3s = at most one M4B.** `Import Folder` makes one Book per
directory that directly contains MP3s (natural order, never flattened); `Add Files` extends the
current Book; Add / Duplicate (configuration, no tracks) / Remove / Previous / Next / selector are the
shared operations. **Shared fields are exactly six** — Artist / Author, Album Artist / Author, Album,
Series Name, Silence Between Tracks (seconds), Book Artwork — deliberately not the MP3 Tool's set;
**Book-only fields are Title, Series Part, Output Filename and Chapter Titles**. A populated Shared
value overrides and disables the matching Book control and leaves the Book's stored value intact. The
Maker observes no source ID3 and pre-fills nothing; the metadata vocabulary stays Title, Artist, Album
Artist, Album, Series Name, Series Part and cover — **no Year, Genre or Comment** were added merely
because another M4B component supports them. Silence is a **non-negative** gap inserted between
adjacent tracks only (never after the last; negative refused before any reservation), not the MP3
Tool's signed Time. Chapter titles are positional, one per line, defaulting to cleaned filenames, and
are frozen at Build. Fast-first (default ON) with automatic Safe fallback is preserved, Safe being
mandatory whenever silence is inserted, and the chosen path and any fallback reason are logged.

**Maker naming is Decision 51A through shared authorities only.** The output name resolves from the
explicit Output Filename → effective Title → effective Album → the unambiguous source folder name →
`Book N`, sanitised by the shared cross-platform sanitiser, `.m4b` appended exactly once, collision-
numbered by the shared planner; a blank Title takes the resolved output name as the embedded Title so
no Book is nameless. Filename and embedded Title are two values. Standard runs go directly inside one
reserved `M4B-Maker-N`; the explicit custom destination (Decision 10A) writes directly into the chosen
folder with **no nested run folder**, stages in an operation-owned temporary directory outside it, and
keeps collision safety.

**Series numbering is success-only, on both tools, through the shared allocator.** With Auto-number
ON (Start Part blank = 1; Book Series Part controls disabled) a number is proposed for a staged Book,
written onto the staged file, validated, and **committed only after publication succeeds**; a failed,
skipped or not-attempted Book consumes nothing, so A ✓ / B ✗ / C ✓ yields 1 and 2 with no gap, and a
later Retry Failed of B receives 3. The Editor's former position-based numbering (`start + index`),
which left gaps on failure, is superseded by this contract (Decision 48A applied to both consumers).

**M4B Metadata Editor: one imported file = one Book/page, and blank means preserve.** The Editor
accepts `.m4b`, `.m4a` and `.mp4`; `Import Folder` (with the shared subfolders option) and `Add Files`
create one Book per imported occurrence — the directory-to-Book grouping rule is never applied here —
with Remove / Previous / Next / selector and deliberately **no Add Book and no Duplicate Book**. Each
page is pre-filled from a frozen `SourceObservation` of its own file (seven text fields, series
provenance as `read_m4b_tags` resolves it, cover presence, chapter titles); showing a source value is
never an edit. **Blank Shared + blank/unchanged Book value = preserve the source value; blank does not
mean remove**, and a value retyped equal to its source writes nothing, so a vendor, movement or
album-implied series representation is never silently migrated to the canonical atom. **Shared starts
blank** even when every imported file agrees, so coincidence never becomes a global override; a
populated Shared value is an explicit edit for every Book and disables the matching Book control. The
seven Shared/Book text fields are Title, Author / Artist, Album, Year, Genre, Comment and Series Name,
plus artwork; **Series Part is read-back plus the Auto-number contract, never a text override**.
Chapter titles are positional with **blank-line-preserve** semantics (line N → chapter N; blank or
unchanged = leave it; extra lines ignored) — not the MP3 Tool's blank-line-collapse. No action
re-encodes audio (audio-stream MD5 proved equal).

**Three Editor actions, each a frozen plan.** **Save Tags** writes only actual intent (Shared over
Book), the explicit artwork (Shared → every Book; Book → that Book; none → preserve source artwork)
and explicit chapter edits, and touches nothing else. **Clear All Tags (keep chapters)** copies to
staging, removes identifying metadata and artwork while keeping the chapter structure, and re-applies
**only explicit** Shared/Book values, explicit replacement artwork and explicit chapter edits —
prefilled-but-unchanged values are not re-applied, otherwise the action would not clear. **Remove
Series Numbering** removes the numbering surfaces (`trkn` used as series numbering, movement
index/count, every vendor `…:PART` / `…:SERIES-PART`) and **keeps the Series Name** and every unrelated
tag, cover and chapter; `shared.metadata.clear_series_numbering` gained `keep_series_name=` for it, its
default unchanged. Clear All Tags remains the one wholesale removal. Each action reserves **one**
standard `M4B-Metadata-N` run (no custom destination) and publishes every Book flat inside it under
its own source filename, extension kept, collision-numbered.

**Every Book is staged privately and published whole or not at all.** Both engines build in
`<run>/.work/<stem>/` (the Maker's custom mode in its own temporary root), do all the work there —
audio assembly, chapters, tags, cover, series part, then a read-back validation through the shared
probe/metadata readers — and only then `os.replace` into the destination, refusing an existing file
and routing across filesystems through a plan-owned temporary sibling. A failed or cancelled Book
leaves no partial output and no staging; a publication failure retains the validated candidate for the
retry. This closes the Editor's recorded debt of copying to the final path before the tag write.
Staging cleanup asks the shared reparse-aware link authority: a link inside staging is unlinked as a
link and never followed (a Windows junction is a link too).

**Artwork on M4B is capability-driven and container-native.** The chooser filter is
`decodable_suffixes()` from the one shared probe; JPEG and PNG bytes are embedded as their own format;
HEIC/HEIF are decoded only where the probe says so and converted **in memory** to a PNG `covr` with
pixel dimensions preserved, no sidecar written, the source never resized, cropped or rewritten; an
unavailable capability is a visible refusal in both panels. The Maker resolves the cover **before**
any FFmpeg launch and embeds it on the staged file without re-encoding; the ID3 `apply_artwork` path is
deliberately not reused for MP4 containers.

**One run model and one log region, common to both.** validate → reserve → plan/freeze → lock →
execute → settle → publish; workers receive frozen values only and may consult no Tk variable, live
workspace, Shared value, file list or setting after start; Pause/Resume are acknowledged at safe
checkpoints, Cancel stops at the next boundary keeping published Books and leaving unreached Books
*Not attempted* (no Book-level "cancelled"), a failed Book does not stop later Books, and Retry Failed
re-runs only the failed Books from the original frozen plan in the same run directory. Summary |
Detailed, history kept across runs with a divider per run and per retry, Clear Log clears the visible
text only; no Copy button, no severity selector.

**Clear All Imports (maintainer-directed amendment at Phase 12).** All three multi-Book tools carry one
destructive workspace reset beside Import Folder, styled as the platform's danger button: it returns the
tool to its pristine startup workspace, keeps the visible log history, touches nothing on disk, asks
for confirmation only when meaningful work exists (any Book with work or any populated Shared value),
and is locked out while a run or an import scan is active. The Editor keeps `Clear All Imports`
(workspace) and `Clear All Tags (keep chapters)` (output copies) as two visibly distinct actions.

**Platform presentation, and the macOS minimum is 1024×800.** Windows draws both tools in the ACT
design system at the unchanged `MIN_SIZE = (920, 600)`; macOS draws them natively. Phase 13 measured
both tools in the real launcher under aqua at the 2026-09-12 floor of 1024×720 and found a genuine
Mac-only layout defect whose bounded remedies fold bands onto more lines than a 1024×720 content host
can absorb while keeping the chapter editor and log readable; the maintainer ruled on 2026-09-15 that
**`AQUA_MIN_SIZE = (1024, 800)`, which is also `AQUA_GEOMETRY`, the size the launcher opens at on
macOS**. *This supersedes, for macOS only, the 1024×720 figure in the 2026-09-12 entry below;* the rule
of that entry — the minimum is the platform's, presentation differences live behind the theme bundle as
composition hints the panels read with the Windows values as defaults, and business behaviour never
branches on platform — is unchanged and is exactly how the Phase 13 remediation was built. The Editor's
whole-form scrolling canvas, an accepted v0.6.0 Drop 1 limitation, is gone: only the chapter box and
the log scroll on either tool.

**What deliberately did *not* become a decision record.** The aqua hint token names and values, the
`ADOPTED` / hash-gate guard reconciliation sequence, the ffmetadata escaping fix and the junction fix
(Phase 11), the FFmpeg argument shapes, and the exact test counts are implementation mechanics or
enforcement of rules already approved; they live in `Handoff.md`, `Changelog.md` and the code.

*Approved across the v0.6.4 drop (Windows Phase 12 accepted 2026-09-15, macOS Phase 13 accepted
2026-09-15) and recorded at Phase 14 closeout by Claude Code. Version identity remains `0.6.2`,
unreleased; nothing merged, tagged or published.*

---

## 2026-09-12 — Focused MP3 closeout: the MP3 Tool's approved product contract, and the minimum window is the platform's

**Decision (v0.6.3 focused MP3 redesign, Phase 13 closeout).** The MP3 Tool redesign is complete
and accepted on both platforms, and these are the rules that outlive the temporary focused plan
that carried them. Each was approved during the plan, is implemented, and is protected by tests.
The numbered decisions of the Plan 6 foundation (the Decision Register 1–55 under `don't-delete/`)
are not repeated here; this entry records what the focused continuation added or superseded.

**The MP3 Tool is a multi-Book workspace with exactly two actions.** `Import Folder` makes one
Book per directory that directly contains MP3s; `Add Files` extends the current Book; Book
identity is the stable Plan 6 id, the visible number a position. The actions are **Write ID3
Tags** and **Combine MP3s → One MP3** and no third; the separate Time-edit operation, the FAST
checkbox, the combined-filename prompt and the preserve/remove metadata modes of the old
single-book form are retired for this tool.

**Shared → Book → blank, and blank means blank.** The Shared area is exactly five fields — Artist,
Album Artist, Album, one signed Time, artwork. A populated Shared value overrides and disables the
matching Book field and leaves the Book's stored value intact. Source tags pre-fill a Book's three
scalars once and are never an output fallback: a cleared field writes no frame. A track's own
default Title (source Title, else cleaned filename) is the one source-derived fallback. There is no
Book-level Title; a Book is named by its Album.

**Title, filename and track number are three values.** The output filename is derived **from the
final Title** (`mp3_plan.track_filename`): one existing leading number removed, sanitised through
the shared cross-platform sanitiser, the calculated number added exactly once when Auto-number is
on, at least two digits wide and widening with the Book's last number; a Title that sanitises to
nothing falls back to the source's cleaned name. The embedded Title never carries the prefix; `TRCK`
is an ordinary unpadded integer; Start # blank means 1. *This supersedes the focused plan's §16.2
wording ("take the source-derived basename") — the accepted authority is the Title, as implemented
at Phase 5 and accepted on both platforms.*

**One signed Time.** Positive appends silence to the end of every track, negative trims, zero still
produces clean new copies; Combine applies it to every constituent including the final one.

**Write ID3 writes a whitelist from a clean tag.** `TIT2` always; `TPE1`, `TPE2`, `TALB` when
populated; `TRCK` when Auto-number is on; one front-cover `APIC` when artwork is selected. Nothing
else from the source survives — old artwork included when no artwork is selected.

**Combine is one file per Book, FAST first, Safe automatically.** Books never merge. FAST (a
one-pass concat-demuxer re-encode) is tried when the staged constituents share codec, sample rate
and channel count; otherwise, or when FAST fails, the Safe WAV-normalising path runs and the reason
is emitted as a technical event. The combined tag is Title = effective Album, Artist / Album Artist
/ Album when populated, the artwork, no `TRCK`, no `CHAP`/`CTOC`; `combined_time-stamps.txt` lists
the final Titles at their adjusted offsets. A FAST rejection by FFmpeg on otherwise compatible media
(observed on macOS with FFmpeg 9.0.1) is this contract working, not a defect.

**Artwork is explicit and read-only.** The chooser filter comes from
`shared.image_capabilities.decodable_suffixes()`; JPG/PNG bytes are embedded as-is; HEIC/HEIF are
decoded through the one shared probe into an **in-memory** PNG for the embed only, pixel
dimensions preserved, no sidecar written; the selected file is never resized, cropped or rewritten.

**One run, one controller, atomic Books, frozen retry.** A processing button reserves one
`MP3-Tool-N` run for the whole batch, freezes one `RunPlan`, and runs one `JobController` /
`JobReporter` / `JobAdapter` for every Book in order. A Book publishes whole or not at all
(private `.work/` staging beside its subfolder, which is named Album → source folder → `Book N`
through the shared collision planner); a failed Book does not stop later Books; Cancel leaves
unreached Books *Not attempted* and the batch cancelled (there is no Book-level "cancelled");
Retry Failed re-runs exactly the failed occurrences of the failed Books against the same frozen
plan inside the same run directory, reusing retained staged pieces, and no live edit can reach it.
Staging cleanup unlinks a link as a link and never follows it.

**One log region.** Summary | Detailed, history kept across runs with a divider per run and per
retry, Clear Log clears the visible text only, the persistent session logger continues; no Copy
Log button, no severity selector, no second engine-output pane.

**The minimum window is the platform's.** Windows keeps `MIN_SIZE = (920, 600)` and its accepted
Phase 11 ACT composition. macOS aqua's minimum is `AQUA_MIN_SIZE = (1024, 720)` — the size the
launcher opens at — because native aqua control, font and bezel metrics make the six fixed bands of
this composition (~440 px) taller than the 484 px content host a 920×600 window leaves, before any
list or log height at all; no wrap, weight or padding change closes that, only a Mac-only redesign,
and the maintainer chose the minimum instead after inspecting 1024×720 and larger on the real
launcher. This supersedes the plan's universal 920×600 wording **for macOS only**. Platform
presentation differences live behind the theme bundle: the aqua metrics carry composition hints the
panel reads with the Windows values as defaults, so the Windows layout is untouched by
construction; business behaviour never branches on platform.

**Tests request a presentation through the theme seam, never by falsifying the host.**
`ui_theme.apply_theme(root, style, platform="win32")` selects the Windows bundle on any machine.
A fixture that rewrites `sys.platform` while a panel runs real FFmpeg is a defect — it sent
`shared/subprocess_utils` down the Windows path on macOS — and is not to be reintroduced.

**What deliberately did *not* become a decision record.** The aqua hint token values, the CRLF
canonicalisation of the Phase-0 hash guards, the casefolded-name comparison in the planner test,
the FFmpeg argument shapes and the Phase 10/12 bug fixes are implementation mechanics or enforcement
of rules already approved; they live in `Handoff.md` and the code.

*Approved across the focused MP3 redesign (Windows Phase 11 and macOS Phase 12, both accepted by
2026-09-12) and recorded at closeout by Claude Code.*

---

## 2026-09-05 — Two already-pushed commits keep their AI co-author trailers: a one-time historical exception, not a change of rule

**Status: historical waiver. This entry does NOT supersede, weaken or amend the 2026-07-07 decision
*"No AI co-author trailers in commit messages, ever"*, which remains fully binding for all future
work.** It disposes of two commits that already exist and already violate it.

**The facts, verified mechanically rather than asserted.** Two commits on the pushed branch
`maintenance/0.6.2-setup-self-healing` carry authorship trailers:

| Commit | Subject | Offending trailers |
|---|---|---|
| `592a72b90886a33bf03172fab39409b786af9dc5` | v0.6.2 PRE-PLAN-6 Phase 8: accept macOS self-repair | `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` and `Claude-Session: …` |
| `e916cb1128cb71c6fbe3de10f1d54238d5bfa345` | v0.6.2 PRE-PLAN-6: fix macOS test isolation | `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` and `Claude-Session: …` |

Both were authored on the macOS machine during Phase 8 and the macOS test-isolation checkpoint. The
2026-07-07 rule forbids not only the `Co-Authored-By` line but **trailers of any kind**, so each of
these commits violates it twice. The remaining seventeen commits of the nineteen-commit maintenance
series comply.

**These commits are NOT reclassified as compliant.** They were and remain violations of the standing
policy. Nothing here makes them correct, and nothing here says Claude is an author of anything:
under the 2026-07-07 decision the maintainer is the sole author and sole committer of this
repository, and that is unchanged. What follows is a decision about *what to do now*, not a
re-reading of what happened.

**Decision (maintainer, 2026-09-05): preserve the history. Grant a one-time, closed-set exception
covering exactly the two commits named above, and nothing else.**

**Why.** The only way to remove a trailer from a commit is to rewrite that commit, which rewrites
every descendant SHA. Both commits are already pushed, and both sit in the middle of a nineteen-commit
series that an independent READ-ONLY integration-readiness review has already read end to end at
`a170e41b71168f33247471be79110b871f88cb3d`. Rewriting would invalidate every SHA that review cites,
including the Phase-10 closeout commit recorded across `Handoff.md`, `Changelog.md` and the master
plan index, and would force a force-push over a branch whose contents have been reviewed and found
sound. The maintainer judged the cost of destroying a reviewed, cited history higher than the cost of
recording two historical trailers truthfully and leaving them in place. Honest provenance is the
point of the rule; erasing the evidence to satisfy it would serve the letter and defeat the purpose.

**The exception is deliberately narrow. It:**

- applies **only** to the continued existence of those two already-created commits;
- is a **closed set of two named SHAs** — it cannot be extended by analogy to any other commit;
- **sets no precedent** and grants no discretion to a future session;
- does **not** authorize an AI co-author or session trailer on the remediation commit that carries
  this entry, or on any future commit;
- does **not** authorize any history rewrite, amend, rebase, squash, cherry-pick or force-push — the
  point of the exception is precisely that history is left alone.

**What every future agent must still do.** Write plain commit messages with **no `Co-Authored-By`
line, no session or provenance trailer, and no other authorship trailer of any kind**, exactly as the
2026-07-07 decision requires. If a coding-agent environment appends one automatically, remove it from
the still-unpushed commit before pushing rather than treating this entry as cover. Only the maintainer
may create a new decision that changes this.

— Disposition ruled by the maintainer (Elijah Matthew), recorded by Claude Code, 2026-09-05

---

## 2026-09-05 — PRE-PLAN-6 closeout: observation is not permission, and a launch owns its own readiness

**Decision (v0.6.2 PRE-PLAN-6 maintenance closeout, Phase 10).** `Setup_and_Run` is now responsible
for the state it launches into, on both platforms. These are the durable rules that outlive the
maintenance drop that carried them; that drop is deleted at this closeout.

**This entry supersedes exactly one paragraph of the 2026-08-28 entry below** — *"Why `have_ffmpeg()`
did not simply become 'verified'"*, which recorded that `have_ffmpeg()` means only *a coherent pair is
available* and that the strong claim lives separately in `verified_ffmpeg()`. That compromise existed
so a machine which had never run setup could still use the tools. A launch now repairs and proves
instead, so the weaker meaning has no remaining purpose — and the split it created was a trap, because
the weak name is the one every consumer gate in the app was written against.

**Everything else in the 2026-08-28 entry stands and is not reopened:** ffmpeg and ffprobe are one
coherent sibling pair; a candidate must actually be executed to count; the winning pair is pinned
**where it lives** and is never copied into `files/bin/` merely to centralise it; a package-manager or
system installation stays owned by the manager that installed it; identity is path + size + mtime with
SHA-256 kept as durable evidence rather than as a per-launch check; rejected and blocked candidates are
remembered and not executed again; and path existence or resolvability is never readiness. That entry's
security boundary is untouched — nothing here weakens, disables or routes around Smart App Control,
Defender, WDAC or any endpoint policy.

### Observation is not permission

1. **`shared/ffmpeg_health.py` remains the sole health and proof authority.** Nothing else decides
   whether FFmpeg is usable.
2. **Discovery is observational only.** `discovered_ffmpeg()` may report that a coherent pair *appears*
   to exist. It enumerates, executes nothing, and never authorises execution — so drawing a status line
   cannot raise the Windows Security prompt that executing a blocked binary raises.
3. **`have_ffmpeg()` now carries the same strong meaning as `verified_ffmpeg()`:** a proved, durably
   pinned, still-matching coherent ffmpeg + ffprobe pair is active. A gate written against either name
   is therefore safe. The older, weaker question moved to `discovered_ffmpeg()`, under a name that
   cannot be mistaken for permission.
4. **`ffmpeg_path()` / `ffprobe_path()` return only the pinned pair**, or `None`.
5. **`ffmpeg_cmd()` / `ffprobe_cmd()` return only absolute paths** to that one accepted sibling pair.
6. **There is no bare `"ffmpeg"` / `"ffprobe"` fallback anywhere.** When no accepted pair exists the
   command APIs raise `FFmpegUnavailable`. A refusal the caller can see beats a command line that
   quietly runs whatever `PATH` offers, with two halves that need not even be the same installation.
7. **pydub is explicitly configured to the accepted absolute pair.** Left unconfigured it shells out to
   the bare names, which was the one audio route no consumer gate sat in front of. With nothing pinned
   it is pointed at a sentinel directory path that no process API will execute, so an operation that
   slips past a gate fails immediately and visibly instead of quietly running something unproved.
8. **A normal launch owns readiness: ASSESS → REPAIR → PROVE → PIN → LAUNCH.**
9. **An installer's exit status is never readiness.** WinGet and Homebrew can return 0 and leave nothing
   usable, so the resulting pair is always proved independently before it is pinned.
10. **A healthy installation does the minimum.** A launch that finds everything already proved is a
    no-op, not a reinstall.

### The setup / bootstrap self-healing contract

**Venv health.** The existence of `.venv` is not health, and treating it as health is the defect this
maintenance existed to remove. A normal launch assesses interpreter liveness, a supported Python,
`ssl`, Tk when the GUI needs it, requirements state, and an import proof. The full-feature Python
contract is **`>=3.11,<3.13`**, expressed in exactly one place; the preference order is **3.12, then a
healthy 3.11**; and **3.13+ is not a fully healthy full-feature setup** under the current pins. No
unrelated interpreter is uninstalled or modified.

**Requirements success cannot be claimed before it is proved.** A requirements success stamp is written
only after reconciliation or install succeeds **and** the required imports actually succeed — pip
exiting 0 proves nothing, since a partial wheel, an ABI mismatch or a clobbered install all exit 0. The
real-import proof is recorded separately and is bounded, so a rebuilt environment cannot inherit an
older one. **A false success stamp is forbidden**, because nothing re-probes afterwards.

**Venv recovery is transactional.** Replacing a broken environment sets the old one aside rather than
destroying it; an interrupted repair preserves or restores the last-known-good state, and an existing
aside is never overwritten. **No normal recovery requires the user to delete `.venv` by hand.**

**Windows package acquisition — user scope, explicitly.** Every production `winget install` names
**`--scope user`**: the Python install, the `Gyan.FFmpeg` install, and the root `.bat`'s Python
fallback. **Nothing requests machine scope, and there is no `runas` or elevation fallback.** Scope is
stated rather than inherited from a package default that can change underneath us. A scope or elevation
refusal is not an error to report — it means *this route is unavailable*, and the caller falls through
to the repo-local portable build. That portable fallback stays pinned to the approved **Gyan 9.0.1**
artifact by exact URL **and** exact SHA-256, verified before extraction, staged, proved in staging, and
promoted by a single same-volume rename into a versioned destination before it can ever be active.

**macOS acquisition.** A normal launch with an existing venv can reach the Homebrew FFmpeg repair, and
the application may call `brew install ffmpeg` when Homebrew is present. **It does not install Homebrew
itself** — it points at `https://brew.sh` and says what that would enable. Homebrew reporting success is
not readiness: the resulting pair is still proved and pinned like any other.

**Failure UX.** A repairable prerequisite failure must not trap the user in a blocking pre-GUI "run it
again" loop, which is advice to repeat an identical non-repairing action. Attempt the repair first,
launch where that is safe, and give at most one truthful limited-mode notice when a capability genuinely
cannot be established.

**Test isolation is part of the contract.** Automated tests must not mutate the real `.venv`
requirements or import state, the production `ffmpeg-state.json`, production `files/bin`, production
setup logs, or package-manager state. Two issues found while accepting macOS were **test-harness
defects, not production defects**: a repair sandbox that could reach the host's real Homebrew, because
production deliberately restores the brew directories to `PATH` and candidate discovery searches `PATH`
before the seam the fixture controlled; and a cross-platform recovery test that seeded a Windows
`Scripts/` venv layout. Both were fixed in the harness, leaving production behaviour and candidate
ordering untouched.

### Accepted real-machine evidence, and one named waiver

**HOME-PC (Windows).** A healthy existing `.venv`, with FFmpeg missing. The first ordinary Explorer
double-click **repaired itself** with no manual intervention, through the user-scope WinGet
`Gyan.FFmpeg` route; the resulting pair was independently proved and pinned, and the GUI launched. A
second launch was healthy, with no repair loop. `.venv` was preserved throughout and never deleted by
hand.

**HOME-MacOS.** A healthy existing `.venv`, with FFmpeg genuinely absent. The first ordinary Finder
`.command` double-click repaired through Homebrew; the resulting pair was proved and pinned, and the GUI
launched. A second launch was healthy with no repair loop, and `.venv` was preserved. The specific
Homebrew and GPAC build numbers present on that machine are incidental evidence, **not** architectural
requirements.

**Phase 9 — CSPW-PC non-admin validation: WAIVED / NOT APPLICABLE.** The maintainer decided that CSPW-PC
is no longer a deployment target, so this was **not tested and did not pass**, and **no HOME-PC
substitute evidence was used or claimed** — HOME-PC's account is an Administrator, so a run there
exercises the elevated path and cannot demonstrate the Standard-User restriction. Automated coverage
proves the explicit user-scope argv and the fallback route, including an AST inventory that stops a new
call site from omitting the scope; **that is not a substitute for a real Standard-User target-machine
acceptance**, which remains unperformed. **If a non-admin Windows deployment target is ever
reintroduced, that validation must be reinstated and actually run.** A waiver stays a waiver.

*Recorded 2026-09-05 by Claude Code, at the maintainer's direction, during the PRE-PLAN-6 Phase-10
maintenance closeout. Version identity remains 0.6.2, UNRELEASED.*

---

## 2026-09-01 — D4 clarified: Strip writes no split-fragment metadata at all

**Decision (post-closeout documentation remediation).** The split-fragment metadata rule recorded as
**D4** in the 2026-08-31 closeout entry below is **incomplete as written**, and this entry supersedes
that wording. D4 says a fragment "inherits only `artist`, `album_artist` and `album`; it regenerates
its own `title` and its structural `track`". That is true of **Preserve** and **Replace** only.

**The complete rule, in both directions:**

- **Split — Preserve / Replace:** the fragment inherits the book-level identity and **regenerates a
  generated structural title and track**, which always win over any book-level title a Replace run
  supplies.
- **Split — Strip / Write none:** **no metadata is written at all.** Nothing is regenerated — not a
  title, not a track number, not an inherited field. Strip is not "the other two minus the inherited
  fields"; it is empty by design, and reading D4's regeneration clause as universal would describe a
  behaviour the tool does not have.

**Why this is a documentation correction and nothing more.** The production invariant is already
embodied by `mp3_tools/m4b_metadata.segment_tags()`, whose Strip branch returns an empty mapping
before any inheritance or regeneration is considered, and it is covered by the existing Plan-5
tests. **No behaviour changed, no code changed, and no approved product decision was reopened** —
D4's substance stands exactly as approved; only its statement here was too narrow. The 2026-08-31
entry below is left intact as written, per this log's append-only rule.

*Recorded 2026-09-01 by Claude Code, during the bounded post-closeout documentation remediation.*

---

## 2026-08-31 — Plan 5 closeout: the M4B Converter's approved product contract

**Decision (v0.6.2 Plan 5, Phase 18 closeout).** The Converter upgrade is complete, and these are
the product rules that outlive the implementation drop. They are recorded here because the drop that
carried them is deleted at this closeout; each was approved during the plan and is implemented.

**One entry, not six, and deliberately so.** The split-placement decision already has its own entry
(2026-08-30), as do the Windows xHE-AAC routing decision, the whole-book cover-from-a-second-input
finding and the FFmpeg-pair pinning rule (2026-08-28/29). Those are not repeated. What follows is the
remainder, which is a single coherent contract rather than six independent architectural choices.

**Layout (D1).** The Converter keeps `MIN_SIZE == (920, 600)`, the `1024x720` default and its
classic, non-`ACT.*` visual identity. Plan 5 added its controls within that window rather than
redesigning the panel; broad visual conversion stays Plan 9's. The sanctioned local scrolling
fallback was **never needed** — every Plan-5 control is a real target at the supported minimum.

**Artwork (D2).** Preserve and Replace keep the source cover; Strip removes it. Only a stream
positively identified by `disposition.attached_pic` is copied, by absolute stream index, so ordinary
video ahead of a cover can never be mistaken for one. A source with no artwork is valid. Two attached
pictures is an ambiguity and **fails closed** rather than guessing. Covers are stream-copied, never
re-encoded, and Plan 5 ships **no** replacement-image picker — that is Plan 8's.

**Split-fragment metadata (D4).** A fragment is not the book. It inherits only `artist`,
`album_artist` and `album`; it regenerates its own `title` and its structural `track`; and it never
carries the whole book's chapter map or title. The regenerated pair always wins, so a Replace run's
book title cannot become a chapter's title.

**Numbering (D5).** Three concepts that never mix: a split output's **structural** track is its
position within its own book and restarts per book; a whole book's **sequential** track is optional,
allocated **only on success** so a failure consumes nothing and the sequence stays gap-free, and it
is derived from the run's own result rather than from any filename or directory listing; and the
filename order prefix is rendered, never allocated. The whole-book option defaults **off** — numbering
a library is something a user asks for, not something a default does on the way past.

**Whole-book chapter retention (D6A).** A whole output *is* the whole book, so Preserve **and**
Replace both keep the source chapter map — replacing a book's text does not invalidate its
navigation. Strip removes it with everything else. Retention means the titles as well as the
boundaries: a map of anonymous timing points is not the map the source had.

**Shared recursion (D7A).** `ImportOptions.include_subfolders` is a shared importing field, default
`True`, honoured at the single existing descent point, and frozen per import so toggling it changes
only the next import. It was extended in shared code rather than forked into the Converter.

**The metadata vocabulary did not grow.** `title`, `artist`, `album_artist`, `album` and an optional
`track` — the same set `shared/metadata.py` already supported. Everything reaching an output is named
explicitly; nothing is inherited because ffmpeg could inherit it.

**What deliberately did *not* become a decision record.** ffmpeg argument shapes, the ID3 version
pin, the worker's exception boundary, the frozen-reservation correction and the Phase-17 bug fixes
are implementation mechanics or enforcement of rules already approved — the plan's own closeout
instruction forbids standalone ADRs for them, and they live in `Handoff.md` instead.

*Approved across Plan 5 and recorded at closeout by Claude Code.*

---

## 2026-08-30 — A split run groups every book in its own folder; whole books stay flat

**Decision (v0.6.2 Plan 5, Phase 16; maintainer disposition after real macOS multi-book validation).
This supersedes the *split* half of D3 / Decision 31A. The whole-book half is unchanged and stays
exactly as approved.**

A **split** occurrence now gets **one container directory named for its source filename's stem**, at
the place its own provenance already puts it, and all of that occurrence's segments go inside it.
`Arazan's Wolves.m4b` becomes `Arazan's Wolves/` — only the final extension is removed before the
shared sanitiser sees the name. A **whole-book** output is untouched: directly selected books stay
flat in the run folder, folder-imported books still mirror, and no per-book container is ever
invented for them.

**Why, and it took a real corpus to see it.** 31A was a reasonable rule and the implementation
followed it literally. Then Phase 16 ran **12 real audiobooks through Split in one run**: 353 chapter
MP3s landed flat in a single folder, interleaved by book — `01 - Arazan's Wolves-Part01.mp3` next to
`01 - Opening Credits.mp3` next to `02 - Prologue.mp3` — and **53 of the 353 carried a collision
suffix** for no reason except that different books name their chapters alike. Collision-safe planning
was working perfectly; the *organisation* was the problem, and it is only visible at corpus scale.
The maintainer judged the result unusable and superseded the rule. **The previous behaviour was not a
defect and is not recorded as one.**

**The folder is the source stem, never the metadata title.** A Replace run rewrites the book's
textual metadata, and naming the folder from that would rename it out from under the user
mid-decision. The filename is the identity people already recognise.

**One authority, not two.** The container is planned through the *same* three shared planners the
outputs themselves use, with the stem standing in for a filename: `plan_flat` for a directly chosen
book, `plan_mirrored` under its mirrored parent, `plan_multi_root` inside its root container. So
provenance, `assert_contained`, `assert_not_input` and the single run-wide collision domain are all
still decided in one place, and no shared contract changed — `DestinationPlanner.plan` already
accepted a sanitised `subdir`.

**Reserved once per occurrence, deliberately.** Two occurrences that would take the same folder are
separated at the *folder* level (`Book`, `Book-1`), and every segment of one book then shares that
one container. Numbering each segment's parent independently would scatter a single book across
several folders — the failure this ordering exists to prevent. Two deliberate duplicates of one file
remain two occurrences with two containers. A failed split book **keeps** its reservation rather than
releasing it, so Retry Failed writes to the identical frozen paths.

**A chapterless source in a split run keeps its folder too** — one output, but it belongs with the
books beside it rather than loose at the run root.

One incidental improvement, measured: because each book now owns its folder, the cross-book chapter
name collisions disappear. The suffixes that 53 of those 353 files carried are simply not generated.

*Maintainer disposition 2026-08-30; implemented and recorded by Claude Code.*

---

## 2026-08-29 — Phase 15 closes on maintainer acceptance, with the untested rows recorded as waived

**Decision (v0.6.2 Plan 5, Phase 15; maintainer disposition, and it overrides the plan's own §26
completion requirement for this phase only).**

Phase 15 Windows validation is **COMPLETE BY EXPLICIT MAINTAINER ACCEPTANCE**. The maintainer
accepted the real-world Windows validation already performed and explicitly waived the remaining
unperformed synthetic/manual §26 rows as prerequisites: *"I'm not going to test all of that since it
would take too long and i don't have time … i tested enough with the other files and I am happy with
how it's performing, if in the future i encounter an error i will come back to the chat and we can
work on it but for now let's move on."*

**The waived rows are recorded as waived, never as passed.** They are enumerated in `Handoff.md` and
summarised in the plan's §26, under the wording *not manually exercised; explicitly waived by
maintainer on 2026-08-29; non-blocking for Phase-15 completion*. Nothing may reclassify them as PASS
on the grounds that the implementation exists, that automated tests cover the behaviour, that
synthetic fixtures were prepared for them, or that the product is performing well. "Phase 15
complete" does not mean "all of §26 passed", and any future summary that says so is wrong.

**Why this is a legitimate close rather than a shortcut.** What was validated is the part that
carries the risk, and it was validated on real 9-to-13-hour audiobooks through the real launcher
rather than on fixtures: FFmpeg provisioning and clean-install acceptance; AAC-LC Whole; the Windows
Media Foundation xHE-AAC route Whole at 100.0004 % and Split at 15/15; a human listen across a split
boundary; the cp1252 Unicode regression with all three Whole metadata modes; Pause, Resume and
Cancel with verified cleanup; and source immutability by hash on three real books. Four genuine
Windows blockers were found and fixed along the way — FFmpeg provisioning, whole-book artwork
truncation, the xHE-AAC decode gap, and the ffprobe code-page refusal — which is the real return
this phase produced. The waived rows are breadth over synthetic fixtures, and the maintainer judged
that breadth not worth further time. That is their call to make, and the honest record of it is this
entry rather than a matrix quietly filled in.

**One row could not have been tested anyway.** *First chapter starting after zero* is not
representable as a valid M4B here: ffmpeg's MOV/M4B muxer normalises the first chapter start to `0`
(verified against the default, `+disable_chpl` and `-disable_chpl`; the same metadata keeps
`2.000000` in Matroska), and all five real books on hand also begin at `0.000000`. No invalid file
was fabricated to satisfy the row. `test_m4b_timeline_partition.py` covers the planner behaviour it
was meant to exercise.

**What this does not close.** The true no-Python + no-FFmpeg fresh-machine proof stays outstanding
as a *release* gate, not a Phase-15 one. The waived rows may be revisited if a real defect appears,
or folded into the Phase 17 bug hunt. Plan 5 stays ACTIVE, Phase 16 is not started, `VERSION`
remains `0.6.1`, and nothing was tagged, released, packaged or merged.

*Maintainer disposition 2026-08-29; recorded by Claude Code.*

---

## 2026-08-29 — Project work lives in the repository; external workspaces need permission

**Decision (repository-wide standing policy, maintainer-directed; not tied to one plan or phase).**

All project-related work created while working inside this repository stays **inside** it —
scratch files, synthetic fixtures, diagnostics, backups, clean-room environments, generated test
media, temporary evidence, logs and agent working directories. The repo-local home is
**`files/dev-work/`**, gitignored in full and organised by phase or purpose. Creating a project
workspace elsewhere on the machine — `C:\act-*`, a Desktop scratch tree, an arbitrary
`%TEMP%` project folder — is not permitted for convenience.

External paths remain legitimate only where the operating system or the thing under test requires
them: installed Python and FFmpeg, WinGet and other system package locations, OS-managed caches
and temp directories the dependencies create themselves at runtime, and the user-selected
application output location. A test whose purpose *is* to prove out-of-repository behaviour is an
exception — and before creating such a workspace the agent must **stop and ask**, stating why
`files/` cannot serve, the exact path proposed, what will be created, and the cleanup plan.

Committable content is application source, tests, required scripts, documentation, and fixtures
deliberately meant to survive a `git pull` on another machine. Everything local-only stays
ignored. Sitting inside the repository does not make temporary evidence GitHub content: no broad
`git add files/`, no force-add of ignored material, and no promotion into `files/test-files/`
merely because something now lives in-tree.

**Why.** By Phase 15 the project had scattered roughly **5 GB** across five `C:\act-phase15-*`
folders and eleven `%TEMP%\act-*` directories — a clean-room checkout with its own `.venv`, an
inactive FFmpeg backup, two diagnostic sets, a synthetic fixture workspace and a registered git
worktree. None of it was discoverable from the repository, none was covered by `.gitignore`, and
a fresh clone gave no hint that any of it existed. Keeping the material in-tree and ignored makes
it visible to whoever is working, disposable in one delete, and impossible to commit by accident,
while the checkout stays usable as the project's clean development and release source.

**Consequence, accepted knowingly.** The relocated clean-room carries a second copy of
`files/tests/`, so a bare `pytest` invoked from the repository root now hits 164 basename
collisions. The authoritative gate is unaffected and was re-measured: `scripts/verify.py` runs
`pytest files/tests/` explicitly and still collects **5160**. Use `python scripts/verify.py` (or
`pytest files/tests`), not bare `pytest`.

*Resolved 2026-08-29 by the follow-up checkpoint, and the rule it establishes belongs with this
one: repository-contained is not the same as active project source, so a local workspace is
excluded from test and source discovery as well as from Git.* A tracked root `pytest.ini` pins
`testpaths = files/tests` and adds `dev-work` and `runtime-data` to `norecursedirs`. Bare
`pytest` now collects the same tree as `verify.py`. The sweep also found the defect was never
unique to `dev-work`: `files/runtime-data/phase14/tree-phase12/` has carried a second copy of
`files/tests/` since 2026-08-22, so `pytest .` was already broken before the migration.

**Historical evidence keeps its original paths.** Reports that say evidence was collected at
`C:\act-phase15-xhe-diag` remain true as written; `Handoff.md` carries the current location map.
Relocation does not invalidate the evidence.

*Maintainer-directed, 2026-08-29; recorded by Claude Code.*

---

## 2026-08-29 — ffprobe's JSON is read as bytes; the host code page never decodes it

**Decision (v0.6.2 Plan 5, Phase 15 blocker remediation; narrow, one production line).**

`m4b_probe.probe_source` asks `check_output` for **bytes** and hands them to `json.loads`, which
decodes JSON's own way (UTF-8/16/32, per RFC 4627). It never asks for `text=True`, an `encoding=`
or an `errors=` mode. A payload that is not valid JSON — or not valid UTF-8 — still fails closed
through the existing typed `ProbeStatus.PROBE_FAILED`, unrepaired.

**Why.** A maintainer imported the real `ToA 4 - The Tyrant's Tomb.m4b` and the Converter refused
it: *`probe status probe_failed: UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d in
position 6528`*. The book is an ordinary valid AAC-LC audiobook — 48,123.24 s, 44 chapters, one
PNG cover, five readable tags — and ffprobe read it perfectly: **exit 0, empty stderr, 22,545
bytes of valid UTF-8 that `json.loads` parses straight from bytes**. The failure was ours.
`text=True` with no encoding makes Python decode with `locale.getpreferredencoding(False)`, which
is **cp1252** on a stock English Windows install. Byte 6528 is the third byte of
`b"\xe2\x80\x9d"` — U+201D RIGHT DOUBLE QUOTATION MARK — inside chapter 4's title *A simple “no”
works*. The typed failure was truthful about what it saw; what it saw was a defect one layer up.

**Crashing was the loud half.** cp1252 *maps* most of the bytes it should not touch: U+2014
arrives as `â€”`, U+2019 as `â€™`, U+00E9 as `Ã©`. A book whose titles avoided the handful of
unmapped bytes would have converted successfully with mojibake baked into every chapter name and
tag. So the fix is measured by exact round-trip, not by the absence of an exception — which is
also why `errors="ignore"` and `errors="replace"` are rejected outright: both turn a refusal into
a silent corruption of the user's chapter titles.

**Why not decode UTF-8 explicitly.** It would work — ffprobe does emit UTF-8 — but it makes this
module a second authority on an encoding `json` already determines correctly, including the
BOM/UTF-16 cases. `shared.metadata.read_chapter_titles` has passed ffprobe's bytes straight to
`json.loads` since it was written; the Converter's probe was the one place that did not, and this
makes them agree rather than inventing a third way.

**Scope, decided on evidence rather than tidiness.** The sweep found one other locale-decoded
ffprobe call reachable from the Converter: `ffmpeg_utils.probe_audio_stream`, used by
`measured_duration` for the drift guard. It is **not** the same contract — `-of
default=noprint_wrappers=1` over six fixed entries — and its output on the very book that broke
the probe is **pure ASCII** (`codec_name/profile/sample_rate/channels/channel_layout/duration`),
which cannot carry a title or a tag. It was left alone. `-decoders` likewise. Nothing in TTS,
Cover, the M4B Maker or the Metadata Editor was touched.

**Why the suite was green while a real audiobook was being refused.** Every generated probe
fixture titles its chapters `Ch One`. A pure-ASCII book cannot fail this way. The regression now
builds a book whose titles carry the same characters, and asserts the payload really is
cp1252-undecodable so the guard cannot quietly stop guarding.

— Diagnosed and implemented by Claude Code from the maintainer's real-book report, 2026-08-29

---

## 2026-08-29 — Windows decodes xHE-AAC through Media Foundation; ordinary AAC stays on ffmpeg

**Decision (v0.6.2 Plan 5, Phase 15 blocker remediation; maintainer-approved, no new dependency).**

A source the probe marks `undecodable_xhe` has its audio decoded by **Windows Media Foundation**
and piped into the unchanged MP3 encode. Everything else — all 54 AAC-LC books in the real
corpus — keeps the existing ffmpeg path untouched. Where Windows cannot decode it either, the run
**fails closed at preflight** rather than producing a shortened audiobook.

**Why ffmpeg is not enough today.** Measured against the real 9.78-hour xHE-AAC book: ffmpeg 9.0.1
refuses **362,465 of 1,515,928 frames** with *"Not yet implemented in FFmpeg, patches welcome"* —
**23.91 %** of the audio — concatenates the rest into 26,783 s against a planned 35,200 s, and
**exits 0**. Split is no better: every chapter span comes back at ~76 %. The audio is not merely
short, it carries ~362,000 excisions. Only the drift guard stopped it shipping. Upstream added the
USAC frequency-domain path in FFmpeg 8.0 and still returns *patches welcome* for eSBR, uniDrc and
time-warped MDCT; since 23.91 % of frames fail rather than all of them, the gap is a **per-frame**
tool. Naming it exactly needs an instrumented build and does not change this decision.

**Why Media Foundation and not FDK-AAC.** FDK v2 does decode xHE-AAC. But `--enable-libfdk-aac`
requires `--enable-nonfree`, which combined with `--gpl` yields a binary that **may not be
redistributed**; this project is GPL-3.0, and no reputable pre-built ffmpeg ships it. Windows 11's
decoder is already installed, needs no download, raises no Smart App Control question, and is
driven from `ctypes` — **stdlib**. It delivered **35,199.78 s of that book: 100.0004 %**.

**Why `IMFSourceReader` and not `MediaTranscoder`.** MediaTranscoder also decodes this book
correctly, but only into a file, and the decoded book is **6.2 GB**. Chunking it was measured and
rejected: `[600,1200)` yields 26,452,025 frames while `[600,900) + [900,1200)` yields 26,443,970 —
every seek discards **8,055 frames (0.183 s)** to decoder priming. The reader is a *pull* interface:
strictly sequential, so nothing is primed away, handing back **4 KB** at a time so the 6.2 GB flows
through a pipe and is never stored.

**Why a split book decodes once.** Because seeking is lossy, `PcmTimeline` runs the decoder once
per item and cuts the PCM at frozen chapter boundaries in the order the segments already run in.
Measured on the real book: opening, early, middle and **final tail** spans all at **100.00 %**.
A short read is reported, never padded — silence in place of missing audio would defeat the guard.

**Capability is probed, never inferred from a version.** Windows N/KN editions ship without the
media feature pack and components can be removed by policy, so the question asked is whether the
libraries load and `MFStartup` succeeds.

**What did not change.** The >3 % drift guard, the encoder, the quality, the metadata allowlist,
ID3v2.3, destinations, numbering, retry, cancellation, and macOS — which keeps `aac_at`, and
therefore reports such sources *decodable* and never reaches this path at all.

**One bug this decision cost, recorded so it is not repeated.** The first live run produced a
complete 100.0004 % audiobook with **zero chapters**: `pcm_argv` emitted `-map_chapters 1` and the
shared `output_args` emitted `-map_chapters 0`, and argument order settled it in favour of the PCM
pipe, which has no chapters. The chapter map is now owned by exactly one place on this route.

— Claude Code, at the maintainer's direction

---

## 2026-08-28 — A whole book with a cover opens its source twice, and the picture comes from input 1

**Decision (v0.6.2 Plan 5, Phase 15 blocker remediation).**

When a Whole output retains artwork, the command opens the same audiobook **twice**: input 0 is
decoded for audio and supplies the chapter map, input 1 exists solely so the attached picture can be
stream-copied out of it.

```
ffmpeg … -i BOOK.m4b -i BOOK.m4b -map 0:a:0 -map 1:<abs index> -c:v copy
         -disposition:v:0 attached_pic … -map_chapters 0 … -c:a libmp3lame …
```

**Why, and it is not obvious.** Mapping the cover out of the *same* input whose audio is being
decoded makes ffmpeg **exit 0** after encoding a handful of audio frames. The artifact that started
this was a 600 KB "audiobook" holding **0.32 seconds** of a 13.5-hour book, alongside its cover,
reported as success. A controlled matrix on the real source isolated it exactly: audio alone passed,
audio **plus chapters** passed, and only the same-input picture truncated — so the chapter map, the
obvious suspect, was innocent. Cover size is irrelevant; a 247-byte cover truncates like a 597 KB
one. The trigger is **source length**: everything up to 50 minutes is fine, 55 minutes and beyond
always truncates. Opening the file a second time for the cover alone fixes it, proven on the full
book — 743 MB, duration exact, all 50 chapters, cover intact, audio encoded once.

**Why not two passes.** Split already attaches artwork in a second stream-copy pass, and copying that
shape here would also have worked. It was rejected: for a book this size it means writing ~750 MB
twice for no benefit the one-command form does not already give. A Whole book remains **one ffmpeg
invocation and one audio encode**, which is what the plan always said it was.

**What this is explicitly not.** It is **not** recorded as an ffmpeg 9.0.1 regression. No evidence
establishes when the behaviour began: every previous Whole output on this machine is a 0-byte
placeholder, and the automated suite's real-media Whole+cover test is six seconds long — two orders
of magnitude below the boundary — so it would have passed against the defect at any version. The
coverage gap alone explains why this survived to a manual matrix. A `~60`-minute generated fixture
now closes it, and it was verified to fail against the pre-fix shape before being trusted.

**Do not simplify the second input away.** `m4b_commands._core` and `_media_args` carry the reasoning,
and five separate guards — in `test_m4b_commands`, `test_m4b_metadata`, `test_m4b_execution` and
`test_m4b_conversion_plan` — pin `1:<index>` and refuse `0:<index>`.

— Claude Code, at the maintainer's direction

---

## 2026-08-28 — The proven FFmpeg pair is *pinned where it lives*, never copied into `files/bin/`

**Decision (v0.6.2 Plan 5, Phase 15 blocker remediation; maintainer cleared risk gate #9 for this
bounded shared change).**

FFmpeg capability now exists only through **one coherent ffmpeg + ffprobe pair that setup or repair
has actually executed**. `shared/ffmpeg_health.py` discovers candidate pairs, proves them by running
`-version` on both halves, and records the winner — **by absolute path** — in
`files/runtime-data/ffmpeg-state.json`. `shared/ffmpeg_utils.py` consumes that record. The pair is
**not** copied into `files/bin/`.

**Why a pinned external pair rather than a normalized local copy.** Copying was the obvious
alternative and it loses on every axis that matters here. The proven Windows build is a 222 MB
static ffmpeg plus a 222 MB static ffprobe, so a copy costs ~444 MB of duplicated bytes for no new
capability. A copy also goes **stale silently**: `files/bin` is checked first, so a copy left behind
by a `winget upgrade` would become an unbeatable candidate — which is a rebuild of the exact defect
this phase removed, where a bad candidate won because it happened to be looked at first. And
copying a GPL third-party binary into the repository tree edges toward redistribution, which is
Plan 9's question, not this phase's. Pinning keeps **one** source of truth, keeps the installation
owned by the package manager that installed it, and makes an upgrade *detectable* — the recorded
size/mtime stop matching, the pin is invalidated, and the pair is re-proven.

**Why identity is path + size + mtime, with SHA-256 as evidence rather than as the check.** Hashing
444 MB on every launch is a visible cost for no extra safety against accidental change. The hash is
computed once at proof time and kept as durable evidence, and re-derived on repair.

**What identity deliberately cannot see, and what covers it.** Nothing about the bytes changes when
a *policy* changes: a pair that ran yesterday and is refused today is byte-identical. So
`ensure_ready()` re-proves the **pinned pair only** on every launch — two bounded `-version` calls,
~60 ms measured — and never sweeps PATH. That distinction is load-bearing: **executing a blocked
binary is itself what raises the Windows Security notification**, so probing strangers on a normal
launch would manufacture the very popup this phase exists to remove. Candidates already proven
unusable are recorded and skipped without being executed again.

**Why `have_ffmpeg()` did not simply become "verified".** It now means *a coherent pair is
available* — still not a claim that either half runs — because a machine that has never run setup
must still be able to use the tools rather than be told it has no FFmpeg at all. The strong claim
lives in the new `verified_ffmpeg()`, and `status_line()` is the single place the difference is
worded, so "found" can never again be printed as "detected" and read as "ready".

**Security boundary, explicitly.** Nothing here disables, weakens, excludes from, or works around
Smart App Control, Defender, WDAC or any endpoint policy, and nothing suppresses a Windows
notification while still using a blocked binary. When no candidate runs, the app says so at the
setup/repair boundary and points at an administrator allowlisting FFmpeg. An organisation's policy
that refuses every legitimate build is a limit the application accepts, not one it routes around.
Getting an unsigned FFmpeg trusted by reputation or signature is release work and stays in Plan 9.

— Claude Code, at the maintainer's direction

---

## 2026-08-22 — Plan 4 closeout: EPUB is retired and archived, Decision 52B is partially superseded, and the licence obligation survives in production

**Decision (v0.6.1 Plan 4, Phase 5, ratified at the Phase 15 closeout).**

**1. EPUB is not a supported input. PDF and TXT are the only ones.** This **partially supersedes
Decision 52B**, which read *"TTS folder batch remains PDF/TXT only; EPUB remains single-file
only."* The folder-batch half stands unchanged; **the single-file EPUB half is withdrawn.** There
is no EPUB mode, no conversion option, no `.epub` dialog filter, and no internal route — stale
persisted state, a retry and a direct internal dispatch call are all refused exactly as the UI is,
proven by 101 AST- and metadata-driven guards rather than by review.

**Why:** EPUB was the least-used and most brittle input, and it was the only one dragging three
parsing dependencies (`ebooklib`, `beautifulsoup4`, `lxml`) into every install. Keeping a
half-supported path alive through the Plan 4 panel restructure would have meant maintaining and
re-testing a mode nobody had asked for.

**2. The source is archived, not deleted, and the archive is permanent.**
`files/archived-code/epub-tts/` holds three extracted source files plus a `README.md` manifest
giving, per file, the original path, purpose, source SHA, retirement reason, retained production
counterpart, licence and restoration guidance. Every byte came from `git show`, never from a
working directory. **It is not a temporary drop and is never deleted with one.** Its inertness is
proved, not asserted: outside `scripts/`, imported and named by nothing in production, uncollectable
as tests, no `__init__.py` / `conftest.py` / `setup.py` / `pyproject.toml` / `sitecustomize`, no
top-level `if` and no top-level call in any archived module, and unreachable by `release.py`, which
walks `ROOT_FILES` + one launcher + `scripts/` only.

**Why:** deleting working GPL-3.0 upstream-derived code to save four files is a false economy. An
archive that cannot be imported, collected or packaged costs nothing and makes restoration a
mechanical act rather than an archaeology exercise.

**3. The module names `epub2tts_edge` and `epub2tts_gui` are deliberately kept.** They are **not**
evidence of EPUB support. Renaming would have had to move atomically across the launcher module
path, `bootstrap.LAUNCHER_FALLBACK`, `tts/__init__.py`, nine test modules holding those paths as
literal strings, `files/Dockerfile` and `README.md` — while Phases 6 and 7 restructured that same
panel. The boundary is written down in three places instead (the panel docstring, the README
`scripts/tts` bullet, and a dedicated manifest section), and a guard asserts the manifest says so.

**Why:** the names carry the upstream provenance, and a half-completed rename during a
simultaneous restructure is exactly the failure the drop warned about. This is disclosure, not
avoidance.

**4. The GPL-3.0 licence and the upstream attribution are obligations of *production*, not of the
archive.** The surviving Edge PDF/TXT engine is the same derivation of
[epub2tts-edge](https://github.com/aedocw/epub2tts-edge) by **Christopher Aedo**, so the README
License section and the credit stay byte-identical and are now pinned by tests, and
`generate_metadata` still writes the upstream URL into every M4B. One line was removed — `ebooklib`
left the "gratefully relying on" list — because that is a dependency acknowledgement, not the
protected attribution, and the project genuinely no longer relies on it.

**Why:** retiring a feature does not retire a licence. Anyone reading the shipped product must
still be told what it derives from.

— Ruled by the maintainer for Plan 4 (superseding the EPUB half of Decision 52B); implemented at
Phase 5 and recorded by Claude Code at the Phase 15 closeout on 2026-08-22.

---

## 2026-08-22 — TTS has one unified PDF/TXT queue; direct files and folders are not two modes

**Decision (v0.6.1 Plan 4, decisions 1A and 2A, ratified at the Phase 15 closeout).**

**Direct files and whole folders coexist in one queue and one run.** There is no Single-File mode,
no Batch-Folder mode and no mode switch. One run preserves occurrence identity, deliberate
duplicates, provenance and natural ordering; **folder-derived items are mirrored** into the output
tree so same-named files from different books cannot collide, and **direct files are placed flat**.
The frozen snapshot captured at run start is what a Retry Failed re-runs, so a retry reproduces the
exact original configuration rather than today's UI state.

**Why:** the two old modes differed in almost nothing except which widget the user had touched
last, and every difference between them was a place for placement rules to diverge. Collapsing
them removed a whole class of "which mode was I in" bugs, and it is what let TTS adopt the Plan 3
importer as-is instead of growing a second list. Mixed provenance in one run is the normal case for
a real audiobook project, not an edge case worth a mode for.

— Ruled by the maintainer on 2026-08-11 (decisions 1A and 2A, "ambiguities remaining: none");
implemented across Phases 6–7 and recorded by Claude Code at the Phase 15 closeout.

---

## 2026-08-22 — Chatterbox is an authorized Plan 4 scope expansion, on the exact model measured in Phase 8, with its dependency cost stated rather than absorbed

**Decision (v0.6.1 Plan 4, Phases 8–10, ratified at the Phase 15 closeout).**

**1. Chatterbox belongs to Plan 4.** It is a recorded scope expansion, explicitly ruled in by the
maintainer on 2026-08-11 rather than deferred to a plan of its own. Phases 8–10 were kept
self-contained so the expansion could be gated, measured and stopped at a hard boundary if the
evidence had gone the other way.

**Why:** the plan was already rebuilding the TTS panel's queue, dispatch and job control. Adding a
third backend afterwards would have meant reopening every one of those seams a second time. It was
scoped in with its own gates precisely so "we are already in here" could not become an excuse for
an unmeasured integration.

**2. The model is `ResembleAI/chatterbox-turbo`, from the published `chatterbox-tts==0.1.7`
wheel — and the import path is `chatterbox.tts_turbo.ChatterboxTurboTTS`.** Everything here was
read off the wheel, not off documentation or upstream master. The package root exports only
`ChatterboxTTS`, `ChatterboxVC`, `ChatterboxMultilingualTTS` and `SUPPORTED_LANGUAGES`, so the
documented `from chatterbox import ChatterboxTurboTTS` **fails**. **Nano is not reachable from
0.1.7** — `from_pretrained` takes `device` only, and the `nano=` parameter exists solely on
unversioned master. The model is 4,044,167,698 bytes (~3.86 GiB), MIT-licensed; output is float32
at 24 kHz; Turbo logs a warning and **ignores** `cfg_weight`, `exaggeration` and `min_p`; and the
upstream PerTh watermark is applied inside `generate` and is mandatory and default.

**Why:** the §5.6 Turbo/Nano discrepancy in the plan was real, and building against the documented
import would have failed at runtime on a fresh machine. Recording what the wheel actually exposes
is what makes a future upgrade a diff rather than a rediscovery.

**3. The dependency cost is stated, not absorbed.** Adopting the pin **downgraded**
`torch` and `torchaudio` to **2.6.0**, `transformers` to **5.2.0**, `safetensors` to **0.5.3**, and
pinned `numpy` to **1.26.4**, alongside the pins upstream leaves floating (`resemble-perth==1.0.1`,
`s3tokenizer==0.3.0`, `spacy-pkuseg==1.0.1`, `pyloudnorm==0.2.0`, `omegaconf==2.3.1`). All are
gated `python_version < "3.13"` alongside Kokoro. **This was proven not to damage Kokoro before it
was accepted**: on the combined stack in an isolated Python 3.12.10 venv, a real CPU synthesis
through the production `tts/kokoro_synth.py` produced byte-identical output (33,837 bytes, 8.35 s)
and the full suite passed unchanged; a clean venv then built from the committed
`requirements.txt` in one `pip install` with no manual correction. Installed size grew ~1,152 MB
(111 → 169 packages).

**4. `setuptools` is held at `80.9.0` as declared compatibility debt.** `resemble-perth` imports
`pkg_resources` while declaring no dependencies at all, and `chatterbox-tts` declares no setuptools
bound. Under this project's `82.0.1`, which removed `pkg_resources`, the import fails, perth
swallows it, sets its watermarker class to `None`, and model construction dies with a misleading
`TypeError: 'NoneType' object is not callable`. The reason lives beside the pin, and the
instruction is to move forward as soon as upstream stops importing it.

**Why:** a silent four-package downgrade under a working Kokoro stack is exactly the kind of change
that surfaces months later as "the voices sound different." Writing down each moved pin, and
proving Kokoro byte-identical across the move, is what makes the downgrade auditable. Pinning
backwards to keep a third party's undeclared import alive is debt and is labelled as debt.

— Ruled by the maintainer on 2026-08-11 (scope) and 2026-08-15 (gate G, the setuptools pin);
recorded by Claude Code at the Phase 15 closeout.

---

## 2026-08-22 — Chatterbox was adopted CPU-first on measured evidence; CUDA remains open and unauthorized

**Decision (v0.6.1 Plan 4, decision 7A and the Phase 8b gate E ruling).**

**Discovery was CPU-first and the numbers went to the maintainer before anything was integrated.**
On HOME-PC the measured aggregate real-time factor was **1.211** (0.826 audio-seconds per
compute-second) with a **~6,191 MB** peak working set — **slower than real time**, and it must never
be described as real-time CPU synthesis. That is neither clearly fine nor clearly fatal, and
calling it "practical" would have meant inventing a threshold. The phase stopped and returned the
measurements.

**Maintainer ruling (2026-08-15): accepted, for an optional, non-default engine.** Device selection
resolves `cuda → mps → cpu` behind one testable seam, so a CUDA machine will use it if one is
present — but **no CUDA-specific launcher, requirements entry, bootstrap step, index URL or
shared-PyTorch change is authorized**, and none was made. No CUDA build was installed or
benchmarked. On Apple Silicon the same seam resolves to `mps` and was later proven live in Phase 13
against the real model.

**Why:** an engine this heavy is a user-visible cost, not an implementation detail, so the decision
to ship it belonged to the maintainer with the figures attached. Leaving CUDA as an untaken branch
rather than an unbuilt feature means the acceleration question can be reopened later without
unpicking anything — and means no one can quietly add a multi-gigabyte CUDA wheel to a
requirements file that a non-technical user installs by double-clicking.

— Measured at Phase 8a; ruled by the maintainer on 2026-08-15; recorded by Claude Code at the
Phase 15 closeout.

---

## 2026-08-22 — The Chatterbox voice set is exactly four maintainer-authorized recordings, approved by ear before any registry row existed

**Decision (v0.6.1 Plan 4, Phases 9–10 and the Phase 13 macOS gate).**

**The voice set is fixed at four**, cloned from four maintainer-supplied reference recordings, and
labelled `Chatterbox - Female 1`, `Chatterbox - Female 2`, `Chatterbox - Male 1`,
`Chatterbox - Male 2` (ASCII hyphens). The earlier built-in-voice / gender-split design is
**superseded**.

**Approval preceded registration, deliberately.** Phase 9 was a hard stop: four evaluation outputs
were produced from the four references and returned to the maintainer with a summary table and
performance figures, and **no `VoiceEntry` row existed** until they had listened. They approved all
four on 2026-08-15, and approved all four again on 2026-08-21 after hearing them synthesized on
real Metal through the production path on macOS. The twelve original rows kept their identity —
voice IDs, backends, timing presets, ordering and the Steffan default (`VOICES[0]`,
`en-US-SteffanNeural`, edge) are unchanged.

**Display labels are the one thing that did move**, by explicit maintainer override on 2026-08-21,
into one consistent `Engine Gender - Name (locale)` form across all sixteen rows. **The override is
limited to user-facing display labels**; the exact ordered list, each former label proven
unoffered and unresolvable, and every other column are pinned by 39 tests. **No migration mechanism
was built, deliberately** — the selected voice is not persisted at all, by any key, so
compatibility code would have been fiction; two tests pin that absence so a future change which
starts persisting a voice fails loudly.

**Why:** a cloned voice is a judgement call about how someone sounds, and no automated gate can
make it. Registering a voice the maintainer had not heard would have put an unapproved identity in
front of users behind a passing test suite.

— Approved by the maintainer on 2026-08-15 (listening) and 2026-08-21 (macOS + labels); recorded by
Claude Code at the Phase 15 closeout.

---

## 2026-08-22 — Local Chatterbox assets are a portability boundary: never committed, never packaged, and never made portable without separate authorization

**Decision (v0.6.1 Plan 4, standing rule from Phase 0 through the Phase 15 closeout).**

**The four reference recordings in `files/Chatterbox-Voice-Uploads/`, every derivative made from
them, and every cached voice-identity conditional are local-only.** They are ignored by a narrow
rule at `.gitignore:55`, are untracked, were never staged, and exist nowhere in this repository's
history. Nothing derived from them is committed or packaged: derivatives and conditionals live
under the ignored `files/runtime-data/chatterbox/`, and production **refuses structurally** to
write inside the recordings folder and re-verifies each source SHA-256 **on every use**. Their only
authorized provenance statement is *maintainer-supplied local reference recording, authorized by
the maintainer for use by this local Chatterbox integration* — no copyright, consent,
redistribution or licence claim is made, and the speakers are not to be identified.

**Therefore Chatterbox is not portable, and that is the intended state.** A clone of this
repository on another machine will start, convert, and report every Chatterbox voice as *setup
required*. **Making Chatterbox work elsewhere requires separate explicit maintainer authorization**
and their own placement of their own recordings. No packaging step, installer change, download or
bundling may be added to close that gap on anyone's initiative.

**Why:** these are recordings of real people. The moment one enters Git history it is effectively
permanent and effectively published, and no later commit removes it. A boundary that depends on
remembering to be careful is not a boundary — so it is enforced by an ignore rule, by hash
verification on every use, by a structural write refusal, and by a degraded path that is truthful
instead of resourceful.

— Standing maintainer rule from Phase 0 (2026-08-11), re-verified at every phase gate including
Phase 13 on macOS and Phase 15 at closeout; recorded by Claude Code.

---

## 2026-08-22 — A hover-scoped global Tk binding must be released by ownership, on every path that ends the hover; and a missing Tk root is a failure where the desktop is the platform

**Decision (v0.6.1 Plan 4, Phase 14 / 14C / 14D).**

**1. `enable_mousewheel` keeps taking the shared root's single global `<MouseWheel>` slot — and now
gives it back on every path that ends the hover.** The launcher runs all six tools inside one root,
so `bind_all` owns exactly one wheel slot that every scrollable options region takes turns holding.
That design stays. What was wrong was the release side: only `<Leave>` released it, and **two real
lifecycle paths never fire a `<Leave>`** — the launcher's tool switch `pack_forget()`s the outgoing
panel out from under the pointer, and closing a panel destroys the region outright. Release is now
also bound to **`<Unmap>`** and **`<Destroy>`**.

**2. Release is guarded by ownership, never unconditional.** Because there is only one slot, a
second region entering *replaces* the first region's handler. A departing region therefore
compares the currently installed Tcl script against the script it installed, and gives the slot
back **only if it still holds it**. The script Tk installs names the region's own registered
callback, which makes it a self-describing ownership token needing no extra bookkeeping.

**Why:** an unconditional release would silently kill scrolling for the region the pointer is
actually over — trading a stale-binding bug for a dead-scroll bug. The measured symptoms of the
original defect were both real: the wheel scrolled the tool the user had just left, and once the
widget was destroyed the stranded callback named a Tcl command that no longer existed, so **every**
later wheel tick anywhere in the launcher raised `TclError: invalid command name …` through
Tkinter's callback reporter.

**3. The `<Unmap>` binding is kept because `pack_forget()` is the real tool-switch lifecycle**, and
it was proven to leak. It is not defensive padding.

**4. A test contract may not be corrected by weakening it.** The Cover browser's rule had been
*"no global `<MouseWheel>` binding may exist anywhere, ever"* — true of the browser, false of the
application, and therefore a tripwire for any other panel's legitimate hover state. It was replaced
by what actually matters and is strictly harder to satisfy: the browser's binding lives on its own
Canvas, and building, scrolling and closing it leaves whatever owned the shared slot **exactly** as
it found it, including when an unrelated region legitimately holds it.

**5. Where a windowing system is part of the platform, a failed `tk.Tk()` fails the run.** Every
live-Tk module used to wrap its root in `try/except TclError → pytest.skip`. That is correct on a
headless POSIX box and wrong on Windows, where an interactive login always owns a window station:
Phase 14 measured one full-suite invocation that **silently dropped forty-nine Chatterbox
integration tests and still exited zero**. The classification now lives once, in
`files/tests/tk_gate.py`, and is made **from the platform, not from the text of the error** —
Windows fails and carries the original exception; macOS and Linux still skip. Only `TclError` is
classified; anything else propagates as itself, because labelling a programming error "headless" is
how the coverage went missing. A structural AST guard forbids any collected module from opening a
root outside the gate.

**Why (5):** a skip is a claim that an absence is acceptable. On Windows that claim is false, and a
false skip is worse than a failure because the run still reports success. Deciding from the
platform rather than from the exception text also means a *new* Tcl failure mode cannot pattern-match
its way into being tolerated.

— Diagnosed, fixed and proved at Phase 14B/14C/14D; approved by the maintainer on 2026-08-22 in the
prompt authorizing Phase 15; recorded by Claude Code.

---

## 2026-08-22 — HEIC/HEIF format preservation is confirmed by live evidence; the 2026-08-11 ruling stands unchanged

**Decision (v0.6.1 Plan 4, decisions 3A and 54A — ratification, not a new rule).**

The rule is already recorded in full in the **2026-08-11** ADR below (*"Image-format capability is
a fifth shared module … with decode and encode kept separate and a missing encoder refusing rather
than substituting"*). It is repeated here only to record that it survived contact with real
hardware and is closed:

**HEIC output preserves the input format, and an unavailable encoder refuses truthfully rather than
silently writing a `.jpg`.** Phase 1 could only prove this through injected probe seams — no real
HEIC file was involved and none was claimed. **Phase 13 proved it live** on Apple Silicon against a
genuine maintainer-supplied `.heic` through the production code: real ISO-BMFF `ftyp` brand,
decode, **HEIC in → HEIC out with no `.jpg` anywhere**, decode and encode capabilities reported
separately and truthfully, and the output reopened and verified at 1024×1024 HEIF. **The source
file's SHA-256 was unchanged afterwards.** The `.jpg` fallback for genuinely *unknown* extensions
such as `.webp` is unchanged, and `REPLACEABLE_SUFFIXES` / `written_suffix()` remain byte-for-byte
as they were.

**Why record a ratification at all:** the original ADR was written from seam-level evidence and
said so. Leaving it there would have left a permanent decision resting on a proof it explicitly
disclaimed. This closes that gap without restating or amending the rule.

— Ruled by the maintainer on 2026-08-11 (decisions 3A / 54A); live evidence obtained at Phase 13 on
2026-08-20/21 and recorded by Claude Code at the Phase 15 closeout.

---

## 2026-08-19 — Chatterbox narration timing is frozen for Plan 4, and the MP3 file-size question is closed at the tested default

**Decision (v0.6.1 Plan 4, Phase 12 closeout — the maintainer's ruling after listening to the
regenerated chapter).**

**1. The remaining pauses are accepted, and narration timing is frozen for the rest of Plan 4.**
The natural-boundary remediation did what it was scoped to do: it removed *unpredictable,
formatting-driven* silence, taking the worst interior gap from 8.73 s to 2.90 s. The maintainer
listened and approved — much better, dead air resolved, a small amount of pause/lag remaining and
acceptable for this release. So: no global silence trimming, no maximum-model-silence cap, no change
to temperature (0.72), the 300-character ceiling, the chunk/paragraph pause, the end silence or
`COLON_PAUSE_MS` (75), and no further text-boundary heuristics without a demonstrated defect.

**Why:** the goal was never uniform timing. The four remaining ≥2 s pauses each correlate to a chunk
with zero newlines whose text contains a written ellipsis or literally narrates a silence — the model
pausing where the author wrote a pause. Post-processing those away would flatten intentional prose to
cure a symptom that no longer has the defect behind it, and it would do so on approved, listened-to
audio. Fine-grained pause/rhythm tuning is recorded as a future observation needing its own
authorization and its own evidence, not as pending work.

**2. The bitrate stays where it was tested. The file-size consequence is accepted, not re-litigated.**
The MP3 finalization ADR below referred one open question to the maintainer: honouring the panel's
`192k` default makes local-engine output an effective 160 kbps, ~5× the old 32 kbps (144 MB → 720 MB
for a ten-hour audiobook). **Ruling: keep the currently tested bitrate and default behaviour.** No
`64k` option is added, the default is not changed to `128k`, and the finalization architecture is not
reopened.

**Why:** the ~5× size is the price of the defect being fixed, and it was paid knowingly — the flagged
consequence went to the maintainer with the numbers attached, and the approval came *after* listening
to two long-form chapters produced at that contract. Changing the encode now would invalidate the
manual evidence that just closed the phase. Nothing is lost by waiting: the existing dropdown already
offers `128k` with no code change, and the 64 kbps correctness floor below stands regardless of which
value is chosen.

**3. The one native crash is still not claimed to be fixed.** The `pythonw.exe` / `torch_cpu.dll`
`0xC0000005` access violation is recorded as historical, characterised from the WER minidump, and
never reproduced in nine controlled attempts or any later run. Fatal-fault diagnostics were added and
self-proved so a recurrence is observable. **Closing Phase 12 does not close that**, and no document
may describe it as resolved.

— Ruled by the maintainer on 2026-08-19 after the Chapter 1144 recheck; recorded by Claude Code at
the Phase 12 closeout.

---

## 2026-08-18 — Chatterbox text is planned on natural boundaries, and no structural newline ever reaches the model

**Decision (v0.6.1 Plan 4, Phase 12 uncontrolled-silence remediation).**

**1. A raw newline is never an instruction to the model.** `split_for_chatterbox` guarantees that
no structural `\n` reaches `model.generate()`. A line break after a completed sentence becomes a
boundary; a line break inside a continuing sentence becomes an ordinary space.

**Why:** a newline handed to Chatterbox is rendered as a pause of no fixed length. A real chapter
contained an **8.73-second** silence produced that way, plus five more of 2.2–2.5 s. Every
configured pause in that file was correct — the silence was inside a single `generate()` call, and
the application had no control over it. Pause length must be the application's decision, expressed
in the assembly, not the model's improvisation on a formatting character.

**2. A sentence ends at a terminator followed by optional closing quotes or brackets.** The old rule
required the terminator to be the last character before the whitespace, so `."` / `?"` / `!"` — how
every line of dialogue ends — was not a sentence. Seventeen line breaks survived into the model in
one 6,251-character chapter.

**3. The hierarchy is paragraph → sentence → clause → whitespace → hard limit**, descended only as
far as the ceiling forces. Clause splitting (`;` `:` `—` `,`, in that order) applies **only** to a
single sentence already over the ceiling, so ordinary prose is never cut at a comma. The colon sits
below the semicolon on purpose: a colon that stays inside a chunk still earns its 75 ms
`COLON_PAUSE_MS`, whereas promoting it to a boundary would convert that into the 700 ms inter-chunk
pause.

**4. Units are packed, not emitted one per sentence.** Every chunk boundary earns a configured
pause, so one-sentence-per-chunk would insert a gap after every full stop and read as machine-gun
narration. Consecutive units are joined up to the 300-character ceiling.

**5. A chunk plan that does not preserve its source is refused, not returned.**
`_assert_content_preserved` compares every non-whitespace character, in order, and raises
`ChunkPlanError` on mismatch. Whitespace is deliberately excluded — this splitter is *required* to
normalise structural whitespace, which is how decision 1 is kept — so the invariant is
content-exact rather than byte-exact.

**Why:** Phase 10 shipped a run that truncated a 2,889-character chunk to 2.1% of its content **and
reported success**. Silent loss of narration is the failure mode that matters here; a run that stops
and says so is strictly better.

**6. The Web Novel Editor was a design reference only.** `elmatthe/web-novel-editor`
(`ai/chunking.py`, `rules/spacing_cleanup.py`) supplied two ideas: retain natural boundaries and
refuse a plan that cannot reproduce its input, and the closing-punctuation sentence-end form. **No
code was copied, imported or vendored, and no cross-repository dependency exists.**

**7. This is Chatterbox's splitter alone.** `kokoro_synth.split_into_chunks` (3,000 characters) and
Edge's `batch_convert.split_into_chunks` are untouched. The 300-character ceiling is not imposed on
any other engine.

*— Decided by the maintainer, implemented and measured 2026-08-18 on HOME-PC.*

---

## 2026-08-18 — Every TTS final MP3 is encoded exactly once, through one explicit contract, never on ffmpeg's defaults — and never below 64 kbps

**Decision (v0.6.1 Plan 4, Phase 12 audio-finalization audit).**

**1. The final encode contract is explicit and lives in one place.**
`shared.ffmpeg_utils.mp3_export_options(bitrate)` returns `format`/`codec`/`bitrate` — explicit
`libmp3lame`, explicit bitrate — and every TTS finalization goes through it: Kokoro, Chatterbox,
and the Edge *folder* path. Returned as keywords rather than performed there, so the encode stays
next to the audio and a test can assert the contract without running ffmpeg.

**Why:** pydub's `DEFAULT_CODECS` maps only `ogg`, so `export(path, format="mp3")` runs ffmpeg with
no codec and no bitrate and the output shape becomes a property of whichever ffmpeg is installed.
On this project's build that was 32 kbps for 24 kHz mono.

**2. Never below 64 kbps for a 24 kHz mono stream. This is a correctness floor, not taste.**
A Xing/Info header needs a 100-byte seek table, which does not fit in a 32 kbps MPEG-2 frame
(96 bytes). ffmpeg is therefore forced to emit the header frame at 64 kbps while the audio frames
stay at 32 — and still tag the file `Info`, i.e. constant bitrate. Any player that trusts that
declaration and reads the first frame's bitrate reports **exactly half** the real duration.
Measured with Windows Media Foundation on a 2:00 fixture: 1:50 at 24 kbps, 1:54 at 32, 1:58 at 48,
and exactly 2:00 from 64 kbps up. **Consequence: the panel's bitrate combobox must never offer a
value below 64k.**

**3. ffprobe and mutagen are not sufficient evidence that an MP3 is well-formed.**
Both read the Xing frame count and so report the correct duration for a file that is internally
inconsistent. All 168 shipped outputs passed under both. The regression guard therefore asserts a
structural invariant — the header frame's bitrate must equal the audio frames' bitrate — read from
the frame headers directly.

**4. Local engines assemble in PCM and encode once; the Edge folder path cannot and is exempt.**
Kokoro and Chatterbox hold numpy arrays, so writing per-chunk MP3s and decoding them back to merge
was a whole lossy generation for nothing — measured at **2.47 dB** on real Chatterbox speech
(19.25 dB → 16.79 dB SNR), consistent with the 1.66 dB recorded earlier on different material. The
Edge folder path receives already-encoded MP3 chunks from the network, so its second generation is
unavoidable; only its final contract was made explicit.

**5. Sample rate and channel count are deliberately NOT normalized.**
The MP3 Tool normalizes to 44.1 kHz stereo through PCM for its own job, and that remains correct
there. TTS output stays at the engine's native 24 kHz mono: resampling and channel expansion would
add cost and loss without improving duration, seeking or compatibility — the 64 kbps floor is what
fixes those, and a single-encoded 24 kHz mono file reads correctly in every parser tested.

**6. The bitrate comes from the control the user already sets, not a new constant.**
The TTS panel has always had an "MP3 bitrate" combobox (128k/192k/320k, default 192k) frozen into
each run as `params["bitrate"]` — but only the Edge *direct* path read it. Honouring it everywhere
fixes the defect for every selectable value with no new setting and no GUI change.
**Known consequence, flagged rather than absorbed:** local-engine output goes from 32 kbps to an
effective 160 kbps (192k clamps to the MPEG-2 ceiling at 24 kHz), so files are ~5× larger —
144 MB → 720 MB for a ten-hour audiobook. Changing it needs no code: pick `128k` in the existing
dropdown, or add a `64k` option if smaller files are wanted.

— Root-caused and implemented by Claude Code under the maintainer's Phase 12 audio-audit
authorization; the file-size consequence is referred to the maintainer for decision.

---

## 2026-08-11 — Image-format capability is a fifth shared module, proved by behaviour rather than by import, with decode and encode kept separate and a missing encoder refusing rather than substituting

**Decision (v0.6.1 Plan 4, Phase 1).** Four choices, recorded here because Phase 1 requires a
new `shared/` module to justify itself in this log — the module-split precedent from Plan 3 §7.

**1. A new `shared/image_capabilities.py` rather than an extension of an existing module.**
The phase's instruction is to prefer extending something that already exists, so the four
candidates were checked before adding a fifth: `ffmpeg_utils.py` resolves and configures external
*binaries* and pydub, `metadata.py` is M4B/MP4 tag mapping, `paths.py` is project-relative paths,
and `bootstrap.py` is first-run setup and installation. **Why none of them:** an image codec
capability is not a binary on PATH, not an audio tag, not a path and not a setup step, and
putting it in the closest of them (`ffmpeg_utils.py`, on the grounds that both "probe for
something optional") would mean a module whose docstring promises ffmpeg answering questions
about Pillow plugins. That is the kind of shared module later readers stop trusting. The new
module imports only the standard library at module level, so it costs nothing to import on a
machine missing every optional image dependency.

**2. Decode and encode are separate capabilities and are never collapsed into one boolean.**
`pillow-heif` wraps a `libheif` build that may have been compiled with a decoder and no encoder,
so "HEIC works" is two different questions. **Why it matters here rather than in the abstract:**
the Cover tool has a source-side *replacement* mode. A machine that can read HEIC but not write
it, reported as one boolean, would either crash mid-run or write a JPEG over an original's
name — an irreversible, silent format change to the user's own file. Two flags make that state
representable, and the panel offers HEIC for import while refusing it for output.

**3. Capability is proved by encoding one real pixel, not by an import succeeding.**
`register_heif_opener()` registers a *saver* whether or not an encoder exists behind it, so
asking Pillow's registry would report an encoder that is not there. The probe therefore imports,
registers, checks that Pillow genuinely gained the HEIF reader, and then encodes a 1×1 image to
memory and sees what happens. **Why this shape:** it also means the module depends on no upstream
symbol beyond `register_heif_opener`, so a `pillow-heif` release that renames or drops its own
capability-query helpers still probes correctly. The probe never raises — every failure becomes a
capability that says what is missing, with a truthful `detail` string for the log — which is what
replaces the bare `try: import pillow_heif … except Exception: pass` that previously sat at
module scope in `cover_resizer.py` and advertised support it had not verified.

**4. A missing encoder refuses; it does not substitute (Decision 3A).** `resize_for_audiobook`
now asks the probe before writing a `.heic`/`.heif` destination and raises
`UnsupportedImageFormat` when it cannot honour the format. The pre-existing `.jpg` fallback for
*unknown* extensions such as `.webp` is deliberately untouched: that format was never advertised
as preserved, so falling back breaks no promise, while HEIC was. `REPLACEABLE_SUFFIXES` and
`written_suffix()` are unchanged, because they encode what the writer can round-trip *by format*,
which is a static fact and not a property of the machine.

**And one thing deliberately not done.** `pillow-heif` is now pinned at `1.5.0` in
`scripts/requirements.txt` (Decision 54A: officially pinned, probed, tested) but is **not** added
to `bootstrap.REQUIRED_IMPORTS`. That list is the set of imports a machine must have, and adding
it would turn optional HEIC support into a startup requirement — the opposite of the degraded
behaviour this module exists to make truthful.

*Recorded at v0.6.1 Plan 4 Phase 1, 2026-08-11, on `feature/0.6.1-tts-cover-workflows`. These are
implementation decisions taken under the drop's delegated authority; maintainer approval of
Phase 1 is pending and no closeout claim is made here.*

---

## 2026-08-10 — Plan 3 is infrastructure with no adopters; truthfulness is enforced by construction rather than by review; the Tk boundary is one guarded module; and the manual evidence is recorded with its gaps intact

**Decision (v0.6.0 Drop 3, Phases 1–9; recorded at the Phase 10 closeout).** Six choices worth
keeping.

**1. The foundation ships adopted by nothing, and structural tests keep it that way.** Four new
shared modules exist and not one production panel, tool or launcher imports them. **Why build
something and then deliberately not use it:** six panels currently each own their own importing,
threading and progress code, and converting them in the same drop that invents the shared
contracts would mean debugging the contracts and the conversions at once, with no way to tell
which was wrong. Building the foundation first makes each later adoption a small, reviewable
change against something already proven. The boundary is not a promise: parameterised guards
AST-parse every module under `scripts/Universal/` and fail if any of them names a Plan 3 module,
`launcher.TOOLS` is pinned at six entries, and the three Tk-free modules are proved to import no
Tk at all. That last one is what makes the whole foundation testable with no display.

**2. A state that would be a lie is made unconstructible, not merely unasserted.** Two claims
matter most in a job UI, because both are easy to make and wrong: "it is paused" while an
indivisible stage is still running, and "it is cancelled" before the worker has stopped. Rather
than checking for them, the reporter mints every state-bearing event **from a controller
snapshot** the controller itself handed out, and that snapshot type refuses to exist for a
cancelled run without acknowledgement. **Why this rather than a validation rule:** a rule is a
thing a future caller can forget or route around; an unconstructible value is not. The same
reasoning shapes the Summary, which cannot leak a diagnostic because the projection that builds
it **never reads the field diagnostics live in** — proven with 200 files' worth of churn
producing three Summary lines — and the ETA, which returns `Calculating…` for every unreliable
case (unknown total, fewer than three comparable samples, a changed category, paused, ended, or a
question about another run) instead of a number nobody should trust.

**3. Every timestamp and every clock read is injected.** None of the three Tk-free modules
imports `time` or `datetime` or calls a clock; the caller supplies one. **Why:** §6.13's rolling
ETA, the pause-exclusion arithmetic and the event ordering are all time-dependent, and the only
way to test time-dependent behaviour without sleeping is to control the clock. The whole drop's
1,460 tests contain **no sleep at all**; races are arranged with barriers, events and bounded
joins, which means a hang fails loudly instead of the suite becoming slow and flaky.

**4. The Tk boundary is one module, one `after` chain, and one guard.** `job_ui.py` is the only
module in the drop that imports Tk. Inside it, `MainThreadPump` owns the single `after` chain —
the Phase 4 import poller rides its `schedule`/`cancel` seam rather than opening a second one —
and every public method that can reach a widget opens with a main-thread guard that **raises
before the widget is touched**. **Why a guard rather than a convention:** "workers must not touch
Tk" is the rule every tkinter application already has and the one they all eventually break, and
a violation shows up as an intermittent crash in somebody else's feature months later. Here a
worker's call fails immediately, at the call site, and a test proves the widget was unchanged.
The pump's single chain is also what makes "no lingering callback after close" checkable at all:
there is exactly one place to look.

**5. Composition, and reuse of what already exists.** The adapters own frames rather than being
them, take every decision as a callback, and define no base panel — a later tool builds its own
layout and hands these components a parent. They create no second manager, coordinator,
cancellation controller, event stream, progress implementation, logger, estimator or output
planner; they reuse the existing `ui_theme.ProgressIndicator` unstyled and the existing
`logging_setup` session logger. **Why:** an inheritance hierarchy invented before its first
adopter is a hierarchy the adopters spend the next five plans fighting, and a second progress
widget or a second log file is a divergence that only becomes visible once the two disagree.
Windows widgets ask the theme bundle for `ACT.*` names and the macOS/aqua and classic branches
ask for **no style at all**, which is why the native appearance is preserved without this module
ever testing the platform — and a before/after snapshot proves no generic ttk style was touched,
so the five unconverted panels render exactly as they did.

**6. The manual evidence is recorded with its gaps intact.** The Windows matrix was run on
HOME-PC and explicitly approved by the maintainer, and that attestation is the complete result —
the supplied screenshots support only a subset of it and are described that way. Three things are
written down rather than smoothed over: **exact 100%-display-scaling was never independently
confirmed**, so the functional matrix is a pass while the true-100% claim is not made; the
harness's literal source-tree before/after console line was not supplied, so repository
verification is recorded as corroborating source integrity rather than presented as the harness's
own output; and the maintainer additionally imported the repository folder as a root, which is
**broader than the plan's disposable-fixture-only preference** and is recorded as a test-scope
deviation. That last one was harmless and provably so: importing's entire filesystem budget is
`scandir` and `lstat`, the worktree stayed completely clean with no untracked file, `git diff
HEAD` was empty, and every tracked file and all 22 approved screenshots stayed byte-identical.
**Why record all three:** the honest failure mode of an approval phase is a green box nobody
observed, and a gap that is written down can be closed later, while a gap that is quietly rounded
up to a pass cannot. **Windows 125% and live macOS were not run for Plan 3 and remain deferred to
Plan 9**, consistent with the standing decision recorded on 2026-08-08.

*Signed: Elijah Matthew (maintainer), 2026-08-10 — approving v0.6.0 Drop 3 Phase 9 at
`9f0cf211a89efb064f6acf435b324bd8c4c1805f` and Plan 3 as a whole.*

---

## 2026-08-08 — Archives ship `config.toml` by explicit scope, concat lists follow ffmpeg's own quoting rules, panels are told when the output base moves, and two validations are deferred rather than faked

**Decision (v0.6.0 Drop 2, Phase 8 and its remediation; recorded at the Phase 9 closeout).**
Four choices worth keeping.

**1. The packager names its root files instead of excluding unwanted ones.** `release.py` writes
an enumerated `ROOT_FILES` list plus exactly one walked tree, and it never mentions
`config-template.toml`. **Why this rather than an exclusion rule:** an exclusion list is only as
good as the last person who remembered to extend it, and the file most likely to leak here sits
directly beside the file we must ship. A packager that never names a file cannot ship it by
accident, so the safety property holds for files nobody has thought of yet. `config.toml` is
copied byte-for-byte rather than generated, so what a user extracts is exactly what the
repository documents and the verify gate checks.

**2. Concat-list escaping follows ffmpeg's documented syntax, not shell intuition.** A path is
wrapped in single quotes and every `'` becomes `'\''` — close the quote, emit an escaped quote
outside it, reopen — and nothing else is touched. **Why the old code was wrong and why this is
not a guess:** ffmpeg's *Quoting and escaping* section states that characters inside single
quotes are literal, so the previous `\'` escaped nothing and ffmpeg read the quote as the
closing delimiter, silently truncating the path. The same function also doubled backslashes,
which survived only because Windows collapses repeated separators and would corrupt a genuine
one. The replacement is the exact form ffmpeg's own documentation gives
(`file '/mnt/share/file 3'\''.wav'`), and it is pinned by tests that drive the real binary over
spaces, Unicode, apostrophes and all three combined — never inferred from one passing fixture.
Shell quoting was deliberately not used: these are file-format rules, and `shlex.quote` stays
confined to the human-readable error log.

**3. A shared registry refreshes the panels; the panels do not learn to resolve paths.** Each
panel registers the read-only variable it already owns, and a successful Save or Reset calls one
helper that re-points them all. **Why not rebuild the panel, pass a callback down six
constructors, or let each panel recompute:** rebuilding would discard a user's in-progress
selections to update a label; new constructor parameters would churn six modules including the
five that Plan 1 deliberately left unconverted; and recomputing in a panel would duplicate the
resolution rules the whole plan exists to centralise. The registry is called from exactly two
places — the successful commit and the successful reset — so a rejected, cancelled or unsaved
value can never be displayed as effective, and a dead registration is dropped rather than raised
over, because refreshing a label must never break the call that just saved a preference. Run
reservation still re-reads the configuration at operation start, so the display is a hint and the
reservation remains the truth.

**4. Live macOS and the Windows 125% matrix are recorded as deferrals, not as passes.** Neither
was run for Plan 2. **Why record rather than approximate:** the honest failure mode of a long
validation phase is a green box that nobody actually observed. Automated aqua coverage is
import- and build-level and is not a live pass; changing Windows scaling needs the maintainer's
own action, and simulating it through the registry would produce evidence of the simulation
rather than of the product. The maintainer's standing decision is that Windows stays at true
100% for the remaining feature drops and the real 125% pass happens in the later dedicated
UI-compression/no-scroll phase, against a stable layout. Both deferrals are written down as
deferrals wherever Plan 2's result is recorded.

*Signed: Elijah Matthew (maintainer), 2026-08-08 — approving v0.6.0 Drop 2 Phase 8 at
`0e7ad0c264cb2a46f3c64f968e24f00963cb1987` and Plan 2 as a whole.*

---

## 2026-08-06 — Cleanup runs in a verified non-venv helper, the app closes only on a positive acknowledgement, the request is retired before the first deletion, and the inventory is never treated as permission

**Decision (v0.6.0 Drop 2, Phase 7).** The post-exit coordinator exists and deletes. Seven
choices behind it.

**1. The maintenance state lives at `files/runtime-data/maintenance/`, and the project owns
it.** Not configurable, not nameable from a request, derived from a repository root the caller
had to prove, and re-validated on every use to be inside the repository and outside all four
removable targets. **Why there rather than a temp folder or the user profile:** the record of
what cleanup was asked to do must survive cleanup, must belong to this project so uninstalling
is still "delete the folder", and must be somewhere the operation itself can never delete. It
sits beside `logs/` and `models/` without being inside either, is already ignored by
`files/runtime-data/`, and is never packaged because archives carry only `scripts/` plus the
root launcher and README.

**2. The helper is a separate process under an interpreter *verified* to be outside any
virtual environment.** Candidates come from `sys._base_executable`, `sys.base_prefix` and
`PATH`; anything inside the repository is rejected before it is probed; the survivor must
itself report `sys.prefix == sys.base_prefix`. **Why verified rather than assumed:** the first
thing this helper may be asked to remove is the interpreter the application is running from. A
guess that turns out to be the venv would delete the process's own feet. The helper is
standard-library only for the same reason — it has to keep working while `.venv` disappears
underneath it.

**3. Cleanup is *not* routed through `bootstrap.py` or the root launchers, and neither file was
changed.** **Why, when the plan named them as the boundary:** the plan's requirement is that
cleanup runs outside the venv, and the reason it named `bootstrap.py` is that `bootstrap.py` is
the existing stdlib pre-venv code. But importing it opens a dated setup log inside
`files/runtime-data/logs/` — one of the four selectable targets — and on Windows that open
handle blocks the deletion the run was asked to perform. A dedicated stdlib module honours the
requirement without sabotaging it, and the coordinator logs into the maintenance folder
instead. The rebuild the plan asks for already works untouched: the `.bat` fast path tests for
`.venv\Scripts\pythonw.exe` and falls through to ordinary setup when it is gone. Changing a
working launcher to add a route nothing needs would have been the larger risk.

**4. The application closes only after a positive acknowledgement — never after a successful
spawn.** The helper writes its acknowledgement only once it has started, loaded *that* request,
validated it, checked the repository root and the state folder, and is ready to wait; the GUI
waits for that, bounded, and gives up early if the process dies. **Why not treat `Popen`
returning as success:** "the helper started" and "the helper understood and accepted the job"
are different facts, and only the second one justifies telling a user their data will be
cleared and then taking their window away. Every failure path withdraws the request and leaves
the app open, so the worst outcome is a wasted click rather than a lie.

**5. The request is retired before the first deletion, not after the last.** `os.replace` moves
it to a consumed name the moment the wait ends and before anything is removed. **Why that
order:** a crash halfway through a pass must not leave an executable request behind — a second
run would start deleting again against a tree that is already half gone, with no record of what
the first attempt did. Retiring first means a crash costs a partial cleanup and an honest
absence of a result, never a repeat. If the request has vanished at that moment because the
requester withdrew it, the run stops and deletes nothing.

**6. The inventory the user saw is never authorization.** Every target is re-derived from its
enumerated ID and re-checked — exact compiled target, containment, repository root, protected
paths, links at every level, and type — immediately before it is touched. **Why re-check what
was checked minutes ago:** between the confirmation and the deletion the app closed, which is
plenty of time for a folder to be replaced by a junction pointing at someone's photo library. A
target that changed shape is refused and recorded, not followed. For the same reason, a link
found *inside* a target is detached rather than descended into: removing a junction never
touches what it points at, and walking one might.

**7. Process-id reuse is defended with a handle, not a hope.** On Windows the helper opens a
handle to the requesting process *before* acknowledging, so the wait is bound to that exact
process object; a recycled id cannot end it early. Elsewhere it polls liveness and relies on
the six-hour staleness ceiling. **Why this matters at all:** the entire safety of "delete after
the app exits" rests on knowing *which* exit was observed. A bounded wait that ends because
some unrelated program inherited the number would delete while the app was still running.

— Elijah Matthew, 2026-08-06

---

## 2026-08-04 — The cleanup catalog is a closed set of four IDs, a request may never carry a path, nothing is selected by default, an unreadable size is said out loud, and Phase 6 fails closed rather than pretending

**Decision (v0.6.0 Drop 2, Phase 6).** The downloaded-data inventory and its confirmation now
exist. Six choices behind them.

**1. Exactly four asset IDs, in a closed catalog that cannot grow at runtime.**
`virtual_environment`, `portable_binaries`, `downloaded_models`, `application_logs` — held as
frozen dataclasses inside a tuple behind a `MappingProxyType`. **Why closed rather than
discovered:** a cleanup feature that enumerates "regenerable-looking" directories is one
mislabelled folder away from deleting someone's work. Every ID here was approved individually
and maps to a directory this project created and can recreate. The audit did notice other
regenerable-looking directories; none were added, per the drop's instruction to stop and ask.
Settings, `config.toml`, outputs, source media, repository source/docs/tests and anything
system-installed are absent by construction, not by a filter that could be widened later.

**2. A request carries enumerated IDs and no path — ever.** There is no `path`, `target`,
`directory`, `root`, `command` or executable field in the request or the result schema, and a
test asserts that of every field name plus the serialized bytes. **Why this specific shape:**
the dangerous version of this feature is one where a widget, a JSON file or a TOML key can
name a directory that reaches a recursive delete. Making the schema physically incapable of
expressing a path removes that whole class of bug rather than defending against it. The single
ID→path mapping takes an always-explicit repository root, has no default, and returns nothing
until the result is proved to be the exact compiled target, contained, non-protected and
link-free. Normalisation deliberately uses `abspath` rather than `resolve()`, because
`resolve()` would *follow* a junction and quietly hand back somewhere else on the machine —
the exact failure the check exists to catch.

**3. Nothing is selected by default, and nothing is remembered.** Every checkbox is created
unchecked on every open; missing and unsafe rows have no usable control; `selected_ids()`
intersects "ticked" with "eligible" so a forced variable yields nothing. **Why no "recommended"
preset:** a preselected destructive set converts a deliberate act into a default one, and the
whole safety argument for this feature rests on the user having chosen each item. Selection is
never persisted for the same reason — a remembered choice is a choice made in a context the
user can no longer see.

**4. An unreadable size is reported, not guessed.** An estimate that skipped a link or hit a
permission error comes back `complete=False`, the row reads `1.2 MB (at least)`, and the
confirmation says *"plus data whose size could not be read safely."* **Why not just show the
partial number:** the figure is the user's main basis for consenting, and a total that silently
under-reports is a lie told at exactly the wrong moment. Links are never followed during
estimation, so a junction cannot inflate — or redirect — the walk.

**5. One custom confirmation, Cancel as the focused default, no suppression.** Not a
`messagebox`: this needs the item list, the sizes, the effect lines and the exclusions in one
place. The destructive button is never the default, so a reflexive Return dismisses it safely;
Escape and the window-close control both cancel; and the window is rebuilt from the live
selection every time, so there is no cached text and no "don't ask again" to find. This mirrors
the Phase 5 replacement confirmation deliberately — the two most dangerous actions in the app
should behave identically under the user's hands.

**6. Phase 6 fails closed rather than pretending.** Accepting builds one validated request and
passes it to a callback; the production callback returns `False` and the dialog says *"Cleanup
did not start. Safe post-exit cleanup is not available yet. No data was changed, and Audiobook
Creation Tool will remain open."* **Why ship a dead end at all:** the alternative was to hold
the UI back until Phase 7, which would have meant designing the request schema, the
authorization rules and the confirmation *against* an executor rather than before one — and the
safety properties above are precisely the ones that are cheap to establish first and expensive
to retrofit. A callback that raises is treated identically to one that refuses, so a future
coordinator crashing can never leave the app claiming cleanup was scheduled.

**A note for Phase 7.** `AssetDefinition.removes_target_itself` already records the difference
between removing `.venv` and emptying the other three, and `requires_post_exit` already records
which assets are open while the app runs. Those are inputs to the coordinator, not decisions it
should make again.

— Claude Code, on the maintainer's instruction (v0.6.0 Drop 2 Phase 6)

---

## 2026-08-04 — Cover replacement is gated three ways and installed atomically; the temporary sibling lives beside its source; a custom destination is the user's folder, so cleanup may never remove it

**Decision (v0.6.0 Drop 2, Phase 5).** The two destination exceptions of Decision 10A now
exist. Five choices behind them.

**1. Replacement needs three independent gates, and each is inert alone.** The
`Save beside source images` toggle, the `Replace original files` radio, and the per-run
confirmation. `effective_mode()` is the single place that combines them, and it returns a safe
mode unless *both* switches are open — so a stale radio behind a switched-off toggle cannot do
anything, and turning the toggle off actively resets the action. **Why three rather than a
confirmation alone:** a confirmation is the last thing a user reads, and people click through
last things. Two deliberate, visible selections mean the dialog is a confirmation of an
intention the user already expressed, not the first time they learn what is about to happen.

**2. The temporary sibling is written beside the source, not in the system temp directory.**
An atomic install requires the temporary file and its target on the same filesystem;
`%TEMP%` frequently is not (a different drive, a different volume). Writing beside the source
guarantees it. `tempfile.mkstemp` supplies uniqueness atomically, so the name cannot collide
with the source, another planned temporary, or an unrelated file. The distinctive
`.act-tmp-` prefix is not decoration: `discard_temporary()` **refuses** any path without it, so
a cleanup path can never be talked into deleting a user's file.

**3. The order is write → validate → replace, and never delete-then-rename.** The finished
image is reopened and its dimensions checked *before* it is installed, so a truncated or
unreadable write cannot reach the original. `os.replace` is atomic on both Windows and POSIX,
so there is no instant where the original is missing. Delete-then-rename was rejected outright:
it opens a window where a crash loses the file entirely. Everything before the `os.replace`
call is recoverable — which is why the failure tests inject at three different points (write,
validation, replace) and all three assert the original is byte-for-byte intact.

**4. A partial batch tells the truth.** Files already installed stay installed; the run reports
"N of M original(s) replaced; any not reached are unchanged." The confirmation says the same
thing in advance. **Why not roll back:** a rollback would need a second copy of every original,
which is the very duplication the user opted out of by choosing replacement — and a failed
rollback is worse than an honest report.

**5. Numbered copies start at `-1`, and sequences are per source directory.** Beside a source,
the unnumbered name *is* the source, so offering it would mean proposing to overwrite the file
being read; `plan_beside()` therefore starts at index 1 and asserts the result differs from the
source. Sequences are tracked per directory so two same-named images in different folders each
get their own `-1` rather than sharing one counter — which is what a user who imported
`shoot1/cover.jpg` and `shoot2/cover.jpg` expects to see.

**The bug this phase found before it shipped.** Phase 4's cancellation path ran
`shutil.rmtree(out_dir)` unconditionally. That is correct for a reserved run, which belongs
entirely to one build — but in the new custom-destination mode `out_dir` **is the folder the
user chose**, so cancelling a build would have deleted it and everything in it. Cancellation now
branches on the mode and removes only this operation's own staging and its own partial output.
Staging in custom mode also moved to an operation-owned `tempfile.mkdtemp()`, so a user's folder
never sees a `build/` directory or an `ERROR.txt`. **Any future cleanup added to this tool must
ask the same question first: does this path belong to us, or to the user?**

**Testing note worth keeping.** The confirmation dialog is built by
`build_replacement_dialog()`, separate from the modal `_ask_replacement()` wrapper, because
driving a real modal loop headlessly hangs. The wording lives in `replacement_message()` and
`replacement_button_label()` so the dialog and the suite read the *same* text — a test that
restated the wording would let the two drift, and this is the one message a user relies on
before an irreversible action. Real focus cannot be observed on a withdrawn root, so the
dialog records `default_widget` explicitly and the suite asserts that plus a source-level check
that `focus_set` targets Cancel and nothing targets Replace.

**Alternatives considered:** a typed confirmation phrase (rejected by the maintainer — the two
explicit selections, exact count, safe default and labelled destructive button are the approved
strong confirmation); `messagebox.askyesno` (rejected — a bare Yes/No cannot carry
"Replace 3 Original Files", and its default is not reliably the safe answer); rolling a partial
batch back (rejected — see 4); keeping the temporary file in the system temp directory
(rejected — see 2); allowing replacement of formats that fall back to `.jpg` (rejected — the
written file would not be the source's name, so it is refused before the dialog with a pointer
to numbered copies).

— Decided by maintainer via drop `0.6.0-drop2-config-output-maintenance-foundation.md` plus the
exact confirmation wording supplied for Phase 5, implemented and recorded by Claude Code,
2026-08-04 (HOME-PC, Windows 11, repo venv Python 3.12.10, ffmpeg and Pillow present)

---

## 2026-08-03 — The output base is managed only in Preferences; per-tool Browse controls are removed; the Cover overwrite option is disabled until Phase 5 rebuilds it safely

**Decision (v0.6.0 Drop 2, Phase 4).** All six tools now write to
`<output base>/<Tool>-Outputs/<Tool>-N/`, reserved at validated operation start. Four choices
came with that.

**1. Per-tool output-folder Browse controls are gone.** Five panels had an editable output
field with a Browse button, defaulted at `build_ui()` time to a `Downloads/<Tool>-N` guess.
Under Plan 2 the output base is a *configuration* value managed in Preferences & Data, and a
per-panel override would bypass it — the plan explicitly forbids stale output-folder fields
that route around the configured base. Each panel now shows its tool folder read-only and names
the actual reserved run once an operation starts. **Why not keep Browse and validate it?**
Because that is the M4B Maker *custom destination* feature, which Decision 10A and the drop
assign to Phase 5 with its own validation and containment rules; shipping an unvalidated
version of it in Phase 4 would pre-empt that design. Input and cover folder history is
untouched — those are dialog conveniences, not destinations.

**2. Reservation happens at operation start, and only there.** The old model picked a number
when the panel was built and froze it for the session, which meant the displayed folder was a
*prediction*: two tools open at once could show the same number, and the number could be taken
by anything else before the first save. Now nothing is created until inputs validate, and the
number comes from the atomic `mkdir` at that moment. A displayed path therefore never promises
a run that does not exist. An AST test asserts `reserve_run_directory` is called only from
action handlers, never from `build_ui` or `__init__` — attributing to the *innermost* enclosing
function, because TTS's `run_job` is a closure defined inside its builder.

**3. Each output-producing action gets its own run — not one run per panel session.** MP3
Tool's combine, time-edit and ID3 are three separate operations, as are the editor's Write
Tags, Clear All Tags and Remove Series Numbering. Sharing one run across them would mix
unrelated results and make "which files came from which action?" unanswerable. It also keeps
cancellation cleanup honest: staging belongs to exactly one operation, so it can never reach
another run, the tool parent or the base.

**4. Cover Image's legacy overwrite control is disabled, not removed and not left live.** This
was the §G blocker: the drop specifies the Phase 4 default and the Phase 5 source-side mode but
never rules on the already-shipped destructive checkbox in between. The maintainer chose the
disabled-placeholder route, and the implementation goes past the widget state deliberately:
`var_overwrite` is forced `False` and the captured worker parameter is the **literal** `False`
rather than a widget read, so re-enabling the checkbox alone could not route an operation into
the source-side branch. `next_version_path()` and that branch are retained as dormant legacy
code — removing them would be churn Phase 5 immediately undoes — and a test asserts the
parameter is a literal and that no Phase 5 interface (mode toggle, numbered-copy/replace
choice, confirmation dialog) exists yet.

**A real bug this migration exposed and fixed.** `avoid_input_overwrite()` only guarded against
writing *onto an input*. Two imported files with the same name from different folders silently
overwrote each other in the Converter, MP3 Tool and Metadata Editor. The shared batch planner
tracks existing files *and* already-planned names, so the second becomes `Book-1.mp3`.

**A real bug this migration introduced, and what it changed about testing.** Routing the
Converter through the planner removed its local `stem` assignment while the metadata fallback
title still used it — every conversion failed with `name 'stem' is not defined` and produced
nothing. **Every planner-level test passed**, because they exercised destinations rather than
the worker body. It was caught by driving the real worker on a generated tone fixture. The
lesson is recorded in the suite: `test_tool_output_integration.py` now runs the actual
Converter, time-edit and Cover workers, so a migration that breaks a worker cannot pass again.

**Alternatives considered:** keeping the Browse field but validating it against the base
(rejected — that is Phase 5's custom-destination feature); one reservation per panel session
(rejected — see 3); removing the Cover overwrite code entirely (rejected — Phase 5 rebuilds it,
so deleting it is churn); deleting `next_output_dir`/`avoid_input_overwrite` now (rejected —
kept as documented dormant API in case of an out-of-tree caller, with a test proving nothing
shipped calls them).

— Decided by maintainer via drop `0.6.0-drop2-config-output-maintenance-foundation.md` and the
Option A ruling on the Cover control, implemented and recorded by Claude Code, 2026-08-03
(HOME-PC, Windows 11, repo venv Python 3.12.10, ffmpeg present)

---

## 2026-08-03 — Output planning is pure and materialisation is explicit; `mkdir` is the reservation race boundary; collisions are case-insensitive everywhere; only the final suffix is an extension

**Decision (v0.6.0 Drop 2, Phase 3).** Five choices behind `shared/output_paths.py`. None of
them is visible to a user yet — no tool consumes the module until Phase 4 — but they are the
shape every later phase builds on.

**1. Planning is pure; materialisation is explicit and narrow.** Every `plan_*` function, the
sanitizer and the collision service compute paths and touch nothing. Only `ensure_output_base()`
and `reserve_run_directory()` create anything, and only directories. **Why:** it makes the
entire surface testable in a temporary tree with no mocking, and it makes "merely opening a tool
creates no folder" a structural property rather than a discipline. It is also what lets a plan
be built on the main thread and handed to a worker, which is the pattern every tool already
uses for its job snapshot.

**2. `mkdir` without `exist_ok` *is* the reservation race boundary.** There is deliberately no
"does this number exist?" check before the create — that check-then-create sequence is exactly
the race the plan forbids. `mkdir` either creates the directory or raises `FileExistsError`;
the loop simply moves to the next number. **Why it matters:** two tools running concurrently, or
one tool started twice, would otherwise silently share a run directory. An 8-thread test with a
barrier proves all eight get distinct directories numbered 1–8. The loop is bounded so a wedged
directory cannot hang a worker. **Do not "optimise" this by pre-scanning the parent.**

**3. Collision comparison is case-insensitive on every platform.** Windows and macOS are both
case-insensitive by default, so `Book.m4b` and `book.m4b` are one file there. Making the
comparison platform-dependent would make a plan differ between the two machines this project
ships to; making it case-insensitive everywhere keeps plans identical and errs toward an extra
`-1` rather than toward an overwrite. On a case-sensitive Linux box the cost is one redundant
suffix; the alternative cost is data loss. **The safer direction is the default.**

**4. Only the *final* suffix is treated as the extension.** `Path.suffixes` would call
`.5 - Extras.m4b` the extension of `Book 1.5 - Extras.m4b` and mangle it; audiobook filenames
contain dots constantly, and multi-part extensions like `.tar.gz` never appear in this
project's outputs. So `archive.tar.gz` collides to `archive.tar-1.gz`, which loses nothing, and
`Book 1.5 - Extras.m4b` collides to `Book 1.5 - Extras-1.m4b`, which is right. The drop's
"preserve the complete suffix" is satisfied — the extension is never truncated or lost — and
its own examples (`stem-1.ext`, `Book-1.m4b`) are all single-suffix.

**5. Link safety is a separate check from containment, because containment cannot catch it
all.** A junction pointing *outside* the run directory is caught by containment: `resolve()`
follows it and the destination normalises outside the root. But a junction pointing *back
inside* the root resolves to a contained path and passes containment entirely — and following
it would still mean establishing a destination through a link an attacker or a stray tool
placed there. `assert_no_link_in` walks every existing component and refuses any reparse point,
which is what closes that gap. Both tests exist, and the second one exists precisely because
the first does not cover it.

**Trailing dots and spaces are stripped deliberately.** Windows silently drops them when
writing, so `Book.m4b` and `Book.m4b ` would land on one file after the collision service had
already decided they were two different names. Stripping them in the sanitizer makes the
collision check see what the filesystem will see.

**Windows link testing uses junctions.** `mklink /J` needs neither Developer Mode nor
elevation, so the directory-link safety tests get real coverage on an ordinary account instead
of being skipped. Only the file-symlink test still requires the privilege and skips with its
exact `WinError 1314` reason recorded.

**`paths.next_output_dir()` stays untouched until Phase 4.** It is marked as a compatibility
wrapper scheduled for removal, and a test records the exact five panels that still call it — so
a sixth caller fails the suite and Phase 4's removals show up in the diff. Phase 3 changes no
current output behaviour at all.

**Alternatives considered:** a lock file or a global counter for run numbers (rejected —
`mkdir` is already atomic on every filesystem this runs on, and a lock file adds a stale-state
failure mode); platform-dependent case comparison (rejected — see 3); `Path.suffixes` for
multi-part extensions (rejected — see 4); rewriting a traversal attempt to something safe
instead of raising (rejected — silently "fixing" `../..` hides a real defect in the caller);
letting the planner create directories as it goes (rejected — it would make every planning test
require a filesystem and would break the "opening a tool creates no folder" guarantee).

— Decided by maintainer via drop `0.6.0-drop2-config-output-maintenance-foundation.md`,
implemented and recorded by Claude Code, 2026-08-03 (HOME-PC, Windows 11, repo venv
Python 3.12.10)

---

## 2026-08-03 — The Preferences dialog is presentation-only and platform-neutral; the launch-warning guard lives in the config layer; the Clear Downloaded Data placeholder carries no command

**Decision (v0.6.0 Drop 2, Phase 2).** Four choices worth not re-litigating.

**1. `preferences_ui.py` decides nothing.** Every rule the dialog enforces — what a valid
output base is, what precedence applies, what a reset clears — lives in `shared/config.py`
and `shared/settings.py` and is tested without Tk. The dialog collects choices and shows
results. **Why:** the Plan 2 contract requires configuration, path and reset logic to be
platform-neutral and testable headlessly; the moment a validation rule lives in a widget
callback, it can only be tested by building a window.

**Styling degrades instead of branching.** `_style(theme, name)` returns `""` wherever
`theme["styles"]` is absent, and a ttk widget naming no style resolves the platform's generic
one. So the Windows build is fully `ACT.*` and the macOS build is fully native from a single
code path, with **no `sys.platform` branch anywhere in the file**. This is the same mechanism
that keeps the five unconverted panels native — not a coincidence, and worth preserving.

**2. The once-per-launch guard belongs in the configuration layer, not the UI.**
`config.take_launch_warning()` consumes the guard; `reset_launch_warning_guard()` re-arms it
for tests. **Why:** diagnostics are produced on *every* load, so a UI-owned flag would let a
reload storm become a dialog storm, and a headless test could not assert the "at most once"
contract at all. Putting it beside the thing that generates diagnostics makes the rule
testable without a display and makes "reopening Preferences must not repeat the warning" fall
out for free rather than needing its own special case.

**The warning is a non-modal `Toplevel`, not a `messagebox`.** The drop calls for a
*nonblocking* summary presented after the root window is ready. A `messagebox` is modal by
definition, so it was rejected; a plain `Toplevel` with a Close button shows the whole
aggregated summary at once — one window for every diagnostic, never one per bad key — and
cannot block the launcher. A failure to present it is caught and logged: **a warning about
configuration must never itself become a startup failure.**

**3. The Clear Downloaded Data placeholder carries no command.** It is created disabled *and*
with no callback at all, so there is nothing to invoke even if some future code re-enabled it,
and `preferences_ui.py` is AST-asserted to import no `shutil`/`subprocess`/`os` and to call no
`rmtree`/`unlink`/`remove`/`Popen`. **Why:** "disabled" is a UI state that a one-line change
can undo; "there is no function to call" is a structural guarantee. Phase 6 owns the catalog,
the confirmation, the coordinator and the deletions.

**4. A failed settings write is now rolled back in memory.** `settings.set()`/`update()`
previously mutated the cache and then returned `False` if the atomic write failed, leaving the
running application believing a preference that never reached disk. They now restore the
previous value on failure. **Why:** the dialog tells the user "the previous setting is still in
use" after a failed save, and that sentence has to be true. Found by building the failure path
rather than by a bug report; regression-tested from both the settings layer and the dialog.

**Layout, measured rather than assumed.** The first build was **689 px tall under the Windows
theme** — taller than the application's own `920×600` minimum — while the unstyled build was
556 px, so a test that only exercised the unstyled bundle passed and hid it. Entry/Browse/Save
now share one row, Reset sits on its card's heading row, and the outer padding uses the tight
end of the spacing scale: **618×596 px on Windows, 630×488 px unstyled**, no whole-dialog
scrolling. The fit test now asserts the Windows path explicitly. `MIN_SIZE = (920, 600)` and
`DEFAULT_GEOMETRY = "1024x720"` are unchanged.

**Alternatives considered:** a modal `messagebox` for the warning (rejected — the drop requires
nonblocking, and one modal per key was explicitly forbidden); a UI-owned "already warned" flag
(rejected — untestable headlessly and vulnerable to reload storms); omitting the Clear
Downloaded Data control until Phase 6 (rejected — the maintainer expressly wants the disabled
placeholder, so it ships inert and clearly labelled); a menubar instead of a status-bar button
(rejected — the launcher has no menubar on any platform, and adding one is a shell change Plan
1 did not sanction); a scroll region to solve the height (rejected — the fit contract says
adaptive layout first, and scrolling is for genuinely unbounded content).

— Decided by maintainer via drop `0.6.0-drop2-config-output-maintenance-foundation.md`,
implemented and recorded by Claude Code, 2026-08-03 (HOME-PC, Windows 11, 1920×1080 at 100%
scaling, repo venv Python 3.12.10)

---

## 2026-08-03 — Configuration is a three-layer precedence with a one-key mutable overlay; the four documentation names are a permanent, mechanically enforced contract; the maximized-fit rule is the Plan 9 acceptance target

**Decision (v0.6.0 Drop 2, Phase 1).** Five things are settled and later plans should build on
them rather than re-litigate them.

**1. Precedence is code defaults → `config.toml` → an allowlisted mutable overlay.** A
committed, commented root `config.toml` holds the project's documented defaults;
`shared/config.py` resolves one typed, immutable `EffectiveConfig` snapshot from it. The
overlay is deliberately **one key** — `output_base_directory` in `settings.json` overriding
`output.base_directory` — declared in `config.SETTINGS_OVERLAY`, which is the whole allowlist.
Anything else in `settings.json` is either known user state (`last_tool`, remembered dialog
directories, voice, bitrate) that is skipped silently, or an unrecognised key that is ignored
with one diagnostic.

**Why a whitelist rather than "any settings key may override its TOML twin":** a name-matching
rule would silently promote a future preference into a configuration override the moment
someone happened to name it after a TOML key. An explicit table makes every override a
deliberate, reviewable line of code. **Do not add a key to it without a plan that says so.**

**Why the existing user-state keys got no TOML counterpart:** they are per-user memory, not
project configuration; inventing `[state] last_tool = …` would put a machine-specific value in
a committed, shipped file for no benefit.

**2. Validation is per key, and the runtime and the repository gate deliberately disagree.**
At runtime a bad value falls back and warns — a user's hand-edit must never stop the
application from starting, and one bad key must never discard its valid neighbours.
`scripts/verify.py` does the opposite and **fails on any diagnostic**, because a *committed*
file that needs a fallback is a defect being shipped. Both use the same loader, so the rules
cannot drift apart. Diagnostics carry a human-readable `message` and a separate technical
`detail`, so a summary can never leak a traceback while the log keeps everything.

**3. Relative output bases are rejected; environment variables are never expanded.** A
relative path would mean something different depending on where the launcher was started
from, so it is refused rather than resolved against the working directory. `~` **is** expanded
because it is portable and machine-agnostic; `%USERPROFILE%` / `$HOME` are **not**, which
makes them literal, therefore relative, therefore rejected. This is a safety boundary, not an
oversight — arbitrary shell-style expansion in a path that later feeds output and (in Plan 2's
later phases) cleanup is exactly the wrong place for surprises.

**4. The four documentation names are permanent and mechanically enforced.**
`md-instructions/Briefing.md`, `Changelog.md`, `Decisions.md`, `Handoff.md`, in exactly that
casing. Never rename, recase, duplicate or alias them; never recreate `CHANGELOG.md`,
`DECISIONS.md` or `handoff.md`. The gate compares **real directory entries** via `os.listdir`
rather than calling `Path.exists()`. That distinction is the whole point: `verify.py` had been
reading `md-instructions/CHANGELOG.md` ever since the documents were recased, and reported
`PASS` for weeks purely because a Windows path lookup is case-insensitive — on a case-sensitive
filesystem the gate would have failed outright. The stale *reference* was the bug; the files
were correct. `files/tests/test_repository_contract.py` proves the gate rejects a missing
canonical file, every case-variant alias, and a deleted `don't-delete/` reference, using
temporary trees because a case-insensitive filesystem will not let a real alias be staged
beside its canonical twin.

**5. The maximized-fit rule is the Plan 9 acceptance target and binds new UI now.** At
1920×1080 on Windows at 100% and 125%, plus the approved live macOS reference display, the
maximized launcher must show each complete tool view without a whole-panel or whole-form
scrollbar where practical, reached through adaptive layout rather than by wrapping a tool in a
permanently scrolling canvas. Scrolling stays valid for genuinely unbounded content (file
lists, book collections, chapter titles, logs, thumbnail browsers) and must stay local to that
region with primary actions, Cancel/Pause/Resume, progress, status and output access still
reachable. At `920×600` the requirement is graceful adaptation, not simultaneous visibility.
`MIN_SIZE = (920, 600)` and `DEFAULT_GEOMETRY = "1024x720"` are **unchanged**. The M4B
Metadata Editor's permanently scrolling form remains an accepted Plan 1 limitation that Plan 9
must reflow — recording the target here does not reopen the Plan 1 approval.

**Structural rule worth keeping:** `shared/config.py` must never import `logging_setup`.
Retention reads configuration, so the dependency runs one way only; `logging_setup` imports
config lazily *inside* `configured_max_sessions()` and falls back to 30 on any failure,
because logging has to come up even when configuration cannot.

**Alternatives considered:** a TOML parser dependency such as `tomlkit` (rejected — stdlib
`tomllib` is sufficient for reading, and the plan forbids a new dependency without proving the
standard library insufficient); letting the GUI write `config.toml` (rejected — the committed
file must stay machine-agnostic and diffable, so user choices go to `settings.json`); making
the runtime *fail* on an invalid config to match the gate (rejected — a non-technical user who
mistypes a number must still get their application); mutable overlay by name-matching
(rejected — see above); renaming `Changelog.md` back to `CHANGELOG.md` to make the stale
reference correct (rejected outright — the maintainer's canonical names are the contract, and
the reference was what was wrong).

— Decided by maintainer via drop `0.6.0-drop2-config-output-maintenance-foundation.md`,
implemented and recorded by Claude Code, 2026-08-03 (HOME-PC, Windows 11, repo venv
Python 3.12.10)

---

## 2026-08-02 — The Windows dark design system is APPROVED as the durable UI contract; tkinter/ttk stays; geometry, DPI awareness and live macOS are explicitly deferred

**Decision:** After reviewing the ten-image screenshot matrix, the maintainer **approved** the
v0.6.0 Drop 1 Windows UI prototype. What is approved is a *design contract*, not a release:
`version.py` remains `0.5.1`, no v0.6.0 exists, and nothing merged to `master` on approval.
The contract, which later plans must follow rather than re-litigate:

- **Centralized semantic tokens.** Windows colours, metrics and fonts live in
  `shared/ui_theme.py` and reach panels only through the theme bundle
  (`theme["colors"] / ["metrics"] / ["fonts"] / ["styles"]`) or `ui_theme.style_tk_widget()`
  for the classic Tk widgets ttk cannot style. **A panel may not declare a hex literal or a
  layout magic number.**
- **`ACT.*` namespaced style isolation.** `vista` stays the base theme; every style this
  project registers is prefixed `ACT.`; generic ttk styles are never created, reconfigured or
  re-laid-out; no `option_add` / `tk_setPalette` anywhere. Recolorable elements are cloned out
  of `clam` into the live theme because vista's native parts ignore colour options. ttk has no
  style inheritance, so an unconverted panel resolving the generic style is exactly what keeps
  it native — the isolation is structural, not a convention.
- **Converted surfaces are the launcher shell and the M4B Metadata Editor. Only those.**
  TTS Audiobook, M4B Converter, MP3 Tool, M4B Maker and Cover Image Resizer stay classic until
  Plan 9. Approval did **not** widen Plan 1's scope.
- **Shared Metadata is a visual treatment of behaviour that already exists.** It adds no
  per-book override, no precedence, no disabling. Decision 20B's full model still requires the
  Plan 6 workspace and the Plan 8 editor workflow.
- **Summary/Details is a presentation-only specimen** in a developer-only, launcher-unreachable
  fixture. No Plan 3 behaviour (filtering, dual log buffers, technical-log routing, job
  snapshots, ETA, Retry Failed, Pause/Resume) exists in the product.
- **Non-Windows behaviour is preserved and must stay preserved.** macOS `aqua`/Finder and the
  Linux/other `classic` fallback are byte-identical to the pre-drop `master` at the function
  level, and four automated tests hold that line.

**Approved evidence:** `files/UI-Prototype-Screenshots/v0.6.0-drop1/` — ten images, 1920×1080,
maximized, five states at true 100% and the same five at true 125% Windows display scaling,
captured at Phase 5 SHA **`b2e809fe4e25f5aaaef1684b5998bc652374de87`** on branch
`feature/0.6.0-drop1-windows-ui-prototype`. The 125% pass was captured on the secondary
1920×1080 display (the one set to 125%); the maintainer accepted it as valid evidence and
required no primary-monitor reshoot. The current specimen is accepted as sufficient — no
additional Details screenshot is to be added.

**Why tkinter/ttk remains acceptable (the question this drop existed to settle):** the hard
part — a genuinely modern dark UI without a toolkit switch — works. Cloning clam elements into
the live vista theme produced a fully colourable dark control set (buttons, entries,
comboboxes, spinboxes, checkbuttons, notebook tabs, scrollbars, Treeview, labelframes,
progressbars) while five panels kept byte-identical native rendering, proven by snapshot tests
across a whole application build. No image assets were needed to fake controls, no new runtime
dependency was added, and no per-machine hack was required. The two things ttk genuinely cannot
reach — the `Combobox` popdown and the window title bar — are narrow and separately solvable.
**Do not propose a toolkit change for the remaining conversion.**

**Geometry: deliberately unchanged.** `MIN_SIZE = (920, 600)` and
`DEFAULT_GEOMETRY = "1024x720"` stay as they are. The M4B Converter's primary action and Log
remain clipped at the 920×600 minimum (~19 px, and ~108 px bottom + 75 px right), identical at
both scaling levels. That panel is unconverted and Plan 9 will rebuild it, so widening the
application minimum on behalf of a layout that is about to change would be a theme-contract
change made for the wrong reason. The converted editor clips nothing at any size or scaling;
its long form is a deliberate scroll region at every size (plan §7.3 requires deliberate
scrolling, not zero scrolling), with the action bar and Log outside it. **Deferred to the
Plan 9 conversion of that panel.**

**DPI awareness: explicitly unresolved future work, and explicitly not a blocker.** The
application is DPI-**unaware** — `GetProcessDpiAwareness` returns `UNAWARE`, and neither the
venv's `python.exe`/`pythonw.exe` nor the base Python 3.12.10 they copy carries a `dpiAware`
manifest; `pythonw.exe` is what `Setup_and_Run` launches, so this is the real user path. At
125% Windows therefore bitmap-scales the whole window: text is soft rather than re-rendered at
120 DPI. The maintainer accepted this for Plan 1 **because the app remains usable and nothing
clips** — the same uniform scaling that softens the text is why the layout cannot break, and
the measured geometry at 1024×720 and 920×600 is byte-identical between the two passes. It is
recorded here as **unresolved Windows work for Plan 9 or an appropriately scoped future plan**,
not as finished behaviour. A fix means a manifest or a `SetProcessDpiAwareness` call at startup
**plus** a re-measure of every fixed pixel metric and fresh screenshot evidence; it was
deliberately not attempted during closeout.

**Live macOS: an approved deferral, never a pass.** No Mac was available across Phases 4–6, so
the v0.6.0 line has **not** been live-verified on macOS and must not be described as such. The
exact five-step smoke test is preserved in `handoff.md`. Automated aqua-branch coverage plus
the byte-identical non-Windows code paths are *evidence*, not a live pass. This deferral did
not block approval because the drop changes no non-Windows code path.

**Alternatives considered:** switching toolkits (rejected — the prototype proved ttk sufficient
and the cost is enormous); converting the other five panels now (rejected — approval
establishes the contract Plan 9 applies, and unconverted panels are what makes the isolation
claim testable); raising `MIN_SIZE` to clear the converter clipping now (rejected — see
Geometry); fixing DPI awareness during closeout (rejected — a production behaviour change would
invalidate the visual evidence just approved).

— Approved by maintainer (Elijah Matthew) 2026-08-02 after reviewing the ten-image matrix;
recorded by Claude Code, 2026-08-02

---

## 2026-07-19 — Batch-timing-parity rewrite implemented, measured, and ABANDONED by ear; the original chunk pipeline is the confirmed-preferred batch method

**Decision:** The Edge batch path stays on its original chunk pipeline
(`split_into_chunks` → one `edge_tts.Communicate` call per ~3000-char chunk →
`merge_mp3s` with a flat 50 ms chunk join), which honors only `speaker` and `rate` and
leaves all inter-sentence pacing to Edge's natural prosody. A full timing-parity
rewrite — batch delegating each file to `run_conversion_job` in a child subprocess
(thread-level delegation is unsafe: the engine's `os.chdir` is process-global, proven
to corrupt concurrent conversions), plus per-path registry presets
(`batch_timing_preset` overrides re-tuned so every non-Jenny voice matched its
old-batch median gap within −22…0 ms) — was fully implemented and measured across
all 7 Edge voices, hit its numeric targets almost exactly, and was then **abandoned
after the maintainer's manual A/B listening: it sounded subjectively worse than the
original batch method for every compared voice.** Do not blindly re-attempt this;
sentence-level pause insertion plus per-chunk silence trimming audibly changes the
speech character of a batch render in ways gap statistics do not capture. Any future
attempt must lead with ear-testing, not measurements, and should start from the
session records around this date (handoff work log, CHANGELOG notes).

**Why:** The maintainer compared old-vs-new batch renders of the same chapter for six
voices; despite median-gap parity, the new engine's output was consistently judged
worse by ear. Measured-identical cadence is not perceived-identical audio: the old
pipeline's single continuous synthesis per chunk preserves Edge's natural prosodic
flow across sentences, while per-sentence synthesis + trim + inserted silence does
not.

**Consequences:** Batch mode intentionally ignores the five GUI pause fields (they
apply to Edge single-file conversion only — documented in Briefing.md); Jenny's
`timing_preset` (sentence 750 / paragraph 800) affects single-file mode only. The
one surviving artifact of the effort is knowledge, recorded here.

— Decided by maintainer (Elijah Matthew) after A/B listening, implemented-and-reverted
by Claude Code, 2026-07-19

## 2026-07-08 — AI-WORKSPACE.md and files/vibe-coding-templates/ are excluded from version control

**Decision:** Neither `AI-WORKSPACE.md` nor `files/vibe-coding-templates/` is tracked in git,
effective this session. Both are listed in `.gitignore`. `AI-WORKSPACE.md` stays on disk as the
authoritative *local* reference for this machine's conventions (including the HOME-MacOS
section), but is never committed. `files/vibe-coding-templates/` is permanently removed from the
tree and is not referenced in any doc.

**Why:** Privacy — `AI-WORKSPACE.md` contains private machine/workspace details that should not
be published to the public GitHub repo; the vibe-coding-templates were workspace scaffolding
with no role in the shipped tool. Upstream commits that delete `AI-WORKSPACE.md` (e.g.
`9c89479`) are therefore correct and must not be reverted.

**Alternatives considered:** committing a redacted `AI-WORKSPACE.md` (rejected — the file's
value is the private local detail; a redacted copy adds maintenance for no benefit); keeping the
templates as dev-only reference (rejected — they duplicate the workspace tooling that lives
outside the repo).

— Decided by maintainer (Elijah Matthew), recorded by Claude Code, 2026-07-08

---

## 2026-07-08 — Shared progress widget lives in ui_theme.py; M4B Maker progress is deliberately indeterminate

**Decision:** Per-tool run progress is one shared class,
`shared.ui_theme.ProgressIndicator` (ttk.Progressbar + counter/percentage label,
main-thread-only `update / set_indeterminate / reset / finish` API), placed in
`ui_theme.py` — **not** in `launcher.py` — and rendered inside each tool's own
layout near its action buttons/status area. Updates are marshaled exclusively
through each tool's existing worker queue (`("progress", (done, total))` /
`("progress_ind", text)` payloads) and applied only in the main-thread drain,
the same channel that feeds each Log box. Determinate wherever a real total
exists (M4B Converter / Cover Image / M4B Metadata per file, MP3 Tool per
track/file, TTS per batch file / Kokoro chunk / Edge paragraph). The **M4B Maker
build is deliberately indeterminate**: it is a single ffmpeg concat/encode with
no observable sub-steps, so the bar animates while working and shows 1/1 on
success rather than faking a percentage. Do not "fix" the Maker to determinate
without a real progress source.

**Why:** `ui_theme.py` is the shared UI module every tool already imports, and
tools also run standalone via their own `main()` while `launcher.py` imports
the tools — placing the widget in the launcher would invert that dependency.
Inventing Maker percentages (e.g. ticking on log lines) would display made-up
numbers; the drop explicitly prefers an honest indeterminate bar.

**Alternatives considered:** launcher-owned status-bar progress (rejected —
tools must work standalone, and per-tool placement keeps the bar next to the
action it describes); parsing ffmpeg `-progress` output for a real Maker
percentage (viable future improvement, but new subprocess plumbing — out of
this drop's scope).

— Decided and implemented by Claude Code per drop
`0.5.0-ux-progress-and-metadata-layout.md`, 2026-07-08

---

## 2026-07-08 — Panel wheel scrolling: crossing events on the wrap frame + Tcl-level NotifyInferior guard

**Decision:** Scroll-on-hover for canvas-based panels is provided by
`shared.ui_theme.enable_mousewheel(scroll_target, hover_region)`: `<Enter>` on the
hover region installs a `bind_all("<MouseWheel>")` handler, `<Leave>` removes it —
but a Leave whose crossing detail is `NotifyInferior` (the pointer merely moved into
a CHILD widget, still inside the region) is ignored. The Leave side is deliberately
bound **at the Tcl level** (`widget.tk.call("bind", …, "+cmd %d")`), not via
`widget.bind()`, because tkinter's event substitution has no `%d` — `event.detail`
does not exist on Python-level events (verified live on Tk 9.0.3), so a pure-tkinter
guard silently never fires. Do not "simplify" this back to a tkinter-level bind.

**Why:** The TTS options canvas is fully covered by its form frame, so the old
Enter/Leave-on-the-canvas wiring never armed the wheel handler in normal use
(wheel/trackpad scrolling simply did nothing, on Windows too). Binding on the wrap
frame arms it anywhere over the panel; without the inferior-guard the binding tears
down the moment the pointer touches any child control, which is the same bug again.

**Alternatives considered:** binding `<MouseWheel>` recursively on every descendant
(fragile — widgets created later are missed); `winfo_containing` hit-testing on every
Leave (heavier, same result); Button-4/5 bindings (X11-only, irrelevant on
macOS/Windows). Listbox/Text widgets in the other tools scroll natively via Tk class
bindings and intentionally do not use the helper.

— Implemented by Claude Code per maintainer instruction, 2026-07-08

---

## 2026-07-08 — macOS launcher uses the native aqua theme, not a Finder-styled clam

**Decision:** On macOS the launcher applies ttk's native `aqua` theme (with a
`TclError` fallback to the classic clam look for Tk builds without aqua). The
Finder-style chrome — tinted source-list sidebar, hover/selection rows, toolbar,
content card — is built from **classic tk widgets** colored via macOS *semantic*
system colors resolved at runtime in `shared/ui_theme.py`; all six tool panels keep
native aqua ttk controls. Windows/other platforms take the classic branch, which
reproduces the pre-v0.5.0 look byte-for-byte.

**Why (both tested live on this Mac, Tk 9.0.3, dark mode):** aqua gives real native
controls in every tool panel and automatic light/dark adaptation for free, which a
Finder-styled clam would have to fake and maintain by hand. aqua's one limit — it
ignores background styling on native-drawn ttk widgets — is confined to the launcher
chrome, hence the classic-tk sidebar. Fonts use the `.AppleSystemUIFont` alias for
San Francisco (SF Pro Text/Display are NOT installed font families on macOS 26);
alpha-based semantic colors flatten through `winfo_rgb`, so secondary/hover/separator
shades are computed blends instead.

**Alternatives considered:** Finder-styled `clam` everywhere (rejected: non-native
controls in all six panels, manual dark-mode); PyObjC/AppKit for true vibrancy
(rejected per drop constraint — no heavy deps for a visual effect; flagged as an
optional future decision).

— Decided and implemented by Claude Code per drop `0.5.0-macos-ui-shell.md`, 2026-07-08

---

## 2026-07-07 — macOS venv must be built on Python 3.12 for Kokoro; 3.13+ is a degraded fallback only

**Decision:** Kokoro's PyPI wheels require Python >=3.10,<3.13, so the venv base on macOS
must be 3.12 (the `PREFERRED_PY` sweet spot). `bootstrap.py` now enforces this in two
places: (1) `run_setup` no longer accepts a >=3.13 interpreter as-found — it first calls
`install_python` (brew `python@3.12` + `python-tk@3.12`) and only keeps the newer
interpreter if 3.12 truly cannot be installed; (2) `_create_validated_venv` detects an
existing venv built on >=3.13 and rebuilds it once a Kokoro-compatible (<3.13) base is
available, closing the "3.13 venv is reused forever" gap. Python 3.13+ is accepted only
as a degraded fallback: Edge TTS works, Kokoro voices are disabled (the requirements
marker `kokoro==0.9.4 ; python_version < "3.13"` skips the wheel, and the self-heal
repair cannot install it either). The compatibility range lives in one helper,
`_is_kokoro_compatible`.

**Why:** A live Mac run (2026-07-07, only Homebrew python3.13 present) built the venv on
3.13.7; every launch-time Kokoro self-heal then failed with "No matching distribution
found for kokoro==0.9.4" — an environmental failure, unfixable from `kokoro_synth.py`.
The old flow only ran `install_python` when NO interpreter was found at all, so a
3.13-only Mac never attempted the 3.12 install, and the fast path reused the bad venv
forever.

**Alternatives considered:** pinning a newer Kokoro that supports 3.13 (none exists —
the newest 3.13-compatible release on PyPI is 0.7.16, an older API); fixing inside
`kokoro_synth.py` (rejected — the package can never be installed on 3.13, so no
synth-side change helps). The Windows path is unaffected: it selects `py -3.12`
directly and never enters these branches.

— Root-caused and implemented by Claude Code per maintainer instruction, 2026-07-07

---

## 2026-07-07 — Kokoro pause fields: paragraph maps to the inter-chunk gap; full parity deferred

**Decision:** For Kokoro voices, the GUI's "After each paragraph block" field drives
`kokoro_file_to_mp3(chunk_pause_ms=…)` (the silence appended after every ~3000-char
synthesis chunk) and "End of recording" drives `end_silence_ms`. The Between-sentences,
After-title, and Before-chapter fields intentionally do **nothing** on Kokoro voices.
Full per-sentence/title/chapter parity requires sentence-level synthesis inside
`kokoro_synth` (Edge gets it from per-sentence clips) — that is a deliberate deferral to
its own future drop and needs maintainer sign-off to expand. Do not "fix" the missing
parity piecemeal in a bug hunt.

**Why:** The Drop 3 plan scoped Kokoro timing to paragraph + end pause to keep the drop
tractable and avoid a synth rewrite. Kokoro chunks are split on ~3000-char sentence
boundaries, not paragraphs, so the mapping is approximate by design.

**Alternatives considered:** sentence-tokenizing inside kokoro_synth (a rewrite — its own
drop); leaving all pause fields dead on Kokoro (rejected — silently ignoring visible GUI
fields is worse than an approximate mapping).

— Decided by maintainer via drop `drop3-plan`, implemented by Claude Code, 2026-07-07

---

## 2026-07-07 — No AI co-author trailers in commit messages, ever

**Decision:** All commits on this repo are authored solely by the maintainer. Commit
messages are plain text with **no trailers of any kind** — in particular, never a
`Co-Authored-By: Claude ...` (or any Claude/Anthropic co-author) line. Claude appears
only in whatever tooling/log metadata arises naturally, never as an author or co-author.

**Why:** Maintainer is the sole author and sole committer on this repo (stated
2026-07-07 when a co-author trailer was about to be added to the Drop 1 commit).
Applies to Drops 2–5 and all future work — future sessions must not add the trailer
by default.

— Decided by maintainer (Elijah Matthew), recorded by Claude Code, 2026-07-07

---

## 2026-07-06 — One commit per drop for the entire v0.5.0 sequence (not per phase)

**Decision:** For all of v0.5.0 — Drop 1 (restructure), Drop 2 (metadata), Drop 3 (TTS),
Drop 4 (script hardening), and the final UI drop — work through every phase of a drop
back-to-back with **no git commits per phase**. Checkpoint progress only via
`md-instructions/handoff.md` (work log) and the session task list. When a drop's final
bug-hunt/verify phase is fully green, stop and present a final summary; the maintainer
reviews and then a **single commit covering the whole drop** is made, followed by a
maintainer-triggered push/force-push. The agent never pushes.

**Why:** Maintainer wants to review + force-push each drop as a single unit. This
overrides the AI-WORKSPACE.md default of committing after each completed phase for the
rest of the v0.5.0 line — future sessions must not default back to per-phase commits.

— Decided by maintainer (Elijah Matthew), recorded by Claude Code

---

## 2026-07-06 — Runtime-writable data lives in `files/runtime-data/` + `files/bin/`

**Decision:** All state the app writes at runtime goes under `files/`: session/setup/launch
logs in `files/runtime-data/logs/`, persisted settings at `files/runtime-data/settings.json`,
the ~300 MB Kokoro HuggingFace cache at `files/runtime-data/models/huggingface/`, and the
portable-ffmpeg fallback in `files/bin/`. All gitignored. `shared/paths.py` keeps the
`RESOURCES_DIR` name pointing at `files/runtime-data/` so the code diff stayed minimal.

**Why:** Maintainer ruled out `scripts/resources/` and OS user-data dirs (Q4): keeping
everything in-tree preserves the "delete the folder to fully uninstall" property; `files/`
is the AI-WORKSPACE home for non-script assets. Alternatives: `%APPDATA%`-style dirs
(rejected — scatters state, breaks portable uninstall).

— Decided by maintainer (layout details by Claude Code), 2026-07-06

---

## 2026-07-06 — Restructured to the AI-WORKSPACE standard layout (v0.5.0 Drop 1)

**Decision:** Unified the two mirrored per-OS root trees into
`scripts/{Universal,Windows,MacOS}` + dev-only `files/` + one `md-instructions/` set, venv at
the repo root, launchers renamed to `Setup_and_Run-audiobook-creation-tool.*`.

**Why:** The mirrored trees had to be kept byte-identical by hand and duplicated every doc —
pure drift risk with zero benefit (Phase-0 diffs proved the trees identical). Alternatives:
keep mirrored trees (rejected — drift, double docs). Consequences: all imports/paths rewired
once; future OS work goes in `Universal/` unless truly platform-specific.

— Decided by maintainer via drop 0.5.0-drop1, implemented by Claude Code

---

## 2026-07-06 — Almost everything lives in `scripts/Universal/`

**Decision:** The entire application is cross-platform code in `Universal/`;
`scripts/Windows/` and `scripts/MacOS/` are empty (.gitkeep) by design.

**Why:** The two per-OS `scripts/` trees were byte-identical except two unused legacy files
(`mp3_tools_launcher.py`, `tts/setup_env.py` — deleted, maintainer Q2); platform differences
are `sys.platform` branches inside shared code and stay that way. Consequence: a file only
moves out of `Universal/` when it genuinely cannot be shared.

— Decided by maintainer via drop 0.5.0-drop1, implemented by Claude Code

---

## 2026-07-06 — Version 0.5.0, not 0.3.x

**Decision:** This restructure line is **v0.5.0**.

**Why:** v0.3.1 is tagged and v0.4.0 released; a MINOR bump keeps linear history honest.
Alternatives: 0.3.2 (behind already-released history), 1.0.0 (deferred for a stability
milestone).

— Decided by maintainer via drop 0.5.0-drop1

---

## 2026-07-06 — `verify.py` adopted as the mechanical gate

**Decision:** `scripts/verify.py` (from the workspace `verify-template.py`) must print
`RESULT: PASS` before any drop is considered done: pytest suite in `files/tests/` (fails on
"no tests collected"), every dependency `==`-pinned, permanent docs de-templated.

**Why:** No mechanical pass/fail gate existed; releases relied on manual checklists.
Consequence: every phase/drop now ends with the same objective check.

— Decided by maintainer via drop 0.5.0-drop1, implemented by Claude Code
