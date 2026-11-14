# ACT v0.8.0 — Windows release acceptance (maintainer exception)

2026-11-14, HOME-PC. Branch `feature/0.8.0-omnivoice-integration`, accepted head
`ee426fdec135c41f93ce5500ce04c448a8671d72`; base `origin/master` `dbf38f7a06200f2a684753ef72fb701a597ac5ea`
(v0.7.3). Identity 0.8.0 (`scripts/shared/version.py`, `config.toml`). Platform: **Windows only**.

This record keeps three things apart: what was **tested**, what the owner **accepted** without a test, and what is
**not qualified**. The release-documentation commit that adds this file changes no program code, model file,
dependency pin or approved asset; it changes the README, the README assertions of `files/tests/test_long_paths.py`
(and that test's one renamed id in `coverage.json`) and the documents.

## Owner decision (2026-11-14)

The owner explicitly approved:

- acceptance of the combined Windows verification evidence below as sufficient for the Windows v0.8.0 release;
- **no** additional canonical full-gate run;
- integration into `master`, building and auditing the Windows ZIP, the `v0.8.0` tag and the GitHub release;
- deferring macOS compatibility and release work to a separate session (macOS v0.8.0 is not supported or published).

This is an explicit **maintainer release exception** to the earlier requirements of a passing full gate on the final
tree and an external Windows qualification before release. **It does not change the recorded result of the original
full gate: that run FAILED and stays a FAIL.** Its passing stages, together with the passing focused checks of the
F1–F5 remediation, are what the owner accepted.

## Tested: the one canonical full gate (FAIL)

Run `files/dev-work/verification-gate/outputs/2026-11-14_113416_full_c8e8` (ignored evidence, kept unchanged):
mode `full`, HEAD `c583d78abef3e300a5a4ef9be9d02bb0b2dcc697`, tree `fd9819be…e035e1e` unchanged during the run,
7,094 s, **exit 1, FAIL**.

- Tests: 16,009 expected, collected and executed; **15,942 passed** (15,410 ordinary; guarded `v3-planning` 457 and
  `v3-supervisor` 75), **2 failed**, 65 skipped, 0 errors, 0 xfail/xpass, 0 deselected.
- Native journeys: **54 of 56 passed**.
- Passing checks: policy, source identity, guarded specification, interpreter, process ownership, error mode,
  partition (15,477 ordinary + 532 guarded over all 293 modules), guarded (both groups), dependencies (all `==`-pinned;
  170 locked packages by SHA-256), docs, document names, config (version 0.8.0, Windows), cleanup, error mode held,
  inventory, coverage (266 of 266 required entries mapped; release-pending: owner 21, qualification 28), self-tests,
  tree.
- Failing checks (all verification pins that predated v0.8.0's additions; no product defect was found):
  acceptance (F1), pytest (F2, F3), skips (F4), coverage-inventory (F5).

## Tested: the F1–F5 remediation (commit `ee426fd`, focused only)

`ee426fd` changed only the gate and tests (`test_base_packages.py`, `test_cancel_semantics.py`, `verification.json`,
`coverage.json`, `journeys/setup.py`, `adapters/windows/setup_launcher.py`) and the documents; nothing under
`scripts/`.

- F1: the setup journeys expect the five approved first-run choices (OmniVoice fifth, off) and take the path limits
  from the copy's own `bootstrap.app_path_limits()`.
- F2: the pip guard allows exactly one literal outside the policy modules, `shared/long_paths.py::_pip_command`, and a
  new test pins that probe whole.
- F3: the cancel guard names the four local routes (OmniVoice the fourth).
- F4: the OmniVoice real-clone opt-in skip has its own exact rule, budget 1.
- F5: 17 bare parametrized ids replaced by all 83 collected parameter ids.

Focused evidence (both runs on HEAD `c583d78` with the F1–F5 changes in the working tree, before they were committed
as `ee426fd`):

| Run / check | Result |
|---|---|
| Focused gate `2026-11-14_143108_focused_ecef` (the two failed tests, the new pin, controls, 2 setup journeys) | PASS, 46 s; 71 passed, 0 failed, 0 skipped; journeys 2 of 2 |
| Focused gate `2026-11-14_143511_focused_0da8` (25 document and tree readers) | PASS, 487 s; 1,866 passed (1,856 + 10 guarded), 0 failed, 0 skipped |
| Coverage-inventory computed as the full gate does, on an exact collection (16,010 ids) | 0 problems, 0 dead ids; control on `c583d78`'s `coverage.json` gives exactly the 17 |
| The failed run's 65 skips replayed through the gate's judge | old policy reproduces the failure, new policy none; 5 negative controls refused |
| Mutation controls on a private copy | no-change control 4 of 4; 17 mutants each failed by their named test |

Not rerun after `ee426fd`, by the owner's decision: the full gate, the ordinary suite as a whole, the 54 passing
journeys, the guarded groups and the other passing stages. Their PASS is `c8e8`'s evidence for `c583d78`; the
owner accepts it together with the focused checks above. `--status --require-current` on `c8e8` describes
`c583d78`'s tree and is not current acceptance.

## Tested: the independent review and its remediation

Codex's independent review of `feca89f` (`files/dev-work/act080-independent-feca89f-20261114/Independent-Review.md`,
ignored, kept unchanged) **failed** three findings, all remediated in `c583d78` with positive and negative controls:

- R1: OmniVoice startup-import failures (a native library Windows refuses, an `OSError`) are classified as `import`,
  so the engine is recorded as damaged and repair is offered; memory, Smart App Control and the network guard are not.
- R2: every Windows path length is counted in UTF-16 units by `shared.long_paths.windows_length`; limits unchanged.
- R3: the long-path tests never write outside their own scratch.

`c583d78` is the commit the full gate above ran on. No further Codex review was requested.

## Accepted by the owner (not a test)

- **Listening:** the owner approved all **12 OmniVoice listening tracks** (two per voice), by the owner's statement of
  2026-11-14. No agent wrote a verdict; nothing about the tracks, references, transcripts or tuning was changed.
- **The combined evidence above** as sufficient for the Windows release, without a passing full gate on the final tree
  and without the external Windows qualification.

## Real installations (HOME-PC only, disposable copies)

A cold install of all five components (on `8e4caa5`), the unified-layout migration and the recovery scenarios ran on
HOME-PC in disposable copies (2026-11-13); scenario 9 (both engines rebuilt after `.venv` was removed) was completed
on the final program code on 2026-11-14, with a bounded narration from every engine family. HOME-PC has Windows long
paths switched on; the app was installed for real in folders of 89 and 102 characters.

## Not qualified (open for v0.8.0)

- Setup's long-path switch-on, for real, on a computer where the setting is off: Windows' administrator (UAC)
  prompt approved and declined, the "restart Windows" path, a standard (non-administrator) account and a managed
  computer whose policy blocks or reverts the change. Tested only with the Windows setting simulated.
- A real installation with long paths off, and in a folder exactly at one of the enforced limits (87/123 for the
  app, 83/119 with OmniVoice).
- Windows 10, any computer other than HOME-PC (Windows 11), and display scaling other than 100%.
- OmniVoice on any GPU other than the RTX 5070 tested; it requires an NVIDIA GPU and does not run on the CPU. Two
  copies of the app running Qwen3 and OmniVoice on one GPU at the same time are not prevented.
- The first-run window with all five components chosen from start to end on the final program code, and the real
  downloads of the models, the OmniVoice wheels and the app's own Python, packages and FFmpeg on that code (the code
  that fetches them is unchanged since `8e4caa5`, where they ran).
- macOS: v0.8.0 is not supported, packaged or published. Linux is not qualified.

## Licensing disclosed with the release

OmniVoice model weights are **CC-BY-NC (non-commercial)**; the OmniVoice code is Apache-2.0; the required audio
tokenizer is under the **Boson Higgs Audio 2 Community License** (based on the Meta Llama 3 Community License: the
Llama 3 Acceptable Use Policy applies, outputs may not improve another large language model, more than 100,000
annual active users needs an expanded licence; attribution required). The app never ships the weights or the
tokenizer; a user's own installation downloads them from one pinned revision. The application itself is GPL-3.0.

## Release-documentation checks (this checkpoint, focused only)

`files/tests/test_long_paths.py`, `test_release_packaging.py` and `test_epub_retirement.py` over the release README:
419 passed. Negative controls for the changed README assertions: four README mutations each failed the intended test,
the unchanged control passed, and the README was restored byte for byte. The document readers and the coverage
inventory were run on the final documents (see the Handoff). No full gate, journey suite, qualification, installation
or model load was run.

## Integration, archive and publication

Performed after the commit that adds this file, by fast-forward of `master` (no rebase, squash or force), with the
unchanged packager `scripts/shared/release.py` building `dist/AudiobookTool-Windows-v0.8.0.zip` from that exact
committed source. The resulting `master` commit, the `v0.8.0` tag, the archive's SHA-256 and size and the GitHub
release URL are recorded in the Handoff's closeout block and the GitHub release notes; this document does not claim
them.
