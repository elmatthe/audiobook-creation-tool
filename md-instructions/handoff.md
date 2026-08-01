# Audiobook Creation Tool — Handoff

## Current Focus
**v0.6.0 Drop 1 (Windows UI prototype) — PHASE 3 COMPLETE, STOPPED at the Phase 4
approval gate.** Plan file: `md-instructions/0.6.0-drop1-windows-ui-prototype.md`
(Plan 1 of nine planned v0.6.x instruction drops; the remaining eight are named in
the plan's sequencing note but are **not drafted and must not be started**).

**Branch:** `feature/0.6.0-drop1-windows-ui-prototype`
**Start SHA (actual implementation base):** `1da1e547ce85d6e5c8a5b34fb549ffa8b93f6318`
— this is `origin/master` after a fast-forward-only pull, and it is **identical to the
plan's stated planning-audit baseline**, so there is **zero drift** to explain.
The desktop checkout was 10 commits behind at `695045c` and fast-forwarded cleanly
(no divergence, no merge, no reset, no stash).

**Phase 0 commit:** `0971a20e24fc196967da97d1b204375dc549ad5a` (docs only).
**Phase 1 commit:** `9cd7fb8e04e11d64f9303d0f44a7ca3f3723af51`.
**Phase 2 commit:** `b2e5285958a8d7adcc19a4c17d45f1e55fd7e900`.
**Phase 3 commit:** see the Session Sync Log entry below.

**Phase 0 result:** baseline established and green. No theme, launcher, tool-panel,
test, `requirements.txt`, or `version.py` source was edited — Phase 0 is
reorient/synchronize/record only. `version.py` remains `0.5.1`; no version bump and
no v0.6.0 release is part of this drop.

**Phase 1 result:** the Windows design system exists and is proven isolated. Two
files changed — `scripts/Universal/shared/ui_theme.py` (+795/-7) and
`files/tests/test_ui_theme.py` (+429/-13). **Nothing was converted:** the launcher,
all six tool panels, `requirements.txt` and `version.py` are byte-identical to
Phase 0. A live run of the real launcher confirms every one of the 283 widgets
across the six panels and all 14 launcher-chrome widgets still carries an **empty**
style string, i.e. still renders through the native `vista` theme.

**Hard boundaries carried forward (from the plan):**
- Only the **Windows launcher shell** and the **Windows M4B Metadata Editor** may ever
  be converted by this plan. TTS Audiobook, M4B Converter, MP3 Tool, M4B Maker, and
  Cover Image Resizer must stay unconverted and protected from ttk style leakage —
  before *and* after screenshot approval. Their conversion belongs to Plan 9.
- macOS aqua/Finder and the Linux/other fallback must remain unchanged.
- No toolkit switch away from tkinter/ttk, no new runtime dependency,
  no `requirements.txt` change, no release.
- Phase 5 has a hard **visual approval gate**: the exact ten-image 1920×1080
  100%/125% matrix under `files/UI-Prototype-Screenshots/v0.6.0-drop1/`, then an
  explicit user *approved* / *changes requested* decision. Screenshots existing is
  not approval.

**Phase 2 result:** the Windows launcher shell is converted and recognizably
redesigned — dark navigation rail, header strip naming the active tool, framed
content card, status bar with a focusable log action. Two files changed:
`scripts/Universal/launcher.py` (+151/-8) and `files/tests/test_launcher_smoke.py`
(+299/-0). **`shared/ui_theme.py` was NOT edited** — the Phase 1 API was sufficient.
The five unconverted panels (and the not-yet-converted metadata editor) still carry
an empty style string on every widget. One genuine geometry regression was measured
and is **open for a maintainer decision** — see *Phase 2 limitations* below.

**Phase 3 result:** the Windows M4B Metadata Editor is converted and is now the
**only** converted tool panel. Six files touched (two new). The panel forks on
`theme["mode"]`: `windows` builds the new card layout, every other mode builds the
historical layout byte-for-byte. The maintainer-approved `sidebar_width` correction
(232 → 180) shipped with it and gave the tool panels **+52px of width** back at every
window size. The five unconverted panels still carry **zero** namespaced styles.
Full detail in *Phase 3* below; the one thing still open is the **vertical** part of
the Phase 2 geometry regression, which the width change could not address.

**Next proposed phase:** Phase 4 — automated and functional regression hardening:
review the whole diff for generic-style leakage and unintended changes, complete the
Section 11 manual functional matrix on Windows (dialogs, list/pages, safe save on
copies, Clear All Tags, Remove Series Numbering, Cancel mid-run, the controlled error
path), re-check resize/keyboard behaviour, and record the macOS smoke requirement.
**Not started. Awaiting explicit user approval.**

### Phase 3 — M4B Metadata Editor + visual specimens (2026-07-31, HOME-PC)

**What it is.** `mp3_tools/m4b_metadata_editor.py` now forks its presentation:

| Mode | Build path | Result |
|---|---|---|
| `windows` | `_build_ui_windows()` | the new card layout, built entirely from `ACT.*` |
| `aqua` / `classic` | `_build_ui_classic()` | the pre-v0.6.0 layout, byte-for-byte |

Both forks create **exactly the same widgets and attributes**, so every method below
the builders — callbacks, workers, the queue pump, `disable_inputs`, the Cancel path,
`_collect_tags`, `_shared_tags` — is shared and has no idea which one drew the screen.
Nothing about metadata reading/writing, field precedence, file order, output paths,
filenames, tag namespaces, chapter logic, thread boundaries or cancellation timing was
touched.

**Entry point.** `build_ui(parent)` is unchanged. It gained an optional
`theme=None` second parameter: when omitted (which is what the launcher does) the panel
resolves the platform bundle itself via `ui_theme.apply_theme`, which is idempotent by
contract. The parameter exists so the developer-only fixture — and, later, the launcher
— can hand in a bundle already applied instead of re-resolving it. Every existing caller
keeps working untouched.

**The new section/card hierarchy** (row 0 scrolls; rows 1 and 2 never do):

```
row 0  scrollable canvas  ── Audiobook Files      (ACT.TLabelframe)
                          ── Shared Metadata      (ACT.Shared.TLabelframe)  <- distinct
                          ── Chapter Titles (optional)  (ACT.TLabelframe)
                          ── Output                     (ACT.TLabelframe)
row 1  action bar   progress line, then Save / Clear All Tags / Remove Numbering / Cancel
row 2  Log          (ACT.TLabelframe + ACT-styled Text)
```

**Visual mapping of every pre-existing control** (nothing was dropped, hidden or
renamed):

| Control | New home | Style |
|---|---|---|
| Open M4B File(s) / Open Folder… / Remove Selected / Clear List | Audiobook Files, toolbar row | `button` |
| File list (`listbox`) | Audiobook Files | `style_tk_widget(…, "list")` + `vscrollbar` |
| `mode_var` notice (shared/"(varies)") | Shared Metadata caption block | `shared_secondary` |
| Title, Author/Artist, Album, Year, Genre, Comment | Shared Metadata grid (Year \| Genre share a row) | `shared_label` + `entry` |
| Cover image entry + Browse… + Clear | Shared Metadata grid, last row | `entry`, `button` |
| Series Name, Series Part, Auto-number toggle | Shared Metadata → Series sub-group | `shared_label`, `entry`, `shared_checkbutton` |
| `series_readback_var`, `autonumber_hint_var` | Shared Metadata, under the sub-group | `shared_secondary` |
| Chapter pager ◀ / ▶ / page label / hint / text | Chapter Titles card | `button`, `label`, `secondary_label`, `style_tk_widget(…, "text")` |
| Output folder entry + Browse… + Open | Output card | `entry`, `button` |
| Progress bar + counter | Action bar, own line, natural width, left-aligned | `progressbar`, `status_label` |
| Save Tags | Action bar | `primary_button` |
| Clear All Tags / Remove Series Numbering | Action bar | `danger_button` |
| Cancel | Action bar, right-aligned | `button` |
| Log | Row 2 card | `style_tk_widget(…, "log")` + `vscrollbar` |

**Shared Metadata, and what it deliberately is not.** Every metadata field in this
editor is *already* batch-wide — a non-blank value is written to every loaded file, and
the existing shared-value detection reports which of them matched across the batch and
which "(varies)". The card is a visual statement of that behaviour, using the Phase 1
`ACT.Shared.TLabelframe` surface (muted accent fill, accent border, accent header) so it
reads as the universal section at a glance. It adds **nothing**: no populated-global-
overrides-per-book precedence, no per-book field disabling, no multi-book workspace, no
one-page-per-M4B workflow — those are Plan 6 / Plan 8. A test asserts no field in the
card is disabled by the grouping, and `test_m4b_metadata_editor_shared.py` (7 tests,
untouched) still owns the shared/"(varies)" semantics.

**Summary/Details, and what it deliberately is not.** It is **not** in the runtime
editor — putting a Summary/Details control there would be a non-functional control in a
user-facing panel, which the plan forbids. It lives in the developer-only fixture as a
component sheet: an `ACT.TNotebook` with Summary and Details tabs, plus the primary /
secondary / danger / ghost / disabled action swatches. The sheet labels itself with
`SPECIMEN_NOTE`, which states in so many words that there is no filtering, no separate
log buffers, no technical-log routing, no job snapshot, no ETA, no Retry Failed and no
Pause/Resume — all Plan 3. A test asserts that text is present and that no button on the
sheet has a command bound to it.

**The developer-only fixture — `files/tests/manual_windows_ui_prototype.py`.** Needed,
because the Phase 5 matrix requires a populated editor and a mid-run editor, and a real
batch finishes far too fast to photograph while a populated batch would otherwise need
real audiobooks on the screenshot machine. Runtime isolation is enforced four ways and
asserted by `test_manual_fixture_is_developer_only_and_unreachable_at_runtime`:

1. pytest cannot collect it — the filename is not `test_*` and it declares no test
   functions (the test greps the source to prove it).
2. The launcher cannot reach it — it is in no `launcher.TOOLS` entry.
3. It is not in the shipped tree — it lives under `files/`, and the test asserts no copy
   exists anywhere under `scripts/`.
4. It patches nothing. Every state is reached by calling the editor's own public methods
   (`_populate` seeds `files`/`_tag_cache`/`_chap_counts` then calls the real
   `_refresh_mode`; `_make_busy` calls the real `disable_inputs`/`progress.update`). A
   test asserts none of its canned paths exist on disk, so it is fully offline.

States: `empty`, `populated`, `active-run`, `specimen`.

**`sidebar_width` 232 → 180 (maintainer-approved).** Measured content-host size:

| Window | Classic (master) | Phase 2 (rail 232) | Phase 3 (rail 180) | Recovered |
|---|---|---|---|---|
| 920×600 (minimum) | 796×561 | 669×457 | **721×457** | +52 w |
| 1024×720 (default) | 900×673 | 773×577 | **825×577** | +52 w |
| Maximized 1920×1009 | — | — | 1721×866 | +52 w |

Navigation is still comfortable: the widest row ("TTS Audiobook") wants 115px against
160px of rail interior — 45px of slack for 125% scaling. A test pins the token at 180
and a launcher test asserts every row still fits.

**Is the M4B Converter's primary action and Log reachable again? Partly — honestly:**

| Window | `Convert M4Bs → MP3s` row | Log box |
|---|---|---|
| 1024×720 (default) | **YES** — mapped, fully inside the host | **YES** — mapped, fully inside the host |
| 920×600 (minimum) | **NO** — unmapped, ~19px past the host bottom | **NO** — unmapped, ~110px past |

The rail change gave back **width**, and width was the whole of the new-in-Phase-2
horizontal overflow — so at the default size that panel is fully usable again. The
remaining clip at the minimum size is **vertical**, caused by the launcher's header
strip (~96px), and neither lever for that (`MIN_SIZE` / `DEFAULT_GEOMETRY`) was changed,
per the maintainer's decision. Recorded, not fixed.

**Panel fit after the change** (requested size minus host; positive = overflow):

| Panel | 1024×720 | 920×600 |
|---|---|---|
| TTS Audiobook | −204 w / −50 h | −100 w / +70 h |
| M4B Converter | −57 w / +102 h | +47 w / +222 h |
| MP3 Tool | −227 w / +278 h | −123 w / +398 h |
| M4B Maker | +23 w / +187 h | +127 w / +307 h |
| Cover Image | −140 w / +21 h | −36 w / +141 h |
| **M4B Metadata (converted)** | **−165 w / −61 h** | −61 w / +59 h |

The converted editor is now the best-fitting panel of the six: it needs no scrolling at
all at the default size, where before Phase 3 it overflowed by 77px horizontally.

**Combobox popdown: not needed, limitation carried forward.** The editor owns no
combobox, so Phase 3 never had to style the popdown list. It remains unthemed and
remains a Plan 9 problem; no `option_add()` was used anywhere (the diff scan is clean).

**Phase 3 automated results (repo venv, Python 3.12.10):**

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_m4b_metadata_editor_shared.py` | PASS — 7 passed in 0.03s (unchanged) |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_m4b_metadata_editor_ui.py` | PASS — **12 passed** in 0.45s (new file) |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_ui_theme.py` | PASS — **17 passed** in 0.13s (was 16) |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_launcher_smoke.py` | PASS — **11 passed**, 1 warning in 2.23s (was 10) |
| `.venv\Scripts\python.exe -m pytest -q` (full suite) | PASS — **82 passed, 3 skipped**, 1 warning in 4.91s (was 68/3) |
| `.venv\Scripts\python.exe scripts/verify.py` | **RESULT: PASS** — pytest 82 passed / 3 skipped in 4.86s; deps `==`-pinned; docs de-templated |
| `git diff --check` | clean (only the benign LF→CRLF notices) |

The 1 warning is still the pre-existing pydub `audioop` DeprecationWarning; the 3 skips
are still the pre-existing `JACK_RYAN_M4B_FOLDER`-gated tests. Neither is new.

**What the new tests prove.** `test_m4b_metadata_editor_ui.py` (12): the panel still
builds and exposes all 24 required widgets and 24 required callbacks, one Tk var per
field correctly bound to its entry, the idle starting state, the busy→idle transition
across every guarded widget, shared-value prefill driven through the real widget tree,
and a non-Windows theme building the historical layout with zero namespaced styles. On
Windows: only `ACT.*` styles are used and no ttk widget was left generic; the generic
styles are byte-identical before and after building it; Listbox/Text/Canvas go through
`style_tk_widget` rather than local literals; the scroll region is still one canvas with
its scoped `%d`-substituted wheel binding; the Shared Metadata surface is unique,
contains every batch field and disables none of them; and Save/Cancel/progress/Log are
outside the scroll region while the form, list and chapter pages are inside it. Plus the
two fixture-isolation tests. `test_launcher_smoke.py` gained the narrowed-rail test and
its isolation test now distinguishes the converted panel (>40 ACT-styled widgets, none
generic) from the five unconverted ones (zero ACT styles between them).
`test_ui_theme.py` gained the Shared Metadata surface-family test and the pinned rail
width.

**Draft visual review (real app, real Tk, HOME-PC, 1920×1080 @ 100%).** Draft only —
scratchpad images, deliberately **not** committed; the ten-image 100%/125% matrix is
Phase 5.

| Check | Result |
|---|---|
| Narrower rail still shows all six tool names clearly | PASS — widest row 115px in a 160px interior |
| Nav selection / hover / pressed / disabled / keyboard focus | PASS — unchanged from Phase 2, verified again after narrowing |
| Editor is a hierarchy redesign, not a recolor | PASS — four titled cards, a distinct shared surface, an action bar and a log, where the old panel was one flat stack of labelframes |
| Shared Metadata visually distinct and recognizable | PASS — accent-blue border and header on the muted fill, clearly different from the neutral cards above and below it |
| Every existing control reachable (layout or deliberate scroll) | PASS — all present; the form scrolls, the actions and log do not |
| Primary actions, progress, Cancel, status, log reachable | PASS at 1024×720, 920×600 and maximized (measured, not eyeballed: all mapped and inside the host at the minimum) |
| File list / chapters / fields / cover / output scroll correctly | PASS |
| Mouse-wheel affects the intended area | PASS — wheel over the form scrolls the form; over the Log scrolls the Log; unchanged wiring |
| Tab / Shift+Tab order sensible, no focus trap | PASS — a 31-stop closed loop: rail (6) → file actions → list → shared fields → cover → series → chapters → output → primary actions → log folder. Disabled controls (Cancel, the pager arrows with no files) are correctly skipped |
| Five classic panels remain unconverted | PASS — in the running app and by test |
| ttk still `vista` | PASS |
| Content-host measurements re-recorded at 920×600 / 1024×720 | PASS — table above |
| Remaining classic-panel overflow reported honestly | PASS — table above; M4B Converter at the minimum is still clipped |
| Summary/Details specimen is clearly presentation-only | PASS — headed "component specimen" with the explicit note; not in the product |
| Fixture unreachable from the runtime launcher | PASS — in-app and by test |

### Phase 3 limitations and open items

1. **The vertical half of the Phase 2 geometry regression is still open.** The approved
   rail change fixed the width. The ~96px of height the shell costs the panels (header
   strip + card frame) is untouched, and that is what still clips M4B Converter's
   `Convert M4Bs → MP3s` row (~19px) and Log (~110px) at the 920×600 minimum. The
   maintainer's decision was to leave `MIN_SIZE`/`DEFAULT_GEOMETRY` alone for now and
   re-assess at Phase 5 against the full 100%/125% matrix. Context that still applies:
   M4B Converter, MP3 Tool and M4B Maker already overflow at 920×600 on master too.
2. **The editor's scroll viewport is shallow at the minimum size** — about 206px at
   920×600 (about 330px at the 1024×720 default, and the whole form fits without
   scrolling when maximized). The form is a deliberate scroll region and the action bar
   and Log stay visible, which is the plan's requirement, but at the absolute minimum
   window size only the Audiobook Files card is visible without scrolling. Flagged for
   the Phase 5 review rather than fixed by shrinking the Log.
3. **No 125% scaling pass yet** (carried from Phase 2). Nothing added in Phase 3 uses a
   fixed pixel height — the cards size from their own fonts — but the true 125% pass is
   Phase 5 and is **not** claimed.
4. **`ttk.Combobox` popdown still unthemed** (carried from Phases 1–2). Phase 3 did not
   need it; the editor owns no combobox. Still a Plan 9 item.
5. **macOS still not verified live** (carried from Phases 0–2). The editor's non-Windows
   fork is asserted to build the historical layout with zero namespaced styles via an
   explicit classic bundle, and `_build_ui_darwin`/`_apply_darwin` were not touched, but
   no Mac was available. Not claimed as passed.
6. **One transient observed in the verify gate.** A single `scripts/verify.py` run
   reported `65 passed, 20 skipped` instead of `82 passed, 3 skipped` — 17 extra skips,
   exactly the size of `test_ui_theme.py`, whose module-scoped fixture skips when
   `tk.Tk()` cannot open a display. It happened once, immediately after several GUI
   scripts had created and destroyed Tk roots, and did not reproduce on the same command
   before or after (both `82 passed, 3 skipped`). Recorded because the headless guard
   converts that condition into skips rather than failures, so a transient can quietly
   reduce coverage while the gate still says PASS. The guard predates this drop; not
   changed here.

### Phase 2 — Windows launcher shell (2026-07-31, HOME-PC)

**What it is.** `launcher.py` now routes three shells off `theme["mode"]`:
`aqua` -> `_build_ui_darwin` (untouched), `windows` -> the new `_build_ui_windows`,
anything else -> `_build_ui_classic` (untouched). macOS and Linux/other are
byte-identical to Phase 1; only the Windows arm is new.

**Layout and style mapping** (every widget names a `theme["styles"]` key — no hex
literal and no magic number reaches `launcher.py`):

| Region | Widget | Style key |
|---|---|---|
| Application background | `root.configure(background=…)` | `colors["window"]` |
| Navigation rail | `ttk.Frame`, fixed `metrics["sidebar_width"]` | `sidebar` |
| Rail header ("TOOLS") | `ttk.Label` | `sidebar_label` |
| Tool rows (6) | `ttk.Button`, `command=select_tool` | `nav_button` |
| Rail / column rules | `ttk.Frame` width or height 1 | `divider` |
| Header strip | `ttk.Frame` | `toolbar` |
| Active tool name | `ttk.Label` | `title` |
| Active tool description | `ttk.Label` | `status_label` |
| Content card frame | `ttk.Frame` (1px hairline around the host) | `divider` |
| Content host (`self.content`) | `ttk.Frame` | **none — deliberately unstyled** |
| Status bar | `ttk.Frame` | `window` |
| Status text | `ttk.Label` (`status_var`) | `status_label` |
| Open log folder | `ttk.Button`, `command=_open_logs` | `ghost_button` |
| Load-failure panel | `ttk.Frame` / `ttk.Label` / `tk.Text` | `window`, `title`, `status_label`, `style_tk_widget(…, "log")` |

**How the content host isolates the five classic panels.** `self.content` and every
per-tool container stay **plain, unstyled `ttk.Frame`s in every mode**. ttk has no
style inheritance, so a child that names no style resolves the *generic* `TFrame` /
`TButton` / `TEntry` — exactly what it resolved on master. The shell therefore cannot
leak into a panel even in principle: there is nothing to inherit from. The card
*border* is drawn by a hairline frame wrapped **around** the host rather than by
styling the host itself, which is what lets the border exist without the host
carrying a style. The one thing inside a container that may carry an `ACT.*` style is
the launcher-owned load-failure panel, which only exists when a tool failed to build
— and the smoke tests assert that never happens.

**Selection cue.** The rail marks the active tool with the standard ttk `selected`
state flag, which `ACT.Nav.TButton` maps to the soft accent fill plus primary text.
Unlike the classic cue (which *disables* the active button) no row is ever disabled,
so every row stays reachable by Tab and keeps its focus ring. `Open log folder` was
promoted from a clickable `tk.Label` to a real `ttk.Button` for the same reason —
it now takes focus and fires on Enter/Space. Both actions are otherwise unchanged.

**No fixed pixel heights.** The header and status bar size themselves from their own
fonts, so 125% display scaling grows them instead of clipping them. `sidebar_width`
is the only fixed dimension; the longest tool name needs 112px of the 212px available
inside the rail, so it has slack at 125%.

**Phase 2 automated results (repo venv, Python 3.12.10):**

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_launcher_smoke.py` | PASS — **10 passed**, 1 warning in 2.18s (was 1) |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_ui_theme.py` | PASS — 16 passed in 0.12s (unchanged) |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_m4b_metadata_editor_shared.py` | PASS — 7 passed in 0.03s (unchanged) |
| `.venv\Scripts\python.exe -m pytest -q` (full suite) | PASS — **68 passed, 3 skipped**, 1 warning in 4.42s (was 59/3) |
| `.venv\Scripts\python.exe scripts/verify.py` | **RESULT: PASS** — pytest 68 passed/3 skipped; deps `==`-pinned; docs de-templated |
| `git diff --check` | clean (only the benign LF→CRLF notice) |

The 1 warning is still the pre-existing pydub `audioop` DeprecationWarning; the 3
skips are the pre-existing env-gated suites. Neither is new.

**What the 9 new launcher tests assert:** the six tools stay in `TOOLS` order and each
gets a nav control in that order; three full sweeps of all six panels produce zero
error panels, no new containers, and the *same container objects* (build-once intact);
a real typed value in the metadata editor survives switching away through three other
tools and back; a valid saved `last_tool` is restored and **only that tool is built**
(the rest stay lazy); an unknown saved key falls back to the first available tool; a
saved tool whose module has gone missing drops out of the registry, gets no nav row,
and falls back safely; every launcher-owned widget carries the intended `ACT.*` style
and **every** non-empty style string anywhere in the shell is `ACT.*`-prefixed;
selection moves the `selected` flag rather than accumulating it and no row is left
disabled; and no widget inside any tool container carries an `ACT.*` style, while
`TButton`/`TFrame` still resolve to `SystemButtonFace` and `ACT.Primary.TButton` to
the accent. The last three are Windows-only and skip elsewhere, because
monkeypatching `sys.platform` for a whole launcher build would also lie to the six
tool modules while they construct.

**Draft visual review (real app, real Tk window, HOME-PC, 1920×1080 @ 100%).** Not
the Phase 5 matrix — draft images live in the session scratchpad and are deliberately
**not** committed.

| Check | Result |
|---|---|
| Recognizably redesigned Windows shell | PASS — dark rail + header + card + status bar, not a recolor |
| Six tools, existing order, all open | PASS — 6/6, zero error panels |
| Selected / hover / pressed / disabled / focus visible | PASS — accent-soft selected fill; focus ring visible on both a nav row and the log button |
| Five non-prototype panels keep classic presentation | PASS — TTS, M4B Converter, MP3 Tool, M4B Maker, Cover render exactly as on master |
| No child-panel `ACT.*` styling | PASS — verified in-app and by test |
| Switching preserves identity and state | PASS |
| Saved last-tool restore / invalid fallback | PASS |
| Status text and log-folder action | PASS — status updates per tool; log button focusable and fires |
| ttk theme still `vista` | PASS |
| Normal (1024×720) / minimum (920×600) / maximized (1920×1009) | PASS for launcher-owned controls — nothing overlaps or clips at any of the three; status and log action stay visible and reachable |
| Content host seam around classic panels | PASS — the host is unstyled, so a classic panel sits on the same background it always had; no unreadable seam |
| **Usable panel area at minimum size** | **OPEN — regression, see below** |

### Phase 2 limitations and open items

1. **The new shell costs the tool panels real space, and at the 920×600 minimum that
   clips a primary action.** Measured content-host size (both shells, same build,
   same panels):

   | Window | Classic shell (master) | Windows shell (Phase 2) | Delta |
   |---|---|---|---|
   | 920×600 (minimum) | 796×561 | 669×457 | −127 w, −104 h |
   | 1024×720 (default) | 900×673 | 773×577 | −127 w, −96 h |

   110 of the 127 lost pixels are the navigation rail: `metrics["sidebar_width"]` is
   232 where the classic sidebar was ~122 including its padding. The rest is the
   header strip and the card frame. I already took the card frame down from
   `content_pad` to `gap_sm`, which recovered 16 w / 12 h; that is everything
   reclaimable inside `launcher.py` without changing a Phase 1 token.

   Effect, by panel requested-size vs host:
   - **Already true on master:** M4B Converter (+118 h), MP3 Tool (+294 h) and
     M4B Maker (+203 h) overflow at 920×600 on the *classic* shell too. Panels
     overflowing at the minimum size is a pre-existing condition, not a new class
     of bug.
   - **New in Phase 2 at the default 1024×720:** M4B Maker (+75 w) and M4B Metadata
     (+77 w) now overflow *horizontally* where they had 52/50px of slack, and every
     panel's vertical overflow grows by ~96px.
   - **Concretely visible:** M4B Converter at 920×600 no longer shows its
     `Convert M4Bs → MP3s` row or its Log box; on master at the same size it does.

   **I did not fix this, on purpose.** The two real levers are
   `metrics["sidebar_width"]` and `MIN_SIZE`, both of which live in
   `shared/ui_theme.py` — a file this phase was told to leave alone unless the
   launcher exposed a *missing primitive*, which this is not. It is a value/geometry
   decision, and the plan (§7.1, §7.2) says token values and any geometry change are
   approved by the maintainer with evidence, not chosen by the implementer.
   **Options for the maintainer, cheapest first:**
   (a) drop `sidebar_width` 232 → 180 (recovers 52 w; the existing test floor is
   `>= 180`, so it still passes); (b) raise `MIN_SIZE`/`DEFAULT_GEOMETRY` with the
   evidence above — note `MIN_SIZE` is shared with macOS; (c) accept it, on the
   grounds that Plan 9 converts these panels to the denser new design anyway and
   they already overflow at the minimum size today.

2. **No 125% scaling pass yet.** The draft review was 100% only. Nothing in the shell
   uses a fixed height, and the rail has 100px of text slack, but the true 125% pass
   is Phase 5 work and is **not** claimed as done.

3. **Draft review is not visual approval.** The mandatory ten-image 1920×1080
   100%/125% matrix under `files/UI-Prototype-Screenshots/v0.6.0-drop1/` remains
   Phase 5, and the draft images are not committed.

4. **`ttk.Combobox` popdown list is still unthemed** (carried from Phase 1). The
   dropdown is a classic Tk listbox reachable only through the global option database,
   which would leak into the five unconverted panels. The launcher owns no combobox,
   so this did not bite in Phase 2; if Phase 3 needs a dark popdown it must be scoped
   per-widget with the isolation tests still green.

5. **macOS still not verified live** (unchanged from Phases 0–1). `_build_ui_darwin`
   and `_apply_darwin` were not touched, and the aqua/classic branch tests pass, but
   no Mac was available. Not claimed as passed.

### Phase 1 — Windows design primitives (2026-07-31, HOME-PC)

**What it is.** `shared/ui_theme.py` now routes each platform explicitly —
`darwin -> "aqua"`, `win32 -> "windows"`, everything else -> `"classic"`. Windows is
never inferred from "not macOS" any more. The Windows branch keeps the **native
`vista` base theme** and layers a dark design system on top as namespaced styles and
token dictionaries. Nothing is applied to a widget automatically: a panel opts in by
naming an `ACT.*` style or by calling `style_tk_widget()`.

**The isolation mechanism (this is the part later phases must not break).**
`vista` draws buttons, entries, comboboxes, spinboxes, checkbuttons, radiobuttons,
notebook tabs, progressbars, scrollbars, Treeview fields/headings and labelframes
with native Windows theme parts that **ignore** `-background`/`-foreground`. Switching
the app to `clam` would recolor them but would also silently restyle the five panels
this drop must leave alone. So each recolorable element is *cloned* into the live
theme under the prefix:

```
ttk::style element create ACT.Button.border from clam Button.border
```

and the `ACT.*` styles are laid out from those clones. Generic `TFrame` / `TLabel` /
`TButton` / `TEntry` / `TCombobox` / `Treeview` / … are never created, configured or
re-laid-out, so an unconverted panel keeps native vista rendering while a converted
one gets a fully colorable dark control set from the same toolkit.
`element_create` raises `Duplicate element` on re-entry, so the clone step is guarded
and `apply_theme` is idempotent.

**Rule for Phase 2/3 and for Plan 9 later:** every variant style needs its **own**
layout. ttk resolves a name by stripping leading components, so `ACT.Primary.TButton`
falls back to plain `TButton` — the native vista button — unless it is given the
`ACT.TButton` layout explicitly. `_ACT_LAYOUTS` does this for every variant; adding a
new variant means adding it there too, or the dark fill silently will not stick.

**API introduced (all in `shared/ui_theme.py`):**

| Name | What it is |
|---|---|
| `WINDOWS_STYLE_PREFIX` | `"ACT"`. Every registered style begins with it; nothing outside it is touched. |
| `theme["mode"]` | now `"windows"` on win32 (was `"classic"`). `launcher.py` only tests `== "aqua"`, so it still takes the classic build path — that is why Phase 1 changes nothing on screen. |
| `theme["base_theme"]` | the ttk theme actually in use (`"vista"`, or `"clam"`/`"default"` when vista is unavailable). |
| `theme["colors"]` | 35 semantic colour roles (surfaces, text, accent/focus, status, fields/selection, scrollbars, Shared Metadata). Nonempty on Windows; still `None` on the classic branch. |
| `theme["metrics"]` | 26 spacing/sizing tokens (sidebar width, row height, pads, gap scale, control padding, border/scroll widths, `content_max_width`). |
| `theme["fonts"]` | 11-entry Segoe UI type scale + `Consolas` mono. `font_heading`/`font_button` keep their historical values so the bundle is still a drop-in for the classic launcher. |
| `theme["styles"]` | semantic key → ttk style name (`theme["styles"]["primary_button"] == "ACT.Primary.TButton"`). **Panels must look styles up here, not hard-code the string.** |
| `style_tk_widget(widget, theme, role="surface", **overrides)` | the one sanctioned way to colour classic Tk widgets ttk cannot style (`Canvas`, `Listbox`, `Text`, `Frame`). Roles: `window, surface, elevated, muted, sidebar, shared, field, list, text, log, canvas, divider`. Unsupported options are dropped so one call works for every widget class; `overrides` win; unknown role raises `ValueError`; **no-op on any non-Windows bundle**, so panels may call it unconditionally. Returns the applied option dict. |

**Explicitly unchanged:** `apply_theme(root, style)` signature, `DEFAULT_GEOMETRY`,
`MIN_SIZE`, `enable_mousewheel`, and the whole `ProgressIndicator` class (`update`,
`set_indeterminate`, `reset`, `finish`, main-thread contract). `ProgressIndicator`
deliberately still uses the *generic* styles — five unconverted panels instantiate it,
and a test asserts its widgets carry an empty style string.

**Phase 1 automated results (repo venv, Python 3.12.10):**

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_ui_theme.py` | PASS — **16 passed** in 0.15s (was 5) |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_launcher_smoke.py` | PASS — 1 passed, 1 warning in 1.54s |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_m4b_metadata_editor_shared.py` | PASS — 7 passed in 0.03s |
| `.venv\Scripts\python.exe -m pytest -q` (full suite) | PASS — **59 passed, 3 skipped**, 1 warning in 3.64s (was 48/3) |
| `.venv\Scripts\python.exe scripts/verify.py` | **RESULT: PASS** — pytest 59 passed/3 skipped; deps all `==`-pinned; docs de-templated |
| `git diff --check` | clean (no whitespace errors) |

The 1 warning is still the pre-existing pydub `audioop` DeprecationWarning; the 3
skips are the pre-existing env-gated suites. Neither is new.

**What the 11 new theme tests actually assert:** explicit `"windows"` mode and a
backwards-compatible bundle; every colour parses as `#rrggbb` and every required
semantic role exists; WCAG contrast floors on all seven surfaces (primary text ≥7:1,
secondary ≥4.5:1, disabled ≥3:1, focus ring ≥3:1, status/accent ≥4.5:1 on the card,
`inverse`-on-accent and `selection_text`-on-selection ≥4.5:1); metrics are
non-negative ints with sane layout minimums; every style name starts with `ACT.`, has
a layout, and roots in a cloned element rather than a native one; hover / pressed /
selected / disabled / focus / danger states are defined and actually resolve to
different values; **generic styles are byte-identical before and after applying the
Windows theme** (layout + configure + background/foreground/fieldbackground lookups +
state maps, for 18 generic styles); re-applying three times is idempotent; the branch
still returns a full bundle when `vista` raises; one real widget per style builds and
renders; and `style_tk_widget` applies/drops/overrides correctly and is a genuine
no-op on the classic bundle.

**Live Windows evidence (real `LauncherApp`, real Tk window, not a mock):**
- `theme["mode"] == "windows"`, `ttk` theme in use still `vista`.
- All six tools registered in order and selected twice: **zero** error panels,
  6 containers with stable object identity (build-once intact), state marker survived
  switch-away/back, `last_tool` round-tripped, geometry `1024x720`, minsize
  `(920, 600)` — identical to the Phase 0 baseline.
- Style audit across the whole widget tree: `tts` 63, `m4b_converter` 38, `mp3_tool`
  41, `m4b_maker` 53, `cover` 24, `m4b_metadata` 64 widgets — **the only distinct
  style string in every panel is `""`**, and the 14 launcher-chrome widgets are the
  same. Zero widgets use an `ACT.*` style anywhere in the application.
- Generic lookups after theming: `TButton`/`TFrame`/`TLabel`/`TEntry`/`TCombobox` →
  `SystemButtonFace`, `Treeview` → `SystemWindow` (native vista values), while
  `ACT.Primary.TButton` → `#4f8ff7`. Both facts are true at the same time, which is
  the whole point of the namespace.

### Phase 1 limitations and open items

1. **No visual/eyes-on inspection.** Everything above is behaviour and style-resolution
   evidence gathered programmatically. Nothing has been *looked at*, and by design
   nothing is visible yet — no widget uses the new styles. Appearance remains Phase 5's
   gate, and the exact colour values are approved through screenshots, not by these
   tests.
2. **`ttk.Combobox` popdown list is not themed.** The dropdown is a classic Tk listbox
   reachable only through the global option database
   (`option_add("*TCombobox*Listbox.background", ...)`), which would leak straight into
   the five unconverted panels' comboboxes. Deliberately not done. If Phase 3 needs a
   dark popdown it must be scoped per-widget, and the leakage test must still pass.
3. **Element clones are per-interpreter.** `ACT.*` elements are created in the live ttk
   theme of the Tk interpreter that `apply_theme` was called on. That is fine for the
   app (one root) and for the tests (module-scoped root); a second `tk.Tk()` would need
   its own `apply_theme` call. Not a defect, just the contract.
4. **macOS still not verified live** (unchanged from Phase 0). aqua preservation is
   proven only by the untouched `_apply_darwin` code path plus monkeypatched-platform
   tests. Not claimed as passed.
5. **Optional tooling:** Context7 was not needed — the question was "can vista host
   cloned clam elements", which was answered by probing the actual Tk 8.6 build in the
   repo venv rather than by reading documentation. Superpowers' executing-plans flow
   structured the phase. Nothing was auto-installed.

### Phase 0 baseline evidence (2026-07-31, HOME-PC)

**Environment**
- Windows 11 Pro 10.0.26200, HOME-PC, repo at
  `…\MyProjects\Home-PC\Audiobook-Creation-Tool`
- Repo venv `.venv\Scripts\python.exe` → Python 3.12.10
- `bootstrap.py --self-test`: venv valid, requirements found, HF_HOME →
  `files/runtime-data/models/huggingface`, `kokoro health = True (ok)`,
  tkinter/ssl/venv/tcl_tk all True, ffmpeg on PATH (`C:\ffmpeg\bin\ffmpeg.EXE`),
  ffprobe available, launch target `scripts/Universal/launcher.py` present.

**Automated baseline (no source edits)**

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_ui_theme.py` | PASS — 5 passed in 0.18s |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_launcher_smoke.py` | PASS — 1 passed, 1 warning in 8.90s |
| `.venv\Scripts\python.exe -m pytest -q files/tests/test_m4b_metadata_editor_shared.py` | PASS — 7 passed in 0.03s |
| `.venv\Scripts\python.exe -m pytest -q` (full suite) | PASS — 48 passed, 3 skipped, 1 warning in 8.41s |
| `.venv\Scripts\python.exe scripts/verify.py` | **RESULT: PASS** — pytest 48 passed / 3 skipped; deps all `==`-pinned; docs de-templated |
| `git diff --check` | clean (no whitespace errors, no output) |

The single warning is the long-standing pydub `audioop` DeprecationWarning, not a
regression. The 3 skips are the pre-existing env-gated suites.

**Windows launcher six-tool manual baseline** — a real (non-withdrawn) Tk window was
opened on this machine through the real `LauncherApp` and every tool was selected once
in registry order, then a second full pass was made to prove build-once and state
preservation:

- Registry order (6/6, unchanged): `tts`, `m4b_converter`, `mp3_tool`, `m4b_maker`,
  `cover`, `m4b_metadata` — titles "TTS Audiobook", "M4B Converter", "MP3 Tool",
  "M4B Maker", "Cover Image", "M4B Metadata".
- Error panels raised across both passes: **none** (`_show_load_error` was
  instrumented and never fired).
- Build-once: 6 containers after pass 1, still 6 after pass 2, and every container's
  object identity was unchanged — panels are shown/hidden, never rebuilt.
- State preservation: a marker attribute set on the M4B Metadata container survived a
  full switch-away/switch-back cycle.
- `last_tool` persisted and read back correctly (`m4b_metadata`); `settings.json` was
  snapshotted and restored, so the baseline left no trace.
- Build-all wall time 1.601 s (per-tool 0.015–0.077 s).
- Realised window: `1024x720+104+104`, minsize `(920, 600)`.

**Pre-prototype Windows theme contract** (what Phase 1 must extend without breaking) —
`shared.ui_theme.apply_theme()` on `win32` returns:

```
mode          = "classic"        ttk theme in use = "vista"
family        = "Segoe UI"       font_heading = ("Segoe UI", 15, "bold")
geometry      = "1024x720"       font_button  = ("Segoe UI", 11)
min_size      = (920, 600)
colors        = None             metrics      = None
```

`colors`/`metrics` being `None` on Windows is exactly the gap Phase 1 closes. Public
surface to preserve: `DEFAULT_GEOMETRY`, `MIN_SIZE`, `ProgressIndicator`,
`apply_theme`, `enable_mousewheel`.

**Before-state screenshot inventory** — all **8** images present and untouched under
`files/UI-Current-Screenshots/`: `cover-image-resizer-current-ui.png`,
`m4b-converter-current-ui.png`, `m4b-maker-current-ui.png`,
`m4b-metadata-current-ui-1.png`, `m4b-metadata-current-ui-2.png`,
`mp3-tool-current-ui.png`, `tts-audiobook-current-ui-1.png`,
`tts-audiobook-current-ui-2.png`. (The plan says "eight before-state images"; the
matrix is 8 files covering 6 tools — TTS and M4B Metadata each have two.)

### Phase 0 limitations and open items (recorded, not silently passed)

1. **No visual/eyes-on inspection was performed.** The six-tool pass was driven
   programmatically through the real `LauncherApp` on a real Tk window; an agent
   cannot judge appearance. This is a baseline of *behaviour*, not of *looks* —
   appearance is Phase 5's gate.
2. **`md-instructions/` filename casing.** The maintainer had renamed the four
   permanent docs on disk to the AI-WORKSPACE casing (`Changelog.md`, `Decisions.md`,
   `Handoff.md`). Git tracks them as `CHANGELOG.md`, `DECISIONS.md`, `handoff.md`, and
   because `core.ignorecase=true` on Windows the rename was never staged — the
   fast-forward checkout restored the tracked casing. **Not changed, and deliberately
   out of Phase 0 scope:** `scripts/verify.py` hard-codes
   `md-instructions/CHANGELOG.md`, so a real case-rename needs a `verify.py` edit,
   which this drop is forbidden from touching. The live filenames are
   `Briefing.md` / `CHANGELOG.md` / `DECISIONS.md` / `handoff.md`, and the plan
   references those same names. **Maintainer decision needed** if the AI-WORKSPACE
   casing is wanted — it should be its own housekeeping commit, not part of this drop.
3. **macOS not verified this session.** No Mac was available; the macOS Finder/aqua
   preservation requirement is proven only through monkeypatched platform-branch
   tests. A live macOS pass remains open for Plan 9 and is **not** claimed as passed.
4. **Git identity on this checkout** is `Elijah Matthew <elijahmatthew015@gmail.com>`,
   not the `elmatthe <elmatthe@ualberta.ca>` pair in AI-WORKSPACE. Left as-is (the
   repo does not lack an identity); flagged only so it is a conscious choice.
5. **Optional tooling:** Sequential Thinking / Context7 were available but not needed
   in Phase 0 — no external library documentation question arose. Superpowers'
   executing-plans flow was used to structure the phase. No tool was auto-installed.

## Previous Focus (v0.5.1 — shipped to master)
**Batch-timing-parity drop ABANDONED by maintainer decision after A/B listening
(2026-07-19); Jenny voice addition kept; v0.5.1 committed to branch
`add-jenny-voice` and pushed for a Windows second-verify pass.** The Phases 1–3
engine work (subprocess delegation, pause-field threading, per-path
`batch_timing_preset` overrides, batch harness, engine `rate` kwarg) hit its
measured targets (every non-Jenny voice within −22…0 ms of its old-batch median)
but sounded subjectively worse than the original chunk pipeline on the
maintainer's six-voice A/B listen — reverted IN FULL from the working tree
(nothing had been committed; see the do-not-retry ADR in DECISIONS.md
2026-07-19 and the work-log entries below, which stand as the historical
record). Final state: batch mode is byte-identical to pre-drop `master`
(chunk pipeline, speaker+rate only, original "Steffan Neural" banner); the ONLY
functional change vs master is the Jenny voice addition (registry entry
750/800 single-file preset, smoke-test counts 12/7, generate_voice_samples
filter args, gitignore entries, sample MP3) plus docs and the 0.5.1 version
bump. Investigation artifacts (batch-baselines/, phase3-listen/, harness, child
script) deleted; drop file deleted per convention. Maintainer pulls
`add-jenny-voice` on Windows, verifies, and merges to master themself — do NOT
merge or push to master from here. Phase 2 (engine change) is
implemented: batch per-file conversion now delegates to `run_conversion_job` in a
child subprocess per file (`tts/batch_convert_child.py` is the child entry;
`_delegate_to_child` in `batch_convert.py` is the spawn/cancel/log seam and the
test-fake point). All seven pause/trim fields + MP3 bitrate thread GUI →
`run_batch_convert` → `convert_single_pdf` → child; presets NOT re-tuned (Phase 3
measures against phase1 baselines). The engine gained ONE additive, default-inert
kwarg: `rate="+0%"` through `run_conversion_job` → `read_book` →
`run_edgespeak`/`parallel_edgespeak` (edge-tts's own default — needed because old
batch honored the GUI Speech-rate field and the single-file engine had no rate
support; single-file inertness proven live: post-change single-file intro render is
millisecond-identical to the reference). Old chunk pipeline
(`split_into_chunks`/`synthesize_chunk_mp3`/`merge_mp3s` + CHUNK_* constants)
removed from batch_convert; "Steffan Neural" banner now shows the real voice.
Live gates: workers=2 real batch → 2/2 mirrored outputs correct, no orphan
children; cancel drill terminates the in-flight child cleanly; verify → RESULT:
PASS (49 passed / 3 skipped; batch tests rewritten around the delegation seam,
5→8). New-engine measurements in
`files/livid-lady-test-files/batch-baselines/phase2-newengine.json`. **⚠ Phase 3
conflict now quantified (maintainer decision required):** restoring old-batch
cadence needs sentence-preset cuts of −162 ms (Steffan), −436…−458 ms (Andrew ×2,
Ava ×2), Aria +70 ms, all of which would shift single-file identically under the
shared preset — per-path presets (or accepting single-file cadence in batch) must
be chosen before Phase 3 re-tuning. Jenny's batch is already −150 ms tighter than
her old batch purely from the engine change. The Jenny preset-trim session's 6
modified files (2026-07-19, further below) still await the same single drop commit.
No behavior change: the only new code is the dev/QA harness
`scripts/Universal/tts/batch_timing_harness.py` (never imported by the app);
verify → RESULT: PASS (46 passed, 3 skipped). Decision: **delegate batch per-file
conversion to `run_conversion_job` via a child subprocess per file** (thread-level
delegation is disproven — a 2-thread demo corrupted/crashed on the process-global
`os.chdir` in `runner.py` on 2/2 runs; a chdir-free engine refactor would touch ~30
cwd-relative filename sites in the GPL-derived engine). Subprocess prototype passed
at workers=1 (real PDF) and workers=2 (nested same-stem tree): mirrored absolute
targets correct, no cross-contamination, parent cwd preserved, and the delegated
render's gap profile is identical to the single-file reference (timing parity by
construction). Baselines for all **7** Edge voices (drop says 6 — Jenny makes 7) ×
{00-intro, 03-ch1-1} captured on the CURRENT engine →
`files/livid-lady-test-files/batch-baselines/phase1-baseline.json` (+
`phase1-variance.json`: Edge synthesis is deterministic run-to-run, gap means ±2 ms,
so Phase 3's ±25 ms tolerance is measurable). Kokoro batch confirmed NOT on this
path (inline GUI loop → `kokoro_file_to_mp3`; untouched by this drop). **⚠ Flag for
the maintainer before Phase 3:** old-batch parity and single-file invariance are
mutually exclusive under one shared preset — e.g. Steffan's old batch median gap is
~770 ms but his single-file (= new-batch) measured gap is ~951 ms at the same preset;
matching old batch within ±25 ms forces preset cuts that would audibly change
single-file mode. Resolution options recorded in the Phase 1 summary. The Jenny
preset-trim session's 6 modified files (2026-07-19, further below) still await the
same single drop commit.

## Previous Focus (UX progress + metadata layout drop — awaiting maintainer commit)
**UX progress + metadata layout drop (`0.5.0-ux-progress-and-metadata-layout.md`) —
ALL PHASES (1–5) DONE on HOME-MacOS (2026-07-08), awaiting maintainer final sign-off
+ the single drop commit.** Phase-4 layout was visually approved by the maintainer
(scrolling, larger Log, de-staled description, progress all confirmed). Phase 5
close-out: full suite 46 passed / 3 skipped; `python scripts/verify.py` →
RESULT: PASS; Windows/classic path proven unchanged (scoped win32 stub on ui_theme →
classic mode, Segoe UI, 6 ttk sidebar buttons, all six tools built, zero error
panels); CHANGELOG [Unreleased] Added+Changed entries, Briefing (ui_theme /
worker-progress / metadata-editor bullets), DECISIONS ADR (progress placement in
ui_theme.py + the deliberate M4B Maker indeterminate call). Drop file deliberately
NOT deleted and nothing committed (maintainer instruction — no .git on this copy;
the maintainer carries files to a real clone, single commit, no AI co-author
trailers).
Work summary — Phase 2: shared `ProgressIndicator` (ttk.Progressbar +
counter/percentage label, main-thread-only `update/set_indeterminate/reset/finish`
API) in `shared/ui_theme.py` (NOT the launcher — tools import shared.*, never
launcher.py) + headless-guarded test. Phase 3: progress wired into all six tools
strictly through each tool's EXISTING worker queue/drain (workers only enqueue
`("progress", (done, total))` / `("progress_ind", text)`; no off-thread widget
violations found in any tool). Determinate: M4B Converter (files), Cover Image
(images), M4B Metadata (files ×3 workers), MP3 Tool (SAFE-combine per track,
time-edit + ID3 per file), TTS (Edge batch + Kokoro batch per file; Kokoro single
per chunk and Edge single per paragraph via new additive `progress_callback=None`
params in `kokoro_file_to_mp3` / `read_book` / `run_conversion_job`). Indeterminate:
M4B Maker (single concat/encode — its old bar was dead: 0 until one jump at the end;
dead `progress_max` queue kind removed) and MP3 Tool's single-concat stages (FAST
mode, SAFE final concat). Phase 4: metadata editor tag/settings sections wrapped in
the exact TTS-style scroll canvas (canvas_wrap + create_window + scrollregion/width
sync + `enable_mousewheel`), Log enlarged to a fixed 14 rows outside the scroll
area, stale "(Added in Phase 6.)" description fixed in launcher.py. Cancel + Log
untouched on every tool. The two previous foci below also still await their single
maintainer commits.

## Previous Focus (component-verify drop — awaiting maintainer commit)
**macOS component-verify drop (`0.5.0-macos-component-verify.md`) — ALL PHASES DONE on
HOME-MacOS (2026-07-08), awaiting maintainer sign-off + the single drop commit.**
Phase 1 kickoff gates green; Phase 2 (Kokoro §2.4) was already fixed 2026-07-07, health
re-confirmed only; Phase 3 voice samples 11/11, approved by maintainer listen; Phase 4
per-tool live pass — **all six tools confirmed working live on macOS** (maintainer reviewed
screenshots), zero macOS-specific breakage, zero code changes; Phase 5 close-out — full
suite 45 passed / 3 skipped, `python scripts/verify.py` → RESULT: PASS, docs updated.
**Residual gap (not a bug):** M4B Converter was verified on a standard AAC-LC M4B only —
the `aac_at` xHE-AAC/USAC decode path on macOS is still unverified (no USAC sample on
hand); see Briefing known limitations. Drop file deliberately NOT deleted and nothing
committed (maintainer instruction). Still no `.git` on this copy — the maintainer carries
files to a real clone. Previous focus below (UI-shell drop close-out) also remains
awaiting its single maintainer commit.

## Previous Focus (UI-shell drop — awaiting maintainer commit)
**macOS UI-shell drop (`0.5.0-macos-ui-shell.md`) — ALL PHASES DONE on HOME-MacOS
(look approved by maintainer 2026-07-08; wheel/trackpad scroll fix added; Phase 5
close-out complete, verify → RESULT: PASS).** Awaiting two maintainer actions:
(1) live-test wheel/two-finger scrolling on the TTS panel, then (2) make the single
drop commit (drop file deliberately NOT deleted and nothing committed until then).
Earlier: the Kokoro-on-macOS §2.4 fix in `bootstrap.py` is live-verified on this
machine and still uncommitted alongside this drop's work. **⚠ This Mac's working copy
has NO `.git` directory** (not a clone — likely copied/zip-transferred), so nothing
can be committed or pushed from this machine as-is; the maintainer must reconcile
these changes onto a real clone. Windows-side drops still pending after this:
Drop 4 (script hardening), then the Windows UI drop.

---

## Open Issues / Bugs

| # | Severity | File | Description | Status | Found by |
|---|----------|------|-------------|--------|----------|
| 1 | Minor | scripts/Universal/shared/bootstrap.py | Drop 3 §2.4 (Kokoro on macOS) — RESOLVED 2026-07-07 on the MacBook. Real root cause: ENVIRONMENTAL, not `kokoro_synth.py`. The venv was built on Python 3.13.7 (the Mac's only Python), but Kokoro's PyPI wheels require >=3.10,<3.13, so the requirements marker skipped the wheel and every self-heal repair failed with "No matching distribution found for kokoro==0.9.4". Fixed in `bootstrap.py`: `run_setup` now installs Python 3.12 before accepting a >=3.13 interpreter (3.13+ kept only as Edge-only fallback), and `_create_validated_venv` rebuilds a >=3.13 venv once a <3.13 base exists. Verified live: 3.12.13 venv, `kokoro_is_healthy` → `(True, 'ok')`. See DECISIONS.md 2026-07-07 ADR. | **Closed — fixed in bootstrap.py** | Claude Code |
| 2 | Minor | scripts/Universal/tts/kokoro_synth.py | CLI-only cosmetic: `kokoro_file_to_mp3`'s default `log=print` emits a `→` character, which raises UnicodeEncodeError on a cp1252-encoded Windows console (found while scripting Drop 3 verification). The GUI is unaffected (logs go through the Tk queue, never stdout). Flagged for review, not fixed — out of Drop 3 scope. | Open — flagged for maintainer | Claude Code |
|   |       |     | (Windows xHE-AAC decode is a documented known limitation, not a bug — see CHANGELOG [0.3.2]. The macOS `aac_at` counterpart decodes AAC-LC fine (verified 2026-07-08) but an actual xHE-AAC/USAC decode on macOS is still unverified — no USAC sample on hand.) | | |

---

## Migration Map — contract for Phase 2 (drop `0.5.0-drop1-restructure-and-docs.md`)

Grounded in the fresh REPO-STRUCTURE.md (2026-07-06 15:56) and the maintainer's answers to all
nine open questions. Windows tree is the canonical source (trees byte-identical except the two
dead legacy files below).

**Program code → `scripts/Universal/`** (git mv from `Windows/scripts/`):
- `mp3_tools/{__init__,cover_resizer,m4b_converter,m4b_maker,m4b_metadata_editor,mp3_tool}.py`
- `shared/{__init__,bootstrap,cancellation,close_terminal,ffmpeg_utils,logging_setup,metadata,paths,release,settings,subprocess_utils,version}.py`
- `tts/{__init__,batch_convert,epub2tts_gui,kokoro_synth,pdf_extractor,voice_registry}.py`
- `tts/epub2tts_edge/{__init__,epub2tts_edge,runner}.py`
- `launcher.py`
- `Windows/requirements.txt` → `scripts/requirements.txt` (single shared; the two files were
  identical except the header comment — maintainer confirmed Q6)

**Deleted, not migrated (maintainer Q2 — confirmed dead, no legacy folder):**
- `scripts/mp3_tools/mp3_tools_launcher.py` (both trees)
- `scripts/tts/setup_env.py` (both trees)

**Dev-only → `files/`:**
- `scripts/tests/test_kokoro_voices.py` → `files/tests/`
- root `test-files/` → `files/test-files/` (stays gitignored — copyrighted media)
- `Windows/test-logs/` → `files/test-logs/` (gitignored)
- `Windows/Dockerfile` → `files/Dockerfile` (maintainer Q3 — dev-only, not a shipped path)
- v0.3.1 one-shot docs (`MACOS-DEBUG-v0.3.1.md`, `MACOS-FIX-REPORT-v0.3.1.md`,
  `WINDOWS-RELEASE-HANDOFF-v0.3.1.md`) → `files/release-history/` (one copy each)
- `files/vibe-coding-templates/` — already in place, unchanged

**Runtime-writable data → `files/runtime-data/` (maintainer Q4; layout chosen by agent):**
- `<OS>/resources/logs/` → `files/runtime-data/logs/` (gitignored; old log files not carried —
  runtime-generated)
- `<OS>/resources/settings.json` → `files/runtime-data/settings.json` (gitignored; Windows copy
  wins if the two diverge — it is the actively-used one)
- `Windows/resources/models/huggingface/` (Kokoro-82M cache, ~300 MB) →
  `files/runtime-data/models/huggingface/` (gitignored, never committed; answers Q5 — this is
  the ONE canonical in-repo cache path for `bootstrap.py`/`launcher.py`/`kokoro_synth.py`)
- `resources/bin/` concept (portable ffmpeg fallback) → `files/bin/` (the AI-WORKSPACE-standard
  home for setup-downloaded binaries; gitignored)
- Implementation: repoint `RESOURCES_DIR`-style constants in `paths.py` / `bootstrap.py` once;
  keep the internal `logs / models / settings.json` names so the diff stays minimal.

**md-instructions — two sets collapse into one root set:**
- `Windows/md-instructions/{Briefing,CHANGELOG}.md` + identical MacOS copies → one
  `md-instructions/{Briefing,CHANGELOG}.md` (byte-identical today, verified by diff — merge is
  trivial; then rewritten per Phase 3)
- New: `DECISIONS.md`, `Instructions_Template.md` (from `files/vibe-coding-templates/`)
- This `handoff.md` is already at its final location

**Entry points (maintainer Q1 + Q7):**
- Root launchers renamed to exactly `Setup_and_Run-audiobook-creation-tool.bat` /
  `Setup_and_Run-audiobook-creation-tool.command` (Phase 5). These stay the ONLY user-facing
  entry files.
- Fast path stays `bootstrap.py --launch-only` (self-heal on every launch preserved exactly),
  repointed to `scripts/Universal/shared/bootstrap.py`. No `cd` into `Windows/`/`MacOS/`.
- Preserve untouched: Windows `pythonw.exe` no-console fast path, macOS Gatekeeper/App
  Translocation guard, Kokoro/venv/ffmpeg self-heal. `.venv` moves to the repo root (the
  AI-WORKSPACE location) since the per-OS trees disappear.

**Other maintainer decisions:**
- Q8: create `.codex/` (CODEX.md pointer to AI-WORKSPACE.md + settings) — Codex is used.
- Q9: README gets a short v0.5.0 status line (internal restructure, no feature changes); keep
  v0.4.0 download links until a v0.5.0 release is published.
- Pending master edits (console-flash fix + AI-WORKSPACE.md) committed on master as `e80ba7f`
  BEFORE branching, so the restructure branch contains only restructure work.

**Drift found vs the drop's assumptions (reality followed, per drop rules):**
- The "loose root handoff.md" no longer exists; `md-instructions/handoff.md` was a blank
  template (no live state to migrate from it — live state reconstructed from the v0.3.1
  one-shots + CHANGELOG).
- Empty `scripts/{Universal,Windows,MacOS}/`, `md-instructions/`, and `files/` skeletons were
  pre-created by the maintainer before this session.
- Working tree had uncommitted `[Unreleased]` changes on master (handled above).
- `dist/` (gitignored release zips) stays at root — `release.py` writes there by design.

---

## Work Log (newest first)
- 2026-07-31 — v0.6.0 Drop 1 **Phase 3 complete** (HOME-PC session; per-phase commit on
  the implementation branch). Converted the **Windows M4B Metadata Editor** — the only
  tool panel this plan may ever convert — and built the visual specimens.
  `m4b_metadata_editor.py` now forks on `theme["mode"]`: `_build_ui_windows()` draws four
  titled cards (Audiobook Files, Shared Metadata, Chapter Titles, Output) in a scroll
  region, with an action bar and a Log that never scroll away; `_build_ui_classic()` is
  the old layout kept byte-for-byte for macOS and Linux/other. **Both forks create the
  same widgets and attributes**, so every callback, worker, queue pump, busy/idle
  transition, Cancel path and copy-only write below the builders is shared code that
  cannot tell them apart — no metadata, output, threading or cancellation behaviour was
  touched. `build_ui(parent)` is unchanged; it gained an optional, backwards-compatible
  `theme=None` parameter (the launcher still calls it with one argument).
  **Shared Metadata** groups every batch-wide field on the Phase 1 accent surface. Every
  one of those fields already applied to every loaded file, so the card states existing
  behaviour visually — it adds no precedence, disables no field, and implements nothing
  from Plan 6/8. **Summary/Details is deliberately NOT in the runtime editor** (that
  would be a non-functional control in a user-facing panel); it is a component sheet in
  the new developer-only fixture, labelled in its own text as presentation-only with no
  filtering/ETA/Retry/Pause-Resume — all Plan 3.
  `files/tests/manual_windows_ui_prototype.py` is the fixture: not pytest-collectable,
  not in `launcher.TOOLS`, not under `scripts/`, patches nothing (it drives the editor's
  own public methods with canned in-memory data), and touches no file on disk. All four
  isolation properties are asserted by a test.
  **The approved `sidebar_width` 232 → 180 shipped with it** and gave every tool panel
  +52px of width back: content host 669×457 → **721×457** at the minimum and 773×577 →
  **825×577** at the default. Widest nav row is 115px in a 160px interior, so the rail is
  still comfortable. **Half the Phase 2 regression is fixed and half is not, and the
  split is exactly width vs height:** at 1024×720 M4B Converter's `Convert M4Bs → MP3s`
  row and Log are fully visible again (measured, mapped, inside the host); at the 920×600
  minimum they are still clipped by ~19px and ~110px, because that deficit is vertical
  and `MIN_SIZE`/`DEFAULT_GEOMETRY` were left alone per the maintainer's decision.
  Tests: new `test_m4b_metadata_editor_ui.py` (12), `test_ui_theme.py` 16 → 17,
  `test_launcher_smoke.py` 10 → 11, full suite 68 → **82 passed, 3 skipped**.
  `ui_theme.py` gained four styles only — `ACT.Shared.TFrame`, `ACT.Shared.TLabel`,
  `ACT.SharedSecondary.TLabel`, `ACT.Shared.TCheckbutton` — so the Shared Metadata
  surface has its own frame/label/toggle family instead of borrowing the "muted" one,
  whose token merely happens to be the same colour today. `launcher.py` was **not**
  edited. Draft review at 1024×720 / 920×600 / maximized, including a measured 31-stop
  Tab loop with no trap (scratchpad images, not committed).
- 2026-07-31 — v0.6.0 Drop 1 **Phase 2 complete** (HOME-PC session; per-phase commit on
  the implementation branch). Converted the **Windows launcher shell only**:
  `_build_ui_windows()` in `launcher.py` builds a dark navigation rail, a header strip
  naming the active tool, a framed content card and a status bar with a focusable
  "Open log folder" button — all from `theme["styles"]` / `theme["colors"]` /
  `theme["metrics"]`, so not one hex literal or magic number entered `launcher.py`.
  `shared/ui_theme.py` was **not** edited: the Phase 1 API (41 styles + `style_tk_widget`)
  covered the whole shell, which is the strongest evidence the design system is right.
  `files/tests/test_launcher_smoke.py` grew from 1 test to 10.
  **The isolation trick that matters:** `self.content` and every per-tool container are
  left as *plain, unstyled* `ttk.Frame`s. ttk has no style inheritance, so an unconverted
  panel resolves the generic `TFrame`/`TButton`/`TEntry` exactly as it does on master —
  the shell cannot leak into a panel even in principle, because there is nothing to
  inherit from. The card border is a 1px hairline frame wrapped *around* the host rather
  than a style *on* the host, which is what buys the border without giving the host a
  style. Verified in the running app: zero of the panels' widgets carry an `ACT.*` style
  while every non-empty style in the shell itself is `ACT.*`.
  Two behaviour changes, both deliberate and both improvements: the active nav row is
  marked with the ttk `selected` flag instead of being *disabled* (so it stays reachable
  by Tab and keeps its focus ring), and the log-folder action became a real `ttk.Button`
  instead of a clickable label (focusable, fires on Enter/Space). The action itself,
  `_open_logs`, is unchanged.
  **Regression found and escalated rather than papered over:** the new shell costs the
  tool panels 127px of width and ~100px of height against the classic shell (110px of
  that is the 232px `sidebar_width` token). At the 920×600 minimum the M4B Converter's
  `Convert M4Bs → MP3s` row and Log box fall outside the visible area, where on master
  they fit. I reclaimed everything reclaimable inside `launcher.py` (card padding
  `content_pad` → `gap_sm`, +16w/+12h) and stopped there: the two real levers are
  `sidebar_width` and `MIN_SIZE`, both in `shared/ui_theme.py`, and both are maintainer
  value/geometry decisions under plan §7.1–§7.2 — not a "missing primitive" this phase
  was authorized to add. Full numbers, per-panel overflow, and three costed options are
  in *Phase 2 limitations* above. Worth noting for context: M4B Converter, MP3 Tool and
  M4B Maker already overflow at 920×600 on master, so this makes an existing condition
  worse rather than creating a new class of bug.
  Draft visual review done at 1024×720, 920×600 and maximized 1920×1009 on this machine
  (scratchpad images, not committed — the ten-image 100%/125% matrix is Phase 5).
- 2026-07-31 — v0.6.0 Drop 1 **Phase 1 complete** (HOME-PC session; per-phase commit on
  the implementation branch). Built the isolated Windows design system in
  `shared/ui_theme.py` and extended `files/tests/test_ui_theme.py` from 5 tests to 16.
  **Converted nothing** — the launcher and all six panels are untouched, and a live
  style audit through the real `LauncherApp` proves it (297 widgets, every one with an
  empty style string; generic ttk styles still resolve to the native vista values).
  Key engineering decision: keep `vista` as the base theme and clone the recolorable
  `clam` elements into it under an `ACT.` prefix, because vista's native parts ignore
  colour options and a global switch to `clam` would have restyled the five panels this
  drop must not touch. Probed the actual Tk 8.6 build in the repo venv to confirm
  `element create … from clam` works for all 28 required elements before writing any
  production code. Every style variant gets an explicit layout, otherwise ttk resolves
  e.g. `ACT.Primary.TButton` down to the native `TButton` and the dark fill silently
  does not stick — that trap is documented in the module and in Current Focus above.
  Also added `style_tk_widget()` as the single sanctioned way to colour `Canvas` /
  `Listbox` / `Text`, so no panel ever carries its own hex literal.
  **Diagnostic-notice investigation** (requested before editing): the two earlier IDE
  notices — "70 new diagnostic issues in 1 file" and "26 new diagnostic issues in 1
  file" — were **Markdown editor-linter notices, not Python or source errors**. They
  fired while `md-instructions/handoff.md` and the drop plan were being written in
  Phase 0 (line-length / list-spacing style rules). `mcp__ide__getDiagnostics` now
  reports **zero** diagnostics for the whole workspace, including
  `handoff.md`, the drop file and `shared/ui_theme.py`, and
  `python -m compileall scripts files/tests` exits 0 with no output. No baseline source
  problem exists and nothing was broadened to "fix" them.
  Results: focused theme suite 16 passed; launcher smoke 1 passed; metadata shared
  7 passed; full suite 59 passed / 3 skipped / 1 warning; `verify.py` **RESULT: PASS**;
  `git diff --check` clean. `requirements.txt`, `version.py` (still `0.5.1`), both setup
  launchers and every tool module are unchanged. Stopped at the Phase 2 approval gate.
- 2026-07-31 — v0.6.0 Drop 1 **Phase 0 complete** (HOME-PC session; committed and pushed
  on the implementation branch per the plan's per-phase commit contract, which
  supersedes the v0.5.0-only one-commit-per-drop rule). Read order completed first:
  AI-WORKSPACE.md, Briefing, CHANGELOG, DECISIONS, handoff, the full drop file, and
  `.claude/skills/audio-processing/SKILL.md` (present and read; `fullstack-bridge-sync`
  inspected and correctly not applicable — no backend/frontend contract work here).
  Worktree protection: the checkout carried an unstaged deletion of
  `md-instructions/Instructions_Template.md` plus untracked `Map-Repo-Structure.bat`,
  `REPO-STRUCTURE.md`, and the new drop file. All four were copied to a scratch backup
  **before** touching git; nothing was reset, discarded, stashed, or overwritten. The
  incoming history deleted `Instructions_Template.md` itself (`9dcf49c`), so the
  fast-forward absorbed the local deletion with a zero net diff, and `220b6dc`/`65d3855`
  added `.gitignore` rules that now cover both convenience tools — `git check-ignore`
  confirms `Map-Repo-Structure.bat` (line 75) and `REPO-STRUCTURE.md` (line 59).
  Sync: `git fetch --prune` then `git pull --ff-only origin master` — 10 commits,
  `695045c..1da1e54`, strictly fast-forward (verified with `git merge-base --is-ancestor`
  before pulling). Start SHA `1da1e547ce85d6e5c8a5b34fb549ffa8b93f6318` **equals** the
  plan's planning-audit baseline, so no drift analysis was needed; the incoming diff
  was the v0.5.1 Jenny line, the 8 `files/UI-Current-Screenshots/` images, gitignore
  hardening, and docs. Branch `feature/0.6.0-drop1-windows-ui-prototype` cut from the
  updated master. Baseline (all with the repo venv, Python 3.12.10, **no source
  edits**): focused suites 5 / 1 / 7 passed; full suite 48 passed, 3 skipped;
  `scripts/verify.py` → **RESULT: PASS**; `git diff --check` clean. Six-tool manual
  baseline driven on a real Tk window through the real `LauncherApp`: 6/6 registered in
  order, zero error panels over two full passes, container identity stable (build-once
  proven), a state marker survived switch-away/back, `last_tool` round-tripped, 1.601 s
  build-all, window `1024x720`/minsize `(920,600)`. Pre-prototype Windows theme contract
  captured verbatim (`mode="classic"`, vista, Segoe UI, `colors=None`, `metrics=None`) —
  that `None` pair is the Phase 1 target. **Nothing was converted, restyled, or
  redesigned.** Limitations recorded above rather than glossed: no eyes-on visual check,
  no live macOS, and the `md-instructions/` case-rename left alone because `verify.py`
  hard-codes `CHANGELOG.md` and this drop may not weaken or edit the gate. Next: Phase 1
  (Windows design primitives only) — **awaiting explicit user approval**. — Claude Code
- 2026-07-19 — Batch-timing-parity drop ABANDONED + Jenny addition shipped to branch
  (MacBook session). Maintainer listened to all six Phase-3 A/B pairs: the rewritten
  batch engine, despite median-gap parity within −22…0 ms, sounded subjectively worse
  than the original chunk method — full working-tree revert ordered and executed
  (nothing was ever committed). Surgical handling: voice_registry.py hand-reverted
  (batch_timing_preset field, effective_preset(), _batch_override(), six overrides
  and Phase-3 comments removed; Jenny's entry restored verbatim to her original
  addition incl. original comment); test_tts_smoke.py kept the 12/7 counts but lost
  the effective_preset contract test; plain `git checkout` (diffs verified pure
  Phase-2/3 first) for batch_convert.py (banner fix reverted with it),
  epub2tts_gui.py, epub2tts_edge.py + runner.py (rate kwarg), and
  test_batch_convert_folders.py (back to the original 5 fake-synth tests);
  batch_convert_child.py + batch_timing_harness.py deleted; batch-baselines/ +
  phase3-listen/ investigation data deleted (Jenny's pre-drop samples kept);
  Instructions_Template.md restored from HEAD (deleted only as a side effect of
  drop-file creation — same precedent as Drop 3). Docs: DECISIONS do-not-retry ADR;
  CHANGELOG revert note + 0.5.1 entry; Briefing pause-fields accuracy fix + version
  line; version.py 0.5.0 → 0.5.1; drop file batch-timing-parity.md deleted last.
  verify → RESULT: PASS. Committed as ONE commit on new branch `add-jenny-voice`
  (Jenny addition + docs/version + revert record), pushed to origin; master
  untouched — maintainer does the Windows verify + merge. — Claude Code
- 2026-07-19 — Batch-timing-parity drop Phase 3 DONE (MacBook session; no commit per
  drop). Per-path presets prototyped per maintainer option (a): registry field
  `batch_timing_preset` (partial dict, None default) + `effective_preset(v, mode)`
  merge helper + `_batch_override()` factory; GUI `_on_voice_selected` now loads
  the effective preset for the current mode and both mode radios re-invoke it
  (lambda for late binding — the radios are built before the handler exists).
  Harness renders batch with the effective batch preset and records the merged
  preset in its JSON. Tuning: two measured iterations (first pass undershot
  medians ~45 ms — the trim residual measured at presets 780–820 shrinks at
  340–640, so Phase-2's implied values were systematically tight); final values
  land every non-Jenny voice within −22…0 ms of its old-batch ch1-1 median.
  Title/chapter batch overrides = 0 (beyond the maintainer's given sentence
  numbers, flagged): the old batch never inserted them, and with 0 the title gap
  is the voice's natural residual — intro title gaps landed within 5–64 ms of old
  batch for five voices (Steffan +113, his residual runs long), trails within
  ±60 ms. Choppiness check for the low-preset voices (AndrewM 423 / Andrew 410 /
  AvaM 373 / Ava 344): new minimum gaps are HIGHER than old batch's own natural
  minimums (e.g. Ava 375 vs 218, Steffan 363 vs 232) — the preset acts as a floor;
  remaining sub-200 ms gaps are comma-scale, present in old batch too. No numeric
  sign of clipping; agent cannot literally listen — old-vs-new A/B samples for all
  six voices staged in files/livid-lady-test-files/phase3-listen/ for the
  maintainer's ear gate. Tests: new per-path merge + single-file-verbatim contract
  test in test_tts_smoke (50 passed / 3 skipped); verify RESULT: PASS. — Claude Code
- 2026-07-19 — Batch-timing-parity drop Phase 2 DONE (MacBook session; no commit per
  drop). Engine change per the Phase-1 decision: `convert_single_pdf` rewritten to
  spawn `batch_convert_child.py` (new, ~68 lines) via `shared.subprocess_utils.popen`
  — child installs the no-window guard + configure_pydub + ensure_punkt itself
  (fresh process), turns SIGTERM into SystemExit so the engine's finally cleans its
  temp dir, renders into a private absolute dir under `.tmp_chunks/<tmp_key>`
  (existing orphan-cleanup covers it), prints `BATCH_CHILD_SAVED::` on success;
  parent moves `<stem> (<voice>).mp3` onto the mirrored target. Cancel: parent polls
  cancel_check every 0.5 s and terminate()s the child (grace 10 s then kill) — faster
  than the old between-chunk checkpoint; per-PDF retry loop unchanged around the
  spawn; network retry lives in the engine (run_edgespeak 3×, finer than the old
  per-chunk retry); per-file progress_report unchanged; child stdout pumped on a
  thread, only retry/error-ish lines forwarded (log stays as quiet as the old
  pipeline), full tail kept for failure messages; `-X utf8 -u` on the child guards
  the cp1252-console issue (Open Issues #2 class). `run_batch_convert` gained
  mp3_bitrate + 7 optional pause kwargs (None → engine defaults, engine stays the
  single source of truth). GUI: pause_kw now built for batch too (validation dialog
  now also fires on bad pause fields at batch start — new, correct) and passed with
  bitrate into run_batch_convert; Kokoro single/batch paths untouched. Harness
  updated to pass each voice's preset pause fields (same mapping as the GUI) and
  self-describe the engine in its JSON. Tests: fake seam moved from
  synthesize_chunk_mp3 to `_delegate_to_child`; same five scenarios preserved
  (same-stem test no longer needs fitz — parent never parses PDFs) + new
  pause-threading, engine-defaults, and cancel tests (5→8). Proofs: single-file
  intro render on new code millisecond-identical to reference (20.215 s /
  961-942-949 ms gaps); live workers=2 batch 2/2 mirrored, 0 orphans; cancel drill
  clean; verify RESULT: PASS (49/3). Measured new engine on all 7 voices × 2
  sources → phase2-newengine.json; conflict numbers recorded in Current Focus.
  — Claude Code
- 2026-07-19 — Batch-timing-parity drop Phase 1 DONE (MacBook session; no commit per
  drop). Traced GUI batch invocation: in batch mode `pause_kw` is never built
  (epub2tts_gui.py:462 gates it on mode=="single"); Edge batch receives only
  speaker/rate/workers/resume, though every pause Tk var is readable on the main
  thread at start_job — threading them through is pure plumbing. Kokoro batch is an
  inline GUI loop (lines ~534–649), not `run_batch_convert` — out of blast radius.
  Chose subprocess-per-file delegation after disproving in-process thread delegation
  live (chdir race: 2/2 runs failed — `sntnc*.mp3` written/read across the wrong tmp
  dirs, CouldntDecodeError, one thread's finally-chdir targets a dir the other
  rmtree'd) and sizing the chdir-free refactor as too invasive (~30 bare relative
  filenames in read_book/make_mp3/make_m4b). Prototype (scratchpad) proved the
  delegated shape: child renders to a private absolute dir, parent moves
  `<stem> (voice).mp3` to the mirrored target; workers=1 real PDF + workers=2 nested
  same-stem TXT tree both correct, cwd stable, delegated gaps == single-file
  reference (961/942/949 ms). Built `scripts/Universal/tts/batch_timing_harness.py`
  (renders via the real `convert_single_pdf`, measures gaps with pydub at
  −50 dBFS/150 ms, writes JSON) and captured baselines: 7 Edge voices ×
  {00-intro, 03-ch1-1} → batch-baselines/phase1-baseline.json; variance run shows
  Edge is deterministic (±2 ms), so ±25 ms tolerance is real. Surprise flagged: batch
  medians (Steffan ~770, Jenny ~1000, Andrew ~452 ms) sit far from single-file
  measured gaps at the same presets (Steffan ~951 ms), so Phase 3's "match old batch"
  and "don't change single-file" conflict under one shared preset — maintainer input
  needed on resolution (per-path preset values vs. accepting single-file cadence in
  batch). verify → RESULT: PASS. — Claude Code
- 2026-07-08 — UX-progress drop Phase 5 — DROP DONE (MacBook session; no commit —
  no .git here; drop file NOT deleted per maintainer instruction). Maintainer
  approved the Phase-4 metadata layout visually (scroll, larger Log, description,
  progress). Close-out gates: full suite 46 passed / 3 skipped;
  `python scripts/verify.py` → RESULT: PASS. Windows/classic proof: launcher
  constructed under a win32 stub scoped to ui_theme's sys reference (a global
  sys.platform stub breaks stdlib shutil — same technique as the UI-shell drop):
  theme mode "classic", family "Segoe UI", colors/metrics None, 6 plain ttk.Button
  sidebar entries, all six tools built through the real LauncherApp with zero error
  panels, settings.json snapshot/restored. Docs: CHANGELOG [Unreleased] gained the
  UX-progress Added + Changed entries; Briefing updated (ui_theme bullet gains
  ProgressIndicator, worker/data-flow bullet gains the progress-marshaling rule,
  metadata-editor bullet gains the scroll layout + 14-row Log); DECISIONS gained
  the progress-placement + Maker-indeterminate ADR; handoff (this file — focus,
  work log, sync log). Awaiting maintainer final sign-off and the single drop
  commit; the maintainer deletes the drop file at commit time (or asks for it to
  be deleted then). — Claude Code
- 2026-07-08 — UX-progress drop Phases 1–4 done; STOPPED at the Phase-4 visual gate
  (MacBook session; no commit — no .git here). Phase 1 re-run after a context clear:
  confirmed no prior Phase 2/3/4 work existed on disk before starting. Phase 2:
  `ProgressIndicator` in shared/ui_theme.py + test_ui_theme.py test. Phase 3 per tool —
  M4B Converter/Cover Image: existing queue "progress" payload widened to (done, total),
  bar swapped for the indicator (determinate, per file/image); M4B Metadata: same for
  all three workers (save / clear-tags / remove-numbering; determinate per file);
  M4B Maker: indeterminate during the single concat/encode, 1/1 on success (old bar was
  dead — value 0 until one end-jump; dead "progress_max" pump branch removed);
  MP3 Tool: new indicator + queue kinds — combine determinate per track in SAFE
  normalize, indeterminate "Concatenating…" during FAST/final concat, time-edit + ID3
  determinate per file; TTS: indicator beside Start/Cancel, Edge/Kokoro batch per-file
  counts, Kokoro single per-chunk and Edge single per-paragraph via new additive
  progress_callback=None params (kokoro_synth.py, epub2tts_edge.py read_book,
  runner.py) — defaults keep all non-GUI callers byte-identical in behaviour. All
  updates flow worker→queue→main-thread drain (same path as each Log box); Cancel and
  Log wiring untouched on every tool. Phase 4: metadata editor scroll canvas mirroring
  the TTS wiring exactly, Log 8→14 rows fixed below the scroll area, launcher
  description de-staled. Gates: compileall clean; suite 46 passed / 3 skipped
  (test_launcher_smoke builds all 6 tools); real-Tk behavioural check of the new
  layout (canvas window, %d Leave bind, log row, busy/idle toggle) passed. NOT done
  (deliberate): Phase 5 close-out — waits for the maintainer's visual sign-off on the
  metadata editor. — Claude Code
- 2026-07-08 — Component-verify drop Phases 4–5 — DROP DONE (MacBook session; no commit —
  no .git here; drop file NOT deleted per maintainer instruction). **Phase 3 gate:**
  maintainer listened to all 11 samples and approved. **Phase 4 (per-tool live pass) —
  PASS:** all six tools exercised end-to-end on macOS under the new Finder shell and
  confirmed working by the maintainer (screenshots reviewed): TTS Audiobook (Edge +
  Kokoro voices, pause-timing fields effective, panel scrolling works), M4B Converter,
  MP3 Tool, M4B Maker, Cover Image, M4B Metadata Editor (Drop 2 shared-metadata
  pre-fill + "(varies)" + Open Folder…). No macOS-specific breakage found — zero code
  changes, so no new regression tests were needed. Caveat recorded everywhere: the M4B
  Converter ran against a standard AAC-LC M4B; the `aac_at` xHE-AAC/USAC decode path is
  still unverified on macOS (no USAC sample on hand). **Phase 5 (close-out):** full
  suite 45 passed / 3 skipped; `python scripts/verify.py` → RESULT: PASS. Docs:
  CHANGELOG [Unreleased] component-verify Verified entry; Briefing macOS-live-pass
  known-limitation bullet retired (replaced by the narrow xHE-AAC-on-macOS residual,
  folded into the Windows xHE-AAC bullet) + High-Level State notes the macOS live pass;
  handoff (this file — focus, open-issues note, work log, sync log). Open Issues #1 was
  already closed 2026-07-07; no DECISIONS ADR needed (no new aac_at/MPS decision arose —
  decoder selection pre-existed in ffmpeg_utils.py). Awaiting maintainer sign-off and
  the single drop commit. — Claude Code
- 2026-07-08 — Component-verify drop Phases 1–3 (MacBook session; no commit — no .git here).
  **Phase 1 (kickoff gates) — PASS:** venv Python 3.12.13; edge-tts 7.2.8 imports;
  `kokoro_is_healthy(venv_python())` → `(True, 'ok')`; real `.command` fast-path launch OK
  (Kokoro health-check ok, GUI detached, launch log clean); test instance closed (a
  pre-existing maintainer launcher window from 04:03 was left running). **Phase 2 (§2.4):**
  treated as CLOSED per maintainer — fixed 2026-07-07 in bootstrap.py (environmental: 3.13
  venv; now forced 3.12), `kokoro_synth._get_pipeline` untouched; only the health check was
  re-run. **Phase 3 (voice samples):** `tts/generate_voice_samples.py` run on macOS →
  11/11 OK (6 Edge + 5 Kokoro) in `files/test-for-manual-listen-elmatthe/`. STOPPED at the
  maintainer manual-listen gate; Phase 4 (per-tool live pass) starts only after sign-off.
  — Claude Code
- 2026-07-08 — Wheel/trackpad scroll fix + UI-shell drop Phase 5 close-out (MacBook
  session; maintainer approved the Finder look first; no commit — maintainer makes the
  single drop commit after live-testing scroll). **Scroll fix:** the TTS options panel
  never scrolled on wheel/trackpad (only scrollbar drag worked) — pre-existing bug in
  SHARED code, so the fix improves Windows and macOS alike. Root cause: the wheel
  handler was armed by Enter/Leave on `options_canvas`, but the form frame covers the
  canvas, so the canvas Enter almost never fired. New
  `shared.ui_theme.enable_mousewheel(scroll_target, hover_region)` binds Enter/Leave
  on the panel's wrap frame instead and ignores Leave-with-detail-NotifyInferior
  (pointer into a child = still inside the panel). CRITICAL non-obvious bit: tkinter's
  bind() never delivers the crossing detail (`%d` absent from `Misc._subst_format_str`
  — verified live on Tk 9.0.3), so the Leave side is a Tcl-level bind; see the
  2026-07-08 DECISIONS ADR before "simplifying" it. `epub2tts_gui.py` now calls
  `enable_mousewheel(options_canvas, hover_region=canvas_wrap)` (old inline handler
  removed). All-scrollers sweep: every other scroller (M4B Converter / MP3 Tool /
  M4B Maker / Cover Image / M4B Metadata Listbox + Text/ScrolledText widgets) already
  scrolls natively via Tk class bindings — verified live with synthetic MouseWheel
  events — so NONE needed the helper; none were touched. Verified end-to-end on the
  real TTS panel (real Tk): Enter-on-wrap arms bind_all, wheel over a child Entry
  scrolls the canvas, Leave(NotifyInferior) keeps the binding, real Leave unbinds;
  same flow re-proven under the classic/win32 path (ui_theme-scoped platform stub —
  stubbing sys.platform globally breaks stdlib shutil) incl. Windows ±120 deltas.
  **Phase 5:** `test_ui_theme.py` gained the headless-guarded `enable_mousewheel`
  wiring test (asserts Enter/Leave bound + Tcl-level %d on the Leave script; wheel
  motion itself can't be simulated headless). Full suite 45 passed / 3 skipped;
  `python scripts/verify.py` → RESULT: PASS. Docs: CHANGELOG (UI shell Added + scroll
  Fixed), Briefing (GUI/launcher/shared bullets + macOS-live caveat narrowed to the
  per-tool matrix), DECISIONS (aqua-vs-clam ADR deferred from Phase 3 + wheel-binding
  ADR). Drop file NOT deleted, nothing committed — both deliberate, awaiting the
  maintainer's live scroll test and single drop commit. — Claude Code
- 2026-07-08 — macOS UI-shell drop Phases 1–4 done (MacBook session spanning the
  07-07→07-08 midnight; no commit — awaiting maintainer UI review before Phase 5).
  **Phase 1** — AI-WORKSPACE.md → HOME-MacOS filled from the real machine: root
  `~/Desktop/Coding_Repositories` (claude-skills-main inside it, no MyProjects split),
  MacBook Pro 14" M4 Pro (14c) · 24 GB · macOS Tahoe 26.5.2 · 1 TB (~466 GB free),
  user `elijahmatthew` = Administrator (sudo w/ password), brew python@3.12+3.13 with
  Tk, default python3 = 3.13.7; noted TCC blocks agent shells from listing ~/Desktop.
  **Phase 2 (baseline launch gate) — PASS**: deleted `.venv`, invoked the real
  `.command` via Finder-equivalent `open`. First-run setup: correct 3.12 base chosen
  (the §2.4 fix working), venv built, all pinned deps installed, ffmpeg on PATH,
  Kokoro model + voices ready (setup_2026-07-07.log, run marker 23:48:28). Caveat:
  the setup window's final auto-launch step wasn't observed (window was closed
  on-screen right at the end — agent shells here have no Accessibility permission,
  so the "Begin Setup" click and window handling happened at the physical machine);
  launch itself was then proven via the `.command` fast path: Kokoro health-check ok,
  GUI on screen detached, Terminal auto-closed promptless, session log clean.
  Health: edge-tts 7.2.8 imports, kokoro_is_healthy → (True, 'ok'), 11 voices
  (6 Edge + 5 Kokoro). Logs: files/runtime-data/logs/{setup_2026-07-07.log,
  launch_2026-07-07.log, launch_2026-07-08.log}.
  **Phase 3** — `scripts/Universal/shared/ui_theme.py` added (apply_theme(root, style)
  → fonts/colors/metrics dict). Research done live on this Mac (Tk 9.0.3): native
  `aqua` chosen over Finder-styled clam (native controls in all six panels, auto
  dark-mode — this Mac runs dark mode; aqua can't recolor native ttk buttons, so the
  sidebar chrome uses classic tk widgets); fonts via `.AppleSystemUIFont` (SF Pro
  Text/Display are NOT installed font families on Tahoe), fallback Helvetica Neue;
  macOS semantic system colors + computed blends (alpha colors flatten in Tk).
  DECISIONS.md ADR deferred to Phase 5 per drop. win32/other branch reproduces the
  old look byte-identically (vista/Segoe UI; clam/TkDefaultFont). Headless-guarded
  `files/tests/test_ui_theme.py` added (3 tests: current platform, stubbed win32
  values, stubbed linux) — pass.
  **Phase 4** — launcher.py wired to ui_theme.apply_theme(); `_build_ui` split into
  `_build_ui_classic` (old body verbatim — Windows tree unchanged) and
  `_build_ui_darwin` (Finder shell: tinted source-list sidebar w/ hover +
  accent-selection rows + emoji glyphs, toolbar strip naming the active tool +
  description, hairline-bordered content card, refined status bar w/ system link
  color). `build_ui(parent)` contract, lazy build-once/show-hide, last_tool restore,
  load-error panel, `_on_close` all untouched; the six tools' internals untouched
  (only launcher.py edited + ui_theme.py/test added). Verified: compileall clean;
  test_launcher_smoke (6/6 tools through the real LauncherApp on the new shell) +
  test_ui_theme pass; scoped win32-stub constructs the classic layout (6 ttk
  buttons); darwin behavioral check (selection/hover/toolbar/build-once) pass; real
  `.command` fast-path launch with the new UI confirmed on screen and left open for
  review. NOT done yet (deliberately): Phase 5 bug hunt, full verify.py run, doc
  close-out, DECISIONS ADR, drop-file deletion, commit. — Claude Code
- 2026-07-07 — §2.4 Kokoro-on-macOS root-caused and FIXED (MacBook session; no commit —
  maintainer reviews first). Live diagnosis: `.venv` was Python 3.13.7 (the Mac's only
  Python — no python3.12 anywhere), and the setup log showed pip skipping kokoro
  (`markers 'python_version < "3.13"' don't match`) then every self-heal repair dying on
  "No matching distribution found for kokoro==0.9.4" (newest 3.13-compatible release on
  PyPI is 0.7.16). ENVIRONMENTAL — `kokoro_synth.py` untouched. Three `bootstrap.py`
  changes: `_is_kokoro_compatible()` helper (single source of the >=3.10,<3.13 range);
  `run_setup` now calls `install_python` when the found interpreter is >=3.13 and only
  keeps it if 3.12 truly can't be installed (logs "Edge TTS works, Kokoro voices
  disabled"); `_create_validated_venv` rmtree-rebuilds an existing >=3.13 venv when the
  chosen base is <3.13 (closes the "bad venv reused forever" gap). Windows path
  unaffected (`py -3.12` is found directly, branches never fire). Verified live: brew
  python@3.12 + python-tk@3.12 installed, old venv deleted, full headless setup → venv
  Python 3.12.13, ssl=True tkinter=True, kokoro==0.9.4 installed,
  `kokoro_is_healthy(venv_python())` → `(True, 'ok')`. New test
  `files/tests/test_bootstrap_python_version.py` (7 params over the version gate,
  pure logic). `python scripts/verify.py` → RESULT: PASS (41 passed, 3 skipped).
  Docs: CHANGELOG macOS-verify entry, DECISIONS ADR, Open Issues #1 closed. — Claude Code
- 2026-07-07 — Drop 3 complete — DROP 3 DONE (no commit yet — maintainer reviews then
  makes the single drop commit). Per `drop3-plan.md` (deleted on close-out):
  **Phase 1** — batch Kokoro now passes `end_silence_ms=end_pause` (was baking the 3000 ms
  default); `chunk_pause_ms=50` kwarg anchor confirmed pre-existing, untouched.
  **Phase 2.1** — `paragraph_pause` hoisted on the main thread next to `end_pause`
  (never read Tk vars off-thread) and passed as `chunk_pause_ms` into BOTH the
  single-file and batch `kokoro_file_to_mp3` calls. Sentence/title/chapter parity
  deliberately deferred — ADR added to DECISIONS.md.
  **Phase 2.2** — `run_batch_convert` + the GUI Kokoro batch now mirror each source's
  path relative to the input dir under the output dir (same-stem files in different
  subfolders no longer overwrite); Resume checks the mirrored target; per-file temp
  chunk dirs keyed off the relative path (they collided on stem too); flat inputs
  keep the exact old flat layout. **Phase 2.3** — batch discovers `.txt` alongside
  `.pdf` on both engines; `.txt` is read directly (PDF extractor bypassed — the GUI
  Kokoro `_do_one` needed the same suffix branch, a necessary deviation from the
  plan's "label + glob only" wording since `pdf_to_txt` would fail on `.txt`);
  labels updated. **Phase 2.4** — BLOCKED (see Open Issues #1): needs a real Mac.
  **Phase 3.1** — `tts/generate_voice_samples.py` added per plan verbatim (only
  change: removed the plan's unused `import tempfile`); output folder gitignored;
  live run 11/11 voices OK. **Phase 3.2** — 8 new tests in
  `test_batch_convert_folders.py` (5: mirroring / same-stem PDFs via fitz / txt
  bypasses extractor / flat regression / mirrored resume; fake `synthesize_chunk_mp3`,
  no network) + `test_kokoro_timing_wiring.py` (3: fake `_get_pipeline`; duration
  deltas prove `end_silence_ms`/`chunk_pause_ms` are applied). **Phase 3.3** — Edge
  pause scaling verified live (small 10 269 ms vs large 23 769 ms — scales, no
  escalation needed). Extra live QA: real-model Kokoro single-file (chunk 200→2000 ms
  = exactly +1800 ms; end 0→3000 ms = exactly +3000 ms) and a real-Tk GUI smoke
  driving the actual panel (batch radio → voice combobox event → spinboxes → Start)
  over nested txt+pdf with same-stem books: mirrored tree, no collisions, 4/4 outputs.
  Gates: compileall scripts/Universal + files/tests clean; `python scripts/verify.py`
  → RESULT: PASS (34 passed, 3 skipped; 1 pre-existing pydub audioop warning).
  Docs: CHANGELOG Drop 3 entries, Briefing TTS bullet, DECISIONS pause-mapping ADR.
  — Claude Code
- 2026-07-07 — Drop 2 Phase QA + close-out complete — DROP 2 DONE (no commit yet —
  maintainer reviews then makes the single drop commit). `files/tests/
  test_jack_ryan_final_product.py` added (env-gated on JACK_RYAN_M4B_FOLDER; `_m4bs()`
  guards the unset var at collection time so verify/CI skip cleanly — agreed deviation
  from the drop's verbatim code). Run against the real fixtures: **14/14 PASS, zero
  findings** (all 12 books: title, author, cover, titled chapters, integer parts, one
  consistent series name) — no Open Issues row needed. Unit tests
  `test_m4b_metadata_editor_shared.py` added (7 tests: shared/varies, missing key,
  album-implied, series_part display-only, unreadable-file exclusion, empty list,
  strip-compare). Gates: compileall scripts/+files/tests clean; full suite 26 passed /
  3 skipped (the one warning is the pre-existing pydub audioop deprecation, not Drop 2);
  `python scripts/verify.py` → RESULT: PASS. Docs: CHANGELOG [Unreleased] Drop 2 entry;
  Briefing metadata-editor bullet updated. Drop file `0.5.0-drop2-metadata.md` deleted.
  — Claude Code
- 2026-07-07 — Drop 2 Phase 3 complete (no commit — one-commit-per-drop rule).
  `btn_add_folder` added to the `disable_inputs` widget set. Smoke vs the real fixture
  tree (real UI instance, real `read_m4b_tags`, dialogs injected): Harry Potter 7 files →
  artist 'J.K. Rowling' + series 'Harry Potter' pre-filled, Title blank; Shadow Slave /
  Supreme Magus / Noble Queen also share Genre 'Web Novel'; Dungeon Crawler 8 files OK;
  Jack Ryan OUTER folder → "No audiobooks found" box (subfolder hint shown), list
  unchanged; Jack Ryan INNER folder → 12 files, Tom Clancy + 'Jack Ryan' shared;
  single-file pre-fill unchanged (title + per-file readback w/ source atom); empty
  folder → info box, list unchanged. series_part never pre-filled anywhere. Next:
  Phase QA (Jack Ryan inspection test) + unit tests + verify + docs. — Claude Code
- 2026-07-07 — Drop 2 Phase 2 complete (no commit — one-commit-per-drop rule). Added
  "Open Folder…" button + `add_folder()` (non-recursive .m4b/.m4a/.mp4; "No audiobooks
  found" box now explicitly says subfolders aren't searched — the drop's Jack Ryan
  caveat); `_refresh_mode` n>1 branch now calls `_prefill_shared(n)` (shared values
  pre-filled + snapshotted into `_prefill`, mode line names shared fields,
  `_batch_series_readback` summarises series identical/varies/none). Docstrings
  corrected vs the drop verbatim: module + `_prefill_shared` now state that shared
  NON-series fields left unedited ARE written on Save (byte-identical rewrite —
  maintainer ruling), only series keys are preserve-by-default. Verified via real Tk
  instance w/ monkeypatched `_tags_for`: shared artist/genre/series pre-fill; differing
  title blank; series_part never pre-filled; `_collect_tags` excludes unedited shared
  series but includes shared artist; varies read-back correct; empty-list mode label
  intact. py_compile clean. Next: Phase 3 (disable-state + manual smoke). — Claude Code
- 2026-07-07 — Drop 2 Phase 1 complete (no commit — one-commit-per-drop rule). Per
  `0.5.0-drop2-metadata.md`: added `self._tag_cache` to `__init__`, new `_tags_for()`
  (cached, fault-tolerant read — a failing file is logged and excluded, never aborts) and
  `_shared_tags()` (shared/varies across all readable files; `series_part` display-only;
  album-implied series treated as absent) in `m4b_metadata_editor.py`; cache cleared in
  `clear_list()` and `remove_selected()`. Purely additive — nothing calls the helpers yet.
  Two agreed deviations from the drop's literal anchors: new methods inserted after the
  complete `_prefill_from` body (the drop's mid-method anchor would break the file), and
  (upcoming, QA phase) `_m4bs()` will guard the unset env var at collection time.
  Maintainer rulings recorded: continue on `restructure-v0.5.0` atop unmerged Drop 1;
  NO `album_artist` row this drop; NO preserve-by-default for shared non-series fields
  (`_collect_tags` untouched). Verified: py_compile clean; `_shared_tags` on a stub —
  empty list → `({}, set())`; 3 files sharing artist w/ differing titles + album-implied
  series → `({'artist': 'X'}, {'title', 'series'})`. Next: Phase 2 (folder picker +
  batch wiring). — Claude Code
- 2026-07-07 — Phase 6 complete — DROP 1 DONE (no commit yet — maintainer reviews then makes
  the single drop commit). Bug hunt: whole-tree grep for stale tokens (`scripts\shared`,
  `resources\logs|bin|models|settings`, `Windows\...`, `MacOS\...`, `setup_and_run`) —
  remaining hits only in CHANGELOG history (preserved verbatim by design), handoff's own
  migration map, and files/release-history snapshots; live code + launchers + tests are clean.
  README repo-describing sections updated to the new layout (structure diagram, one-tree
  design note, files/bin ffmpeg path, release-build command; install steps use the new
  launcher names with "(named setup_and_run.* in the v0.4.0 zip)" parentheticals; v0.4.0
  download links kept per maintainer Q9). release.py dry run: both v0.5.0 zips built, exit 0,
  archive root = README + correct launcher only, zero runtime/test leaks, .command packaged
  0o755. Final gates: compileall scripts/ + files/tests clean; verify.py → 19 passed,
  RESULT: PASS. Deleted scratch REPO-STRUCTURE.md + Map-Repo-Structure.bat + the drop file
  `0.5.0-drop1-restructure-and-docs.md`. Root now: README, AI-WORKSPACE.md, two Setup_and_Run
  launchers, scripts/, files/, md-instructions/ (+ gitignored .venv/ + dist/). — Claude Code
- 2026-07-07 — Phase 5 complete (no commit — one-commit-per-drop rule). Root launchers
  git-mv-renamed to the exact maintainer-specified names
  `Setup_and_Run-audiobook-creation-tool.bat` / `.command` and rewired: no more `cd` into
  Windows/-MacOS/ (cd to repo root), BOOTSTRAP → scripts/Universal/shared/bootstrap.py,
  log-path messages → files/runtime-data/logs/. Preserved verbatim: Windows pythonw
  no-console fast path, macOS Gatekeeper/App-Translocation guard (sibling marker changed
  from MacOS/ to scripts/ — same logic + message), foreground --launch-only +
  close_terminal.py Terminal auto-close, Tk-capable-Python probe + Homebrew repair +
  headless fallback, winget Python install path. Kokoro install logic untouched (Drop 3).
  Verified live: bootstrap --self-test all green on the new layout (venv valid at root,
  requirements found, HF_HOME → files/runtime-data, kokoro health ok, launch target =
  scripts/Universal/launcher.py); real double-click path via the renamed .bat launched the
  GUI detached under pythonw (launch log in files/runtime-data/logs/, no crash output);
  test instance closed. — Claude Code
- 2026-07-07 — Phase 4 complete (no commit — one-commit-per-drop rule). scripts/verify.py
  stood up from verify-template (project name set; deps check made PEP-508-marker-aware so
  `kokoro==… ; python_version < "3.13"` / `audioop-lts==… ; python_version >= "3.13"` don't
  false-fail the operator regex — the pin rule applies to the spec before ';'). pytest==9.1.1
  added to scripts/requirements.txt and installed in the venv. files/tests/ suite written:
  conftest (import-root bootstrap) + launcher build-all smoke (all 6 tools through the real
  LauncherApp, error-panel monkeypatch, settings.json snapshot/restore) + per-tool
  behaviour-preservation smokes (tts voice registry 11-voice contract + pdf_to_txt on a
  generated PDF; mp3_tool hms/concat-escape/next-folder; m4b_maker natural sort/title
  normalization/ffmetadata chapters/concat quoting; m4b_converter sanitize_filename;
  cover_resizer letterbox+crop+ext-fallback+next_version_path via real PIL; shared.metadata
  ffmpeg args/header lines/freeform namespace/ABS series-atom constants). No network anywhere.
  One test expectation corrected against real behaviour (normalize_title: first `_` becomes
  the colon before the possessive rule can see it). `python scripts/verify.py` → 19 passed,
  RESULT: PASS. — Claude Code
- 2026-07-06 — Phase 3 complete (no commit — one-commit-per-drop rule). Briefing.md rewritten
  to current state per the template (architecture, all 6 tools, new layout, known limitations;
  old v0.1–0.3 status stack dropped — that history lives in CHANGELOG + files/release-history).
  CHANGELOG: prior [Unreleased] items (console-flash fix, test-fixture history scrub) folded
  into a new [0.5.0] - 2026-07-06 entry along with the restructure/Added-verify entries
  (explicitly "no user-facing tool changes"); fresh empty [Unreleased] on top; ALL prior
  history preserved verbatim. DECISIONS.md seeded with the drop's four ADRs + the
  runtime-data-layout ADR (+ the earlier commit-policy ADR). Instructions_Template.md written
  (project-tailored, uses <angle> slots so verify's [bracket] scan can't false-positive).
  version.py → 0.5.0; README status line → short v0.5.0-in-development note, v0.4.0 download
  links kept (maintainer Q9). .claude/CLAUDE.md + .codex/CODEX.md created pointing at
  AI-WORKSPACE.md with the kickoff read order and the no-per-phase-commit rule. — Claude Code
- 2026-07-06 — Phase 2 complete (no commit — one-commit-per-drop rule). Executed the full
  migration map: git mv Windows/scripts → scripts/Universal (git recorded all as renames —
  history preserved); requirements → scripts/requirements.txt (header de-Windows-ified);
  Dockerfile + v0.3.1 one-shots → files/{,release-history}; test_kokoro_voices.py →
  files/tests/; deleted mp3_tools_launcher.py + tts/setup_env.py + entire MacOS dupe tree.
  Untracked moves: settings.json/models/huggingface → files/runtime-data/, harness MP3s →
  files/test-logs/kokoro-voices/, test-files → files/test-files/, Windows/.venv → root .venv
  (old resources/logs discarded — runtime-generated). Rewired paths.py + bootstrap.py to
  REPO_ROOT derivation (RESOURCES_DIR → files/runtime-data, BIN_DIR → files/bin, VENV_DIR →
  root .venv, REQUIREMENTS → scripts/requirements.txt); removed the OS_ROOT alias everywhere;
  kokoro_synth HF fallback now walks to the repo root (scripts/+files/ present); release.py
  reworked for the single-tree layout (both zips = README + OS launcher + scripts/**);
  updated all stale resources/-and-setup_and_run docstrings. .gitkeep in scripts/{Windows,
  MacOS} so the empty OS dirs survive clone. Verified: compileall clean; headless build-all
  6/6 tools, no error panels, 1.35 s; all derived paths print correct new locations; moved
  venv works (Python 3.12.10). Old Windows/ + MacOS/ trees deleted. — Claude Code
- 2026-07-06 — Phase 1 complete (no commit — maintainer's one-commit-per-drop rule, see
  DECISIONS.md 2026-07-06 entry; applies to the whole v0.5.0 sequence). Rewrote .gitignore to
  the final layout (`.venv/` root, `files/bin/`, `files/runtime-data/`, `files/test-files/`,
  any-depth `test-logs/`; dropped all Windows/-MacOS/-prefixed rules); verified with
  `git check-ignore -v`. Created files/ skeleton (tests, release-history,
  runtime-data/{logs,models}, bin). DECISIONS.md created early with the standing commit-policy
  decision. Next: Phase 2 (the big migration). — Claude Code
- 2026-07-06 — Phase 0 complete. Committed pending console-flash fix + AI-WORKSPACE.md on
  master (`e80ba7f`); cut branch `restructure-v0.5.0`; re-ran Map-Repo-Structure.bat and
  reconciled the migration map (this file) against the fresh tree + all nine maintainer
  answers. Baseline recorded: `compileall` clean on both trees (venv Python 3.12.10); headless
  launcher build-all via the real `LauncherApp` = 6/6 tools built, zero error panels, 4.32 s.
  This is the known-good bar for every later phase. Next: Phase 1 (skeleton + .gitignore).
  — Claude Code
- 2026-07-06 — Session kickoff: read AI-WORKSPACE.md, both Briefing/CHANGELOG copies (verified
  byte-identical Win↔Mac), the three v0.3.1 one-shots, and the full Drop 1 instruction file.
  Confirmed version state: version.py/README = 0.4.0, CHANGELOG top release [0.4.0], tags
  v0.1.0–v0.4.0 incl. v0.3.1 (`49bb51a`). — Claude Code

---

## Session Sync Log (newest first)

### 2026-07-31 — HOME-PC — v0.6.0 Drop 1 Phase 3 — committed and pushed to `feature/0.6.0-drop1-windows-ui-prototype`
- Base:    `b2e5285958a8d7adcc19a4c17d45f1e55fd7e900` (Phase 2). No pull needed —
  `master` and `origin/master` are both still `1da1e547` and were not touched.
- Changed: `scripts/Universal/mp3_tools/m4b_metadata_editor.py` (+373 / -9) — the
  presentation fork (`_build_ui` dispatcher, `_build_ui_classic` holding the old body
  verbatim, the new `_build_ui_windows`, the `_wrap_with` caption helper), a theme-aware
  `__init__`, the optional `theme=None` parameter on `build_ui`, and an expanded module
  docstring. Every method from `add_files` down is unchanged.
- Changed: `scripts/Universal/shared/ui_theme.py` (+21 / -2) — `sidebar_width` 232 → 180
  (maintainer-approved, with the reason in a comment) plus four new namespaced styles
  for the Shared Metadata surface (`ACT.Shared.TFrame`, `ACT.Shared.TLabel`,
  `ACT.SharedSecondary.TLabel`, `ACT.Shared.TCheckbutton`, the last with its own explicit
  layout). No generic style was created, configured or re-laid-out.
- Added:   `files/tests/test_m4b_metadata_editor_ui.py` (12 tests) — preserved public
  contract, busy/idle, shared-value prefill through the real widget tree, the non-Windows
  fork, and the Windows-only style/isolation/scroll/Shared-Metadata assertions plus the
  two fixture-isolation tests.
- Added:   `files/tests/manual_windows_ui_prototype.py` — the developer-only visual
  fixture (`empty` / `populated` / `active-run` / `specimen`). Not pytest-collectable,
  not reachable from the launcher, not in the shipped tree, patches nothing, offline.
- Changed: `files/tests/test_ui_theme.py` (+49 / -5) — the pinned 180px rail and the
  Shared Metadata surface-family test; new styles added to the build-everything test.
- Changed: `files/tests/test_launcher_smoke.py` (+51 / -3) — the narrowed-rail regression
  test, and the isolation test now separates the converted editor from the five
  unconverted panels instead of requiring all six to be style-free.
- Changed: `md-instructions/handoff.md` (this file — Phase 3 section, hierarchy and
  control-mapping tables, Shared Metadata / Summary-Details boundaries, fixture isolation,
  the rail measurements, the M4B Converter reachability answer, limitations, work-log
  entry, this sync entry)
- Note:    **`scripts/Universal/launcher.py` was NOT edited.** The narrower rail exposed
  no launcher-owned defect.
- Note:    **Only the metadata editor was converted.** `scripts/requirements.txt`,
  `scripts/Universal/shared/version.py` (still `0.5.1`), both setup launchers,
  `scripts/Universal/tts/`, the other five tool modules and
  `files/UI-Current-Screenshots/` are untouched — confirmed with `git diff --name-only
  HEAD` over each path (empty). A grep of the added lines under `scripts/` for
  `style.configure|style.map|style.layout|option_add|#rrggbb` returns only the three new
  `ACT.Shared*` configure calls; no hex literal and no `option_add` entered the drop.
- Note:    **Open item carried forward:** the vertical half of the Phase 2 geometry
  regression. Width is fixed; M4B Converter's primary action and Log are reachable again
  at 1024×720 but still clipped at the 920×600 minimum. `MIN_SIZE`/`DEFAULT_GEOMETRY`
  left unchanged per the maintainer's decision; re-assess at Phase 5.
- Note:    **Untracked `config-template.toml` still left alone at the repo root** — not
  edited, staged, committed, moved or deleted. Staging was done by explicit path only.
- Verify:  `.venv\Scripts\python.exe scripts/verify.py` → **RESULT: PASS**
  (pytest 82 passed / 3 skipped; deps `==`-pinned; docs de-templated).
  `git diff --check` clean before and after this handoff update.

### 2026-07-31 — HOME-PC — v0.6.0 Drop 1 Phase 2 — committed and pushed to `feature/0.6.0-drop1-windows-ui-prototype`
- Base:    `9cd7fb8e04e11d64f9303d0f44a7ca3f3723af51` (Phase 1). No pull needed —
  `master` and `origin/master` are both still `1da1e547` and were not touched.
- Changed: `scripts/Universal/launcher.py` (+151 / -8) — new `_build_ui_windows()`
  (navigation rail, header strip, framed content card, status bar with a focusable
  log button), a `windows` arm in `_build_ui()` and in `_highlight_selection()`
  (ttk `selected` flag instead of disabling the active row), a themed arm in
  `_show_load_error()`, and an updated module docstring. `_build_ui_classic`,
  `_build_ui_darwin`, `_row_hover`, `select_tool`, `_load_tool_into`, `TOOLS`,
  `_available_tools`, `_apply_default_geometry`, `_open_logs`, `_on_close`,
  `_configure_hf_cache` and `main()` are unchanged.
- Changed: `files/tests/test_launcher_smoke.py` (+299 / -0) — 1 test → 10. Adds
  registry order, build-once/no-rebuild across three sweeps, a real typed state marker
  surviving switching, valid-saved-tool restore (with the other five still lazy),
  invalid-key fallback, missing-module fallback, `ACT.*` chrome styling, selected-state
  handling, and the child-panel style-isolation test. The original build-all test is
  preserved verbatim.
- Changed: `md-instructions/handoff.md` (this file — Phase 2 section, layout/style
  mapping table, isolation explanation, draft-review table, limitations, work-log
  entry, this sync entry)
- Note:    **`shared/ui_theme.py` was NOT edited.** The Phase 1 API covered the entire
  shell, so no new style, token or helper was needed and the isolation tests did not
  have to change.
- Note:    **Only the launcher shell was converted.** All six tool modules,
  `scripts/requirements.txt`, `scripts/Universal/shared/*` (including `version.py`,
  still `0.5.1`), both setup launchers and `files/UI-Current-Screenshots/` are
  untouched — confirmed with `git diff --name-only HEAD` over each of those paths
  (empty). `git status` shows only the three files above.
- Note:    **Open geometry regression escalated, not silently accepted** — the shell
  costs the tool panels 127px width / ~100px height vs the classic shell, which clips
  M4B Converter's primary action row at the 920×600 minimum. Full measurements and
  three costed options are in *Phase 2 limitations*. Deliberately not fixed here
  because both levers live in `ui_theme.py` and are maintainer decisions.
- Note:    **Untracked `config-template.toml` still left alone at the repo root** — not
  edited, staged, committed or deleted. Staging was done by explicit path only.
- Verify:  `.venv\Scripts\python.exe scripts/verify.py` → **RESULT: PASS**
  (pytest 68 passed / 3 skipped; deps `==`-pinned; docs de-templated).
  `git diff --check` clean before and after this handoff update.

### 2026-07-31 — HOME-PC — v0.6.0 Drop 1 Phase 1 — committed and pushed to `feature/0.6.0-drop1-windows-ui-prototype`
- Base:    `0971a20e24fc196967da97d1b204375dc549ad5a` (Phase 0). No pull needed —
  `master` and `origin/master` are both still `1da1e547` and were not touched.
- Changed: `scripts/Universal/shared/ui_theme.py` (+795 / -7) — explicit `win32`
  branch returning `mode="windows"`, 35 semantic colours, 26 metrics, an 11-entry font
  scale, 41 `ACT`-namespaced ttk styles in `theme["styles"]` (plus 4 widget-owned
  sub-styles) built from 24 explicit layouts over 28 cloned `clam` elements, and the
  new `style_tk_widget()` helper for classic Tk widgets. `apply_theme` signature,
  `DEFAULT_GEOMETRY`, `MIN_SIZE`, `enable_mousewheel` and `ProgressIndicator` are
  unchanged.
- Changed: `files/tests/test_ui_theme.py` (+429 / -13) — 5 tests → 16. Adds the Windows
  bundle/colour/metric contracts, WCAG contrast floors, style-namespace and
  widget-state coverage, a real-widget build pass, the missing-native-theme fallback,
  idempotent re-application, `style_tk_widget` behaviour, and the **generic-style
  isolation** test that compares 18 generic styles before/after theming. The classic
  Linux/other and macOS aqua assertions are preserved as they were.
- Changed: `md-instructions/handoff.md` (this file — Phase 1 section, API table,
  isolation rule for later phases, limitations, work-log entry, this sync entry)
- Note:    **Nothing was converted.** `launcher.py`, all six tool modules,
  `scripts/requirements.txt`, `scripts/Universal/shared/version.py` (`0.5.1`), both
  setup launchers and `files/UI-Current-Screenshots/` are untouched. `git status`
  shows only the three files above.
- Note:    IDE diagnostics investigated before editing, as instructed. Both earlier
  notices (70 and 26 issues) were **Markdown linter output on the documentation files
  written during Phase 0**, not Python errors. Workspace diagnostics are now empty and
  `compileall` over `scripts` + `files/tests` exits 0. No genuine baseline source
  problem; nothing unrelated was fixed.
- Note:    **Untracked `config-template.toml` still left alone at the repo root** — not
  edited, staged, committed or deleted. Staging was done by explicit path only.
- Verify:  `.venv\Scripts\python.exe scripts/verify.py` → **RESULT: PASS**
  (pytest 59 passed / 3 skipped; deps `==`-pinned; docs de-templated).
  `git diff --check` clean before and after this handoff update.

### 2026-07-31 — HOME-PC — v0.6.0 Drop 1 Phase 0 — committed and pushed to `feature/0.6.0-drop1-windows-ui-prototype`
- Pulled:  `master` fast-forwarded `695045c` → `1da1e547ce85d6e5c8a5b34fb549ffa8b93f6318`
  (`git pull --ff-only`, 10 commits, no divergence). Incoming: v0.5.1 Jenny line,
  8 `files/UI-Current-Screenshots/*.png`, `.gitignore` hardening,
  `md-instructions/Instructions_Template.md` deleted upstream, docs, `version.py` 0.5.1.
- Added:   `md-instructions/0.6.0-drop1-windows-ui-prototype.md` (the active temporary
  drop — tracked on purpose so its Phase 6 deletion is a recorded git event, matching
  how `drop3-plan.md` / `0.5.0-drop2-metadata.md` were handled)
- Changed: `md-instructions/handoff.md` (this file — new Current Focus with the Phase 0
  baseline evidence, limitations, and next phase; work log; this sync entry)
- Note:    **No program, theme, launcher, tool-panel, or test source was touched.**
  `scripts/requirements.txt` and `scripts/Universal/shared/version.py` (still `0.5.1`)
  are byte-identical to `origin/master` — confirmed with `git diff` against the remote.
  `files/UI-Current-Screenshots/` preserved unchanged.
- Note:    Worktree carried pre-existing user work — an unstaged deletion of
  `Instructions_Template.md` and untracked `Map-Repo-Structure.bat` /
  `REPO-STRUCTURE.md`. Nothing was reset, discarded, stashed, or overwritten; all were
  backed up to scratch first. Upstream deleted the template itself and gitignored both
  convenience tools, so the working tree resolved with a zero net diff.
- Note:    The maintainer's on-disk case-rename of the four permanent docs
  (`Changelog.md` / `Decisions.md` / `Handoff.md`) did **not** survive the pull —
  `core.ignorecase=true` meant git never saw it. Live tracked names remain
  `Briefing.md` / `CHANGELOG.md` / `DECISIONS.md` / `handoff.md`. Renaming needs a
  `scripts/verify.py` edit (it hard-codes `CHANGELOG.md`), which this drop may not make;
  raised for a separate maintainer decision.
- Note:    **Untracked `config-template.toml` left alone at the repo root.** It is not
  this session's work (file mtime 2026-07-17, contents are the raw scaffolder template
  with `[PROJECT_NAME]` placeholders) and it appeared in `git status` only partway
  through the session, so an external process (VS Code / a scaffolder run) wrote it.
  It is neither committed nor deleted. Per AI-WORKSPACE the committed root file is
  `config.toml`, not `config-template.toml`, and this repo has neither tracked — so
  this is scaffolding drift for the maintainer to resolve, not drop work. Staging was
  done by explicit path, never `git add -A`, so it cannot be swept in.
- Note:    Phase 0 is committed and pushed on the implementation branch only. `master`
  is untouched. Per-phase commits are this plan's explicit contract (§1.5); the v0.5.0
  one-commit-per-drop ADR does not apply to the v0.6.x line. No AI co-author trailers.

### 2026-07-19 — MacBook — Jenny voice + batch-rework revert — committed to `add-jenny-voice`, pushed (NOT merged to master)
- Changed: scripts/Universal/tts/voice_registry.py (Jenny VoiceEntry, 750/800 single-file preset)
- Changed: files/tests/test_tts_smoke.py (voice counts 11→12, edge 6→7)
- Changed: scripts/Universal/tts/generate_voice_samples.py (reusable voice-filter CLI args)
- Changed: .gitignore (files/livid-lady-test-files/ voice-timing corpus)
- Changed: scripts/Universal/shared/version.py (0.5.0 → 0.5.1)
- Changed: md-instructions/CHANGELOG.md (Jenny entries + rework-reverted 0.5.1 note)
- Changed: md-instructions/Briefing.md (12 voices / 7 Edge; batch pause-fields limitation
  made explicit; version line 0.5.1)
- Changed: md-instructions/DECISIONS.md (batch-rewrite-abandoned-by-ear ADR)
- Changed: md-instructions/handoff.md (this file — focus, work log, sync log)
- Note:    ALL batch-engine work from the abandoned drop reverted before commit —
  batch_convert.py / epub2tts_gui.py / epub2tts_edge.py / runner.py /
  test_batch_convert_folders.py are byte-identical to master; batch_convert_child.py,
  batch_timing_harness.py, and the drop file batch-timing-parity.md never committed.
- Note:    Maintainer pulls this branch on HOME-PC for a second verify pass and merges
  to master themself. No AI co-author trailers.

### 2026-07-08 — MacBook — UX-progress drop (all phases) — NOT committed (no .git on this copy)
- Changed: scripts/Universal/shared/ui_theme.py (new ProgressIndicator class)
- Changed: scripts/Universal/mp3_tools/m4b_converter.py (indicator + (done,total) payload)
- Changed: scripts/Universal/mp3_tools/cover_resizer.py (indicator + (done,total) payload)
- Changed: scripts/Universal/mp3_tools/m4b_maker.py (indicator, indeterminate encode,
  dead progress_max branch removed)
- Changed: scripts/Universal/mp3_tools/mp3_tool.py (new indicator + progress/progress_ind
  queue kinds + per-worker ticks)
- Changed: scripts/Universal/mp3_tools/m4b_metadata_editor.py (indicator + (done,total)
  payloads; Phase 4 scroll-canvas layout + 14-row Log)
- Changed: scripts/Universal/tts/epub2tts_gui.py (indicator beside Start/Cancel; progress
  enqueues in all four conversion paths)
- Changed: scripts/Universal/tts/kokoro_synth.py (additive progress_callback param)
- Changed: scripts/Universal/tts/epub2tts_edge/epub2tts_edge.py (read_book
  progress_callback, paragraph units)
- Changed: scripts/Universal/tts/epub2tts_edge/runner.py (progress_callback pass-through)
- Changed: scripts/Universal/launcher.py (M4B Metadata description de-staled)
- Changed: files/tests/test_ui_theme.py (ProgressIndicator test)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] UX-progress Added + Changed)
- Changed: md-instructions/Briefing.md (ui_theme / worker-progress / metadata-editor
  bullets)
- Changed: md-instructions/DECISIONS.md (progress-placement + Maker-indeterminate ADR)
- Changed: md-instructions/handoff.md (this file — focus, work log, sync log)
- Note:    Phase 5 close-out complete (suite 46/3, verify PASS, win32-stub classic
           proof). Drop file 0.5.0-ux-progress-and-metadata-layout.md intentionally
           NOT deleted and nothing committed (maintainer instruction) — maintainer
           does the final sign-off, carries files to a real clone, and makes the
           single drop commit (no AI co-author trailers).

### 2026-07-08 — MacBook — component-verify drop (all phases) — NOT committed (no .git on this copy)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] component-verify Verified entry)
- Changed: md-instructions/Briefing.md (xHE-AAC bullet reworded w/ macOS USAC residual;
  macOS-live-pass caveat retired; High-Level State notes the macOS per-tool pass)
- Changed: md-instructions/handoff.md (this file — focus, open-issues note, work log,
  sync log)
- Note:    NO program-code changes this drop — the live pass found no macOS breakage.
  The only working-tree deltas vs the previous sync entries are the three docs above.
- Note:    Drop file 0.5.0-macos-component-verify.md intentionally NOT deleted and
  nothing committed (maintainer instruction) — maintainer does the manual sign-off,
  carries files to a real clone, and makes the single drop commit (no AI co-author
  trailers).

### 2026-07-08 — MacBook — scroll fix + UI-shell Phase 5 close-out — NOT committed (no .git on this copy)
- Changed: scripts/Universal/shared/ui_theme.py (new enable_mousewheel helper —
  wrap-frame Enter/Leave + Tcl-level NotifyInferior guard)
- Changed: scripts/Universal/tts/epub2tts_gui.py (inline wheel handler + canvas
  Enter/Leave block replaced by enable_mousewheel(options_canvas, canvas_wrap);
  shared.ui_theme import added)
- Changed: files/tests/test_ui_theme.py (added enable_mousewheel wiring test)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] macOS UI shell Added + Fixed)
- Changed: md-instructions/Briefing.md (GUI/launcher/shared/ui_theme bullets;
  macOS-live-pass caveat narrowed)
- Changed: md-instructions/DECISIONS.md (2 ADRs: aqua theme choice; wheel-binding
  Tcl-level detail guard)
- Changed: md-instructions/handoff.md (this file — focus, work log, sync log)
- Note:    Drop file 0.5.0-macos-ui-shell.md intentionally NOT deleted yet —
  maintainer live-tests scrolling on the TTS panel, then makes the single drop
  commit (one commit for Phases 1–5 + this fix; no AI co-author trailers) and
  deletes the drop file.

### 2026-07-08 — MacBook — UI-shell drop Phases 1–4 — NOT committed (no .git on this copy)
- Changed: AI-WORKSPACE.md (HOME-MacOS section filled in from the real machine)
- Added:   scripts/Universal/shared/ui_theme.py (apply_theme; aqua/Finder vs classic)
- Changed: scripts/Universal/launcher.py (wired to ui_theme; _build_ui split into
  classic (verbatim old body) + darwin Finder shell; _highlight_selection branch;
  _row_hover; _ui_font_family/DEFAULT_GEOMETRY/MIN_SIZE moved into ui_theme)
- Added:   files/tests/test_ui_theme.py (3 headless-guarded theme tests)
- Changed: md-instructions/handoff.md (this file — focus, work log, sync log)
- Note:    Machine state: `.venv` deleted and rebuilt fresh via the .command
  (Python 3.12.13, Kokoro healthy) as the Phase 2 launch-gate test.
- Note:    ⚠ This working copy has NO .git directory — the maintainer must carry
  these files onto a real clone (branch `restructure-v0.5.0` per plan) to commit.
  One commit for the whole drop, maintainer-made, no AI co-author trailers.

### 2026-07-07 — MacBook — §2.4 Kokoro fix — not committed, not pushed
- Changed: scripts/Universal/shared/bootstrap.py (`_is_kokoro_compatible` helper;
  run_setup installs 3.12 before accepting >=3.13; _create_validated_venv rebuilds a
  >=3.13 venv on a <3.13 base)
- Added:   files/tests/test_bootstrap_python_version.py (version-gate regression test)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] macOS component-verify Fixed entry)
- Changed: md-instructions/DECISIONS.md (macOS-venv-on-3.12 ADR)
- Changed: md-instructions/handoff.md (this file — focus, Open Issues #1 closed,
  work log, sync log)
- Note:    Machine state changed: brew installed python@3.12 + python-tk@3.12; root
  `.venv` rebuilt on Python 3.12.13 (Kokoro healthy). No commits — maintainer reviews
  and commits. No AI co-author trailers.

### 2026-07-07 — HOME-PC — Drop 3 — committed, merged to master, pushed
- Changed: scripts/Universal/tts/epub2tts_gui.py (batch end_silence_ms fix; paragraph_pause
  hoist + chunk_pause_ms into both Kokoro calls; Kokoro batch .pdf/.txt discovery with
  mirrored output subfolders; mode/browse/docstring labels)
- Changed: scripts/Universal/tts/batch_convert.py (mirrored output tree + collision-safe
  temp dirs + .txt support; out_mp3 threaded through convert_single_pdf; docstrings/CLI text)
- Added:   scripts/Universal/tts/generate_voice_samples.py (per-voice manual-listen QA)
- Added:   files/tests/test_batch_convert_folders.py (5 tests)
- Added:   files/tests/test_kokoro_timing_wiring.py (3 tests)
- Changed: .gitignore (files/test-for-manual-listen-elmatthe/ — generated MP3 samples)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] Drop 3 Fixed + Added)
- Changed: md-instructions/Briefing.md (TTS feature bullet)
- Changed: md-instructions/DECISIONS.md (Kokoro pause-mapping ADR)
- Changed: md-instructions/handoff.md (this file — focus, open issues, work log, sync log)
- Deleted: md-instructions/drop3-plan.md (drop implemented)
- Note:    md-instructions/Instructions_Template.md restored from HEAD — the working
           tree showed it deleted alongside the untracked drop file (the drop was
           evidently created from the template, same as before Drop 2), so the net
           working-tree diff for it is zero.
- Note:    Single Drop 3 commit made on restructure-v0.5.0 (stacked on 97758c2) at the
           maintainer's explicit instruction, then fast-forward merged to master and
           pushed. restructure-v0.5.0 RETAINED and pushed (base for macOS work).
           No AI co-author trailers.
- Note:    REMOTE ANOMALY FOUND AND RESOLVED at ship time: origin/master had been
           force-moved to a stale pre-restructure line (a20fa21 "Delete AI-WORKSPACE.md",
           a Jul 2 GitHub web-UI commit atop 391326e — the OLD test-files-scrub rewrite,
           content-identical to our 45c66e5 but with no common ancestor). Maintainer
           ruled it a stale accident: our line was force-pushed over it
           (--force-with-lease), so a20fa21 is gone from master and the root
           AI-WORKSPACE.md remains (as refreshed in 97758c2). If another machine still
           has the old line locally, hard-reset its master to origin/master before
           doing anything.
- Note:    Drop 3 §2.4 (Kokoro on macOS) is NOT done — blocked on a real Mac (Open
           Issues #1). It is the FIRST task for the MacBook session, from master.

### 2026-07-07 — HOME-PC — Drop 2 — not committed, not pushed
- Changed: scripts/Universal/mp3_tools/m4b_metadata_editor.py (tag cache + _tags_for/
  _shared_tags/_prefill_shared/_batch_series_readback, Open Folder… button + add_folder,
  batch branch of _refresh_mode, disable_inputs set, docstrings)
- Added:   files/tests/test_m4b_metadata_editor_shared.py (7 detection unit tests)
- Added:   files/tests/test_jack_ryan_final_product.py (env-gated QA inspection)
- Changed: md-instructions/CHANGELOG.md ([Unreleased] Drop 2 entry)
- Changed: md-instructions/Briefing.md (metadata-editor feature bullet)
- Changed: md-instructions/handoff.md (this file — focus, work log, sync log)
- Deleted: md-instructions/0.5.0-drop2-metadata.md (drop implemented)
- Note:    Awaiting maintainer review → single Drop 2 commit on restructure-v0.5.0
           (stacked on a7044d4). Agent does not push. No AI co-author trailers.
- Note:    A SECOND separate commit follows Drop 2 (maintainer ruling, same precedent
           as e80ba7f): the refreshed root AI-WORKSPACE.md + the synced copy at
           files/vibe-coding-templates/AI-WORKSPACE.md. Pre-Drop-2 working-tree
           leftovers resolved: Map-Repo-Structure.bat + REPO-STRUCTURE.md discarded
           (scratch); md-instructions/Instructions_Template.md restored from HEAD
           (deletion predated the session; the refreshed AI-WORKSPACE still
           references it).

### 2026-07-07 — HOME-PC — not committed, not pushed
- Entire v0.5.0 Drop 1 restructure sits UNCOMMITTED in the working tree of branch
  `restructure-v0.5.0` (per the one-commit-per-drop rule): all git mv renames staged,
  new files (tests, verify.py, DECISIONS.md, handoff.md, Instructions_Template.md,
  .claude/CLAUDE.md, .codex/, files/vibe-coding-templates/) untracked pending the single
  drop commit the maintainer will make after review.
- Do NOT start work on another machine until this branch is committed, force-pushed by the
  maintainer, and merged — the whole tree has moved.

### 2026-07-06 — HOME-PC — not pushed
- Changed: AI-WORKSPACE.md (refreshed global workspace doc — committed on master `e80ba7f`)
- Changed: Windows+MacOS scripts/launcher.py, scripts/shared/subprocess_utils.py,
  md-instructions/CHANGELOG.md (console-flash fix, committed on master `e80ba7f`)
- Added:   md-instructions/handoff.md (this file — de-templated, migration map written)
- Note:    Branch `restructure-v0.5.0` active; restructure in flight. Do not start work on
           another machine until this branch merges — the whole tree is about to move.
