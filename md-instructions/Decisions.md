# Audiobook Creation Tool — Decisions (ADR log)

Append-only. Newest entries on top. Each entry: date, decision, why, signed by whoever made it.

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
