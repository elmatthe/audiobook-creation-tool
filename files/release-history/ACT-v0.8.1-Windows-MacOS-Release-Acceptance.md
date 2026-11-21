# ACT v0.8.1 — Windows and macOS release acceptance (maintainer exception)

2026-11-20, HOME-PC (Windows 11). Branch `0.8.1`, independently reviewed candidate
`f7a0b51e697cf71cf8d51887ed548a10908918ec`; integration branch `master`. Identity 0.8.1
(`scripts/shared/version.py`, `config.toml`, platforms Windows and MacOS, `developer_mode = false`).

This is a **historical record, not a new verification claim**. It keeps three things apart: what was **tested**, what
the owner **accepted** without a further test, and what is **not qualified**. The release-preparation commit that adds
this file changes no program code, model file, dependency pin, voice, reference recording or approved asset: it changes
the README, the one README-pin test (`files/tests/test_long_paths.py`) and the Changelog and Handoff. The executable
`scripts/` tree is byte-identical to the reviewed candidate (tree `4388fda9b9f9c6af7927d8b139c95d5bf5d02459`).

## Owner decision (2026-11-20)

The owner explicitly approved:

- acceptance of the combined evidence below as sufficient for v0.8.1;
- **no** second canonical Full gate;
- fast-forward integration of `0.8.1` into `master` and building and auditing both release archives
  (`AudiobookTool-Windows-v0.8.1.zip`, `AudiobookTool-MacOS-v0.8.1.zip`) from the same committed source.

Tagging and GitHub publication are separate steps and were **not** part of that decision. This is an explicit
**maintainer release exception** to the requirement of a passing Full gate on the final tree. **It does not change the
recorded result of the historical Full gate: that run FAILED and stays a FAIL. No passing final canonical Full gate
exists for v0.8.1.**

## Tested: the one historical Windows Full gate (FAIL)

Run `2026-11-20_164951_full_2cf1` (ignored evidence, kept unchanged): mode `full`, commit
`00ae6252569eec3b4d8ec921d67c8ab852d98bfd`, 6,190 s, **FAIL**.

- Collection was clean (17,318 tests executed) and both guarded groups passed.
- **Native acceptance journeys: 56 of 56 passed.**
- The failures were **30 failed tests, 1 teardown error, 229 skips that the skip policy did not name, and 2 coverage
  entries** (`ACT.SHARED.BUTTON-ROLES`, `ACT.SETUP.APP-PYTHON`). Attribution by isolated reruns on earlier commits:
  stale Aqua layout pins and a missing macOS standing after the button-role work; macOS-merge tests that assumed
  macOS (`fcntl`, process-id, timing, version pin, voice-preview README wording); a Windows symbolic-link privilege
  (WinError 1314); and an order-dependent test-isolation hazard. **No product defect was identified.**

## Tested: the F1 and F2 remediation (tests, dev tool and gate metadata only)

- `0040284` (F1) and `cce0591` (F2) changed no file under `scripts/`: Aqua layout pins through one helper, the macOS
  standing and owner check for the button roles, exact Windows skip rules, platform-correct macOS tests, a hermetic
  stage-zero Tk test, the voice-preview README renderer matching the owner's table (an `Availability` column and six
  display-only OmniVoice `To Be Added` rows), and a real-link test that skips only on WinError 1314.
- Subsequent targeted verification reported, for the original 30 failed tests, **18 passes, 12 Windows skips and zero
  failures**. The skips are **not** passes.
- The original teardown trigger (two `.pyc` files first written under the bundled Python's `__pycache__` during the
  run) **was not reproduced again**.

## Tested: the independent Codex review and its remediation

The independent review (`files/dev-work/v0.8.1-independent-codex/review.md`, ignored, kept unchanged) first **failed**
three material findings, all remediated and independently re-reviewed:

| Finding | Remediation commit | Result |
|---|---|---|
| M1 — a cancelled or refused second import dialog could discard the running import's remembered folder | `0347a05` (R1) | PASS |
| M2 — Reset Preferences left Aqua outlined role buttons with the previous theme's images | `0347a05` (R1) | PASS |
| M3 — the test guard's bundled-Python bytecode exception was too broad | `0347a05`, `93b1659`, `f7a0b51` (R1–R3; tests only) | PASS (R3) |

**Final verdict: PASS WITH LIMITATIONS**, for `f7a0b51e697cf71cf8d51887ed548a10908918ec`. R3 changed only the test
guard, its tests and documentation. The review withholds nothing further; it does not claim a passing Full gate.

## Accepted by the owner (not a test)

- The combined evidence above (the passing journeys and guarded groups of the historical run, the F1/F2 remediation
  checks, the three remediated and re-reviewed findings and the final verdict) as sufficient for v0.8.1, without a
  second Full gate.

## Not qualified (open for v0.8.1)

- **macOS native checks owned by the maintainer:** Preferences Reset confirmation of the Aqua outlined buttons on a
  real Mac; remembered folders in the Finder's own file dialogs; Full Keyboard Access / Tab traversal of the outlined
  buttons.
- **Windows owner-manual folder checks** that remain outstanding, and the **conditional setup (first-run) visuals**.
- **Windows real symbolic-link rejection** on an account that holds the privilege to create links (the test skips on
  the HOME-PC account with WinError 1314).
- **Fresh installation:** no first installation of this exact release has been run on a fresh Mac or fresh Windows
  computer; **a fresh Mac has not been qualified by any separate evidence.** The macOS statements are limited to the one
  MacBook Pro (Apple M4 Pro, 24 GB) named in the README and to the macOS revision's earlier qualification.
- Everything listed in `ACT-v0.8.0-Windows-Release-Acceptance.md` as not qualified that was not re-tested (Windows
  long-path switch-on on a computer where it is off, a standard account, Windows 10, other scaling, other GPUs, and a
  full five-component first-time installation on this exact code).
- Other recorded platform and hardware limits (OmniVoice needs an NVIDIA GPU on Windows; Chatterbox and Qwen3 are
  Windows only). Linux is not qualified or distributed.
- **Voice previews:** the gallery still has exactly **28 published previews** (`previews.json`). The six OmniVoice
  rows are `To Be Added` placeholders: they are not previews, are not counted and are not authorisation to publish any.
  The gallery is not bundled in either archive.

## Release content frozen for the build

- Both archives derive from the same committed source; the executable scripts tree is unchanged from the reviewed
  candidate. Windows offers all 34 registered voices; macOS offers 20 (Edge 5, Kokoro 9, OmniVoice 6); Chatterbox and
  Qwen3 stay Windows only. No voice identity, engine setting, reference recording, model version or synthesis
  behaviour changed in v0.8.1 release preparation.
- Exactly 18 named clone reference recordings ship (six each for Chatterbox, Qwen3 and OmniVoice), with the
  reference-recording licensing disclosures preserved as before. No model weights, caches, runtime data, logs or
  private files ship.
- **Not published:** the macOS-only revision `0.8.0+macos.1` (D16, "v0.8.0 for macOS, Revision 1") was prepared but never
  tagged or published; its code is part of `master` and of this release.

## Licensing disclosed with the release

OmniVoice model weights are **CC-BY-NC (non-commercial use only)**; the OmniVoice program code is Apache-2.0; the
required audio tokenizer is under the **Boson Higgs Audio 2 Community License**, based on the Meta Llama 3 Community
License (the Llama 3 Acceptable Use Policy applies, outputs may not improve another large language model, more than
100,000 annual active users needs an expanded licence, attribution required; the README carries the required
attribution). The model card also forbids unauthorised voice cloning, impersonation and fraud. The app never ships the
weights or the tokenizer: a user's own installation downloads them, with their licence files, from one pinned
revision. The historical reference-recording licensing disclosures are unchanged. The application itself is GPL-3.0.
This is not legal advice.

## Release-documentation checks (focused only)

The README, version, configuration and packaging checks affected by the documentation (see the Handoff for the exact
selection and result). No Full gate, complete suite, guarded verification campaign, journey run, installation, model
download or TTS inference was run for this release preparation.

## Integration, archives and publication

Performed after the commit that adds this file: fast-forward of `master` to the release-preparation commit (no squash,
rebase or force), then the unchanged packager `scripts/shared/release.py` building both archives from that exact
committed source. The merged SHA, each archive's SHA-256, size and member count are recorded in the Handoff's closeout
entry; this document does not claim them. **Tagging, the `v0.8.1` release and any upload are not done by this record
and carry no date or URL here.**
