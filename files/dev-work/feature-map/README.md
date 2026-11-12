# ACT feature map

What the Audiobook Creation Tool does, tool by tool, written for the owner and for any agent that changes the application. Built in v0.7.2 Phase 4 from the source, the live widget trees of a running instance, the registered journeys and the existing tests.

**One inventory.** `files/dev-work/verification-gate/coverage.json` is the only machine-readable record of features, their source, their contracts and how each is verified. These documents explain the features in prose and name each by its stable id in backticks. They hold no test ids and no mapping table, so nothing here can drift from the inventory. To see how a feature is verified, look its id up in `coverage.json`, or run `verify.py --mode focused --feature <id>`.

## The documents

| Document | Covers |
|---|---|
| `README.md` | This index, how the inventory is kept honest, and the verification gate's own features (`ACT.GATE.*`) |
| `tts-audiobook.md` | TTS Audiobook: sources, voices and engines, Edge narration, local engines and their setup, publication, Cancel, Pause, Retry |
| `mp3-tool.md` | MP3 Tool: Books, tracks, shared and per-Book metadata, Write ID3 Tags, Combine, artwork, numbering |
| `m4b-converter.md` | M4B Converter: whole book or by chapter, metadata modes, quality, decoding routes, naming and collisions |
| `m4b-maker.md` | M4B Maker: Books, ordering, chapters, metadata, artwork, Build M4B(s), naming and destinations |
| `m4b-metadata-editor.md` | M4B Metadata Editor: Save Tags, Clear All Tags (keep chapters), Remove Series Numbering, chapter titles, artwork |
| `cover-image.md` | Cover Image: browsing, size, crop or letterbox, numbered copies or replacement, corrupt inputs |
| `consistency-matrix.md` | The six tools side by side where a person expects them to behave alike, and the differences left for the owner (v0.7.2 Phase 6) |
| `shared-workflows.md` | The launcher, the shared job, log, import, Book and output machinery, settings, appearance, Preferences, and installation, launch, repair and optional assets |

## How the inventory is kept honest

The gate holds `coverage.json` to account in every full and changed run, and `files/tests/test_verification_coverage.py` runs the same check on every changed run. Each of these stops a clean run until someone has reviewed the mapping:

- **A new control, dialog, binding or tool.** Static discovery (`helpers/surface_discovery.py`) reads every application file the suite's registry names. It finds each control a file builds directly, each standard dialog it raises, each event it binds and each tool the launcher registers. Live discovery (the `inventory.live-surfaces` journey) opens a real isolated instance and reads every interactive widget of the shell, the six tools, Preferences & Data, and each speech engine chosen in the TTS voice list. Each finding must be in the reviewed index (`surfaces` in `coverage.json`) and mapped to a feature. A control nobody mapped fails, and so does an indexed control that is no longer there.
- **A changed source file.** Every application source file, and the two `Setup_and_Run` launchers, carries a review stamp: the digest the file had when its features were last reviewed. A change, a new file, a removed file, or a file no feature names fails until the features are reviewed and the file is restamped.
- **A dead reference.** A deleted or renamed test is seen at once from the test source, and a full run also checks every test id against its exact collection. A dead scenario or journey, a symbol that no longer exists, an id this inventory does not have (in the surface index, the issue ledger or any of these documents), and a registered journey that no feature maps are all refused.
- **A weakened requirement.** An exception needs the owner's approval and must cite where it was given; none exists. A `planned` gap must name an open issue in the ledger and a phase after the last one completed against the inventory (5 since v0.7.2 Phase 5). None is left since v0.7.2 Phase 8. A unit test cannot stand in for native or real-media evidence. The policy pin `coverage.require_reviewed_inventory` is itself tested.

The negative controls that prove each detection are in `test_verification_coverage.py`, `test_surface_discovery.py` and `test_verification_gate_contract.py`, and on a real running instance in the `control.unmapped-live-control-is-caught` journey.

## Four measures, kept apart

1. **Inventoried and reviewed.** The features registered, with every discovered surface and source file accounted for. This says the inventory is complete as far as discovery can see. It does not say anything works.
2. **Mapped.** A required feature has at least one routine verification: an exact test, or a registered journey that gives native, real-media, control or discovery evidence. A 100% figure here proves only that the registered entries have targets.
3. **Satisfied.** Every routine verification of a required feature passed in this run. Only a full run is held to all of them. Release-pending evidence is never satisfied by a routine run, so `release_ready` stays false: `qualification` (real Edge online, real local engines, fresh Windows, 1,000-plus chapters), `owner` (listening, visual baselines, display scaling) and `planned` (a known gap, tied to an issue and a later phase).
4. **Line coverage.** Optional, and not collected.

Each full run writes all four to `coverage-report.md` and `results.json`.

## Keeping it current

When you change application source:

1. Run `python files/dev-work/verification-gate/helpers/inventory.py check`. It names what moved: changed files and the features they serve, new or vanished surfaces, and dead ids.
2. Review those features' entries in `coverage.json` (source symbols, contracts, verification) and their sections in these documents. Map any new surface to a feature, and add a feature when it is a new capability.
3. Restamp only the files you reviewed: `python files/dev-work/verification-gate/helpers/inventory.py restamp <path> ...`. Nothing restamps wholesale.
4. Run the affected tests: `verify.py --mode focused --feature <id>`, then a changed run.

A new journey is added to `verification.json` and mapped by at least one feature, or the gate refuses it. A new live control appears in `surfaces.live` after review: run `inventory.live-surfaces` and map what it reports.

## The verification gate's own features

The gate is development tooling under `files/dev-work/verification-gate/` and is never shipped. It has to be trustworthy for any of the other features' verification to mean something, so its own guarantees are inventoried too.

### The canonical gate

`ACT.GATE.RUNNER`

`verify.py` is the one developer gate, with four modes: focused, changed, full and qualification. Every invocation reserves its own run directory under `outputs/`, writes a start marker, and finalizes `results.json` only after every child has exited and its records have been reconciled. A run that executed nothing, whose exit code and reports disagree, or whose tree changed while it ran is never PASS. A later `--status` read rejects evidence that was copied, edited or made stale by a source change. A qualification scenario is sealed PASS only when its own verdict bears that out (this scenario, its runner exited 0, at least one run, every check passed) and the whole scenario is there (its identity names the run's HEAD, its runs are recorded, and every check `verification.json` requires of that scenario's PASS is present); anything else the gate itself seals FAIL, and the reader derives the same from the sealed evidence (v0.7.2 Phase 9, ACT72-072). The m4b-scaling harness reads what the application stages exactly, before every removal, rename, truncation and writing-open, held to Windows' own report of the output base, and judges T5 as frozen: the exact peak total no higher than the seeking route's (ACT72-073).

### Selection

`ACT.GATE.SELECTION`

A focused run takes exact test ids, stable feature ids (which select the feature's modules and its exact tests) and journey ids. An unknown one is an invalid invocation. A changed run maps each changed path to tests through policy routes, a word match of the module name in test source, and the features whose source changed. A path it cannot trace widens the run to everything. A changed run is never full acceptance.

### Guarded suites

`ACT.GATE.GUARDED`

The optional-setup v3 suites run under `files/tests/guarded_pytest.py`, each exactly once and never in the ordinary run. The process, network and write policy holds for the life of the process, and a guard finding fails the group even when its tests passed.

### Real input and the observation channel

`ACT.GATE.NATIVE-INPUT`

Journeys drive the real application with real Windows mouse and keyboard input. Input goes only to the owned process's foreground window, at a target the pointer is shown to hit. A lost foreground, a covered or disabled target, a dead input path or another desktop blocks rather than passes, and a lease keeps two runs from sharing the desktop. The test-only observation channel reports widget identity, geometry and state on the Tk main thread. It has no operation that calls application code.

### Judging journey reports

`ACT.GATE.ACCEPTANCE-REPORT`

The gate judges each journey from its evidence, never from the runner's word. A native claim needs real input and an action log. A media claim needs validated fixtures and inspected outputs. A status that contradicts its own checks, a copied report or a missing screenshot fails. A scenario cannot appear or vanish without a policy edit, and each of the six tools needs a complete journey.

### Shutdown negative controls

`ACT.GATE.SHUTDOWN-CONTROLS`

Three journeys prove the shutdown journeys could fail:

- taking away the application's own hold on its Tk root lets the forced collection's crash be seen;
- removing the media-child stop lets the orphan FFmpeg be seen;
- the forced landing without the fix crashes.

A shutdown journey cannot pass on an unclean exit.

### Media fixtures and the output oracle

`ACT.GATE.MEDIA-ORACLE`

Fixtures are real, deterministic media, built with the pinned FFmpeg and validated before any application sees them. The oracle decodes every sample. It compares intervals against the independently decoded source, and catches truncation, duplication, an attenuated first frame, wrong chapter content, titles, tags and artwork, and an input-side seek, none of which a duration check can see.

### Containment

`ACT.GATE.CONTAINMENT`

Every journey's application is born at Low integrity, so Windows itself refuses it write access to the owner's state, including the file-dialog history. A preflight proves that before any scenario runs, or nothing runs, and a run that added to the history fails.

### Owned scratch

`ACT.GATE.SCRATCH`

A run's disposable scratch lives in `%TEMP%\act-gate` under the owner's conditions (`Decisions.md`). A child folder is disposable only when its owner process has ended and its run names it. A failing test's folder is copied into the run's evidence, and the audit changes nothing.

### Visual baselines

`ACT.GATE.VISUAL-BASELINES`

Journeys capture candidate pictures of the application's own windows. A run lists candidates and never writes or approves a baseline. A baseline that was not approved by the owner stops the run. None is approved yet.

### This inventory

`ACT.GATE.COVERAGE-INVENTORY`

The inventory itself and the checks above: static and live discovery, the review stamps, dead-reference and dangling-id detection, the release-pending kinds, the four measures, and the `restamp` tool that records a review by name only.

## What this map does not establish

- Anything about macOS. Native macOS has not been reviewed live or qualified.
- Windows display scaling other than 100%. HOME-PC runs at 96 DPI, and changing that is a system change.
- Real Microsoft Edge speech. The routine journeys replay real MP3 frames at the service boundary. Real Edge is the `edge-low-memory` qualification.
- Real synthesis on Kokoro, Chatterbox Turbo or Qwen3-TTS (the `optional-engines` qualification), a fresh Windows (`fresh-windows`), or 1,000-plus chapter scaling (`m4b-scaling`). Each is a runner under `verification-gate/` since v0.7.2 Phase 8, run by name and never by a routine mode; a result is for that scenario, this machine and that commit only.
- Listening quality, which only the owner can judge.
- The contents of every dialog. Static discovery indexes each dialog at the place the code raises it. Live discovery opens Preferences & Data, but not every error and confirmation box.
