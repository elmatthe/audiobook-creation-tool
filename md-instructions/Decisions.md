# Audiobook Creation Tool — Decisions (ADR log)

Append-only. Newest entries on top. Each entry: date, decision, why, signed by whoever made it.

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
