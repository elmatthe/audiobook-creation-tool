# Audiobook Creation Tool — Plan 01B: Universal Speech-Preparation Pipeline and `scripts/` Layout Consolidation

**Status:** Revised 2026-10-19 after ChatGPT review and the owner's working decisions (section 0). The owner has authorised implementing **only C0, A0 and B1** (sections 6 and 10); every other checkpoint remains a proposal. The original research pass changed no production file, dependency, model, recording or setting.  
**Repository:** https://github.com/elmatthe/audiobook-creation-tool  
**Branch inspected:** `feature/0.6.7-bundled-chatterbox-references`; **implementation branch:** `feature/0.6.7-speech-pipeline-and-layout`, cut from the inspected head ([D1])  
**Inspected head:** `df0dbc28ec08a25d9a5af426ec1dd718c0baef5a` (rechecked live; working tree clean apart from the untracked, unrelated `.ai/` and `scripts/project-status.py`)  
**Save as:** `files/plans/ACT-v0.6.7-Plan-01B-Text-Pipeline-and-Script-Layout.md`  
**Authority:** the owner's 2026-10-19 prompts; `AI-WORKSPACE.md`; `md-instructions/Handoff.md` (CP6 block) and `Decisions.md` (2026-10-19 entries and the v0.6.5 Phase 5/6 audio rulings); `files/plans/ACT-v0.6.7-Plan-01-CP6-Qwen3-Integration-Addendum.md`.

**How to read this document.** Every statement is tagged. **[V]** = verified fact (read from the repository at the inspected head, from an official source, or measured read-only today; the source is given). **[P]** = proposed architectural choice. **[D#]** = an owner decision (recorded as decided in section 0.1; the details deliberately left to evidence are in section 8). **[R#]** = a risk (section 9). Anything not tagged is explanatory.

---

## 0. Review closure and recorded working decisions (2026-10-19)

ChatGPT reviewed the full document and the owner had already approved the overall architecture. The owner then authorised C0 (this revision, the decisions and the branch), A0 (characterization fixtures) and B1 (mechanical relocation) — nothing else: no Workstream A production integration, no audio generation, no transcript change, no model install, no merge, tag or release.

### 0.1 Working decisions (**decided**; they replace the recommendations of the first draft of section 8)

| # | Decision |
|---|---|
| **D1** | New branch `feature/0.6.7-speech-pipeline-and-layout` from `df0dbc28`. |
| **D2** | Sequence **C0 → A0 → B1 → A1–A5 → S5** (A6 optional, gated). A0 precedes B1 so the original text paths are characterised before any file moves. |
| **D3** | The deep MP3/M4B package split is deferred until after S5. B1 adds useful `scripts/` and tool-module navigation documentation. |
| **D4** | Warn about a stale `scripts/Universal`; **never delete it automatically**, and never delete any ignored or untracked file merely to make the directory disappear. |
| **D5** | In-house stdlib verbalizer; `num2words` only as an optional developer comparison. |
| **D6** | Engine modes are `native` **during rollout only**. The final architectural goal is shared normalization defaults for every engine; an engine-specific exception requires evidence, documentation and review (4.6). |
| **D7** | The proposed en-US spoken style (4.3) is the working style; finalised by the owner's A/B verdicts. |
| **D8** | Test Kokoro's ambiguous four-digit numbers before approving any exception. No exception is approved today. |
| **D9** | Empty default glossary; user-curated, data-only pronunciation overrides. |
| **D10** | Edge folder metadata (`Title:`/`Author:`/`#`) consistency is a separately tested behaviour change — **not** part of B1. |
| **D11** | Preserve existing Kokoro/Chatterbox heading timing unless evidence supports a change. |
| **D12** | GUI glossary editor and Preferences controls deferred. |
| **D13** | One representative voice per engine for the initial A/B. |
| **D14** | Narrowly validated hygiene only; never indiscriminate deletion of Unicode controls, and never alter unsupported-language content. |
| **D15** | English-only normalization in v1. |

### 0.2 Corrections made in this revision

| # | Correction | Recorded in |
|---|---|---|
| 1 | The Chatterbox structural-colon `punc_norm` patch and the 75 ms prose-colon pause are **temporary compatibility behaviour**, not the target architecture. An explicit retirement checkpoint (A6) with acceptance criteria exists; neither is touched by B1; retirement is not claimed until unexpanded/protected structured colons and URLs are addressed. | 3.3, 4.3 (PROT), 6 (A6), 9 (R13) |
| 2 | A content hash does not freeze a glossary or mode configuration. The run carries an **immutable run-scoped copy** of the effective settings; Retry Failed cannot see a modified glossary. Tests cover mid-run and pre-retry edits. | 4.7, 4.8, 6 (A3), 9 (R14) |
| 3 | A0 characterization goldens are captured from the **original** implementation **before** the directories move; they are text/chunk/seed baselines, not regenerated audio. | 4.8, 6 (A0), 7.1 |
| 4 | Test counts: no regression in the pre-existing suite plus passing new tests; old and new counts are recorded **separately** (the total is allowed to rise). | 7.1, 10 |
| 5 | Source mappings start from the **decoded/extracted source text**; nothing claims to reconstruct a PDF's page layout. | 4.4 |
| 6 | The final shared-rule goal is reconciled with the temporary per-engine mode table (convergence rule); there must never be four separately maintained normalization implementations. | 4.6 |
| 7 | Audio gate: any change affecting previously approved pronunciation or pacing is listed explicitly and reviewed by the owner; earlier approvals are evidence baselines, **not permanent vetoes** of the newly approved architecture direction. | 7.2 |
| 8 | Bounded overlay-upgrade risk review; nothing ignored or untracked is deleted to make `scripts/Universal` disappear. | 5.3, 9 (R8) |

---

## 1. Goal and execution boundary

Two separately implementable workstreams, to be completed *before* final CP6 S5 qualification so that S5 qualifies the final architecture once:

* **Workstream A — Universal speech preparation.** One shared, conservative, deterministic text-preparation pipeline in front of Edge, Kokoro, Chatterbox and Qwen3: preserved document structure, context-aware numeric normalization, a shared spoken-form pronunciation glossary, original-to-spoken source mappings, an ambiguity policy, and integrity checks. Per-engine capability adapters, chunk limits and runtime differences stay.
* **Workstream B — `scripts/` layout.** Eliminate `scripts/MacOS/`, `scripts/Windows/` and `scripts/Universal/`; promote the shared application code to `scripts/shared/`; make the TTS, MP3, M4B and artwork modules easier to find. Initial relocation is purely mechanical.

**Not in scope:** Plan 02; any merge, tag or release (none is implied); new voices or models; changes to the 28 approved voices, their labels, order, reference hashes or generation parameters; the six Qwen3 clones' approval path; GUI redesign or a rewrite of any large GUI file; machine-learning or network-based normalization; installing anything.

**Preserved without exception:** all 28 voices; `.venv`; `.venv-qwen3`; model assets under `files/runtime-data/`; the bundled reference recordings and their SHA-256 values; every generated recording under `files/dev-work/` and `files/voice-previews/`; current user settings (`files/runtime-data/settings.json`).

**Sequencing [D2, decided].** C0 → **A0 → B1** → A1–A5 → (A6, optional) → S5. A0 characterises the *original* text paths before any file moves, so B1 can prove it moved nothing; new speech code is then born at its final path. Neither workstream is a prerequisite of the other for correctness.

---

## 2. Owner decisions already recorded (2026-10-19) and the state of the Qwen3 approvals

| Decision | Effect on this plan |
|---|---|
| Voices heard in the available evaluation recordings on HOME-PC are **approved** for eventual production integration. | No repeated listening comparisons. A/B gates in this plan are only for *text-preparation* changes, on short targeted snippets. |
| The complete proposed redesign (universal speech preparation, conservative normalization, shared spoken-form glossary, engine adapters, staged `scripts/` reorganization) is **approved**. | Sections 4 and 5 design it; section 0.1 records the working decisions that followed. |
| Sequencing: finish the investigation and approved refactoring checkpoints **before** final S5; avoid redundant full-suite runs and expensive audio regeneration. | Section 7 budgets exactly three critical full gates and a bounded A/B audio set. |
| Integrity: inspect the local Qwen3 transcript approval records; invent no approvals; bypass no SHA-256 check. | Table below. |

**Inspected today, read-only [V]:**

| Item | Finding |
|---|---|
| `files/dev-work/qwen3-eval/runs/qwen3-initial/transcripts/verified.json` | Six entries (`Female-1`, `Female-2`, `Male-1`–`Male-4`). **All six have `"approved": false` and `"approved_by": null`.** File last modified 2026-10-18 19:55, when the Whisper drafts were written; never edited since. |
| SHA-256 binding | For each of the six, the recorded `wav_sha256`, the SHA-256 of the bundled reference WAV recomputed today, and the constant in `tts/qwen3_runtime.QWEN3_VOICES` are **identical**. The binding is intact; nothing has been approved against it. |
| Production transcript file `files/runtime-data/qwen3/transcripts.json` | **Does not exist.** In the app the six clones therefore report "Setup required". |
| Clone recordings | `runs/qwen3-initial/qwen-clones/` is **empty**. No short or sustained clone recording exists. Only the synthetic-reference smoke test (`pilot/clone-smoke/`) was ever produced. |
| Sustained recordings that exist | `long-form/Aiden-preset.{wav,mp3}`, `Ryan-preset.{wav,mp3}`. |

**Consequence.** The owner's approval of "the voices heard" can only cover voices that exist as recordings: the Edge/Kokoro/Chatterbox evaluation sets and the Qwen3 *presets*. It cannot cover the six Qwen3 clones, which have never been synthesised. Outstanding for the clones, unchanged by this plan, and required before they can be called production-ready: (1) the owner's review and `approved: true` for six transcripts; (2) six short and six sustained clone recordings generated with the existing harness; (3) the owner's listening decision; (4) the Q5 rights audit of the reference recordings and transcripts. Plan 01B does not touch any of these and must not be read as approving them.

---

## 3. Verified baseline

### 3.1 How source text reaches each engine today [V]

References are to the inspected head.

| Stage | Edge — direct (individually added files) | Edge — folder/batch | Kokoro | Chatterbox Turbo | Qwen3 |
|---|---|---|---|---|---|
| Extraction | PDF → `pdf_extractor.pdf_to_txt` (dehyphenate, soft-wrap rejoin, noise-line strip) then `runner._ensure_pdf_txt_has_chapter_heading`; TXT copied | PDF → `extract_text_from_pdf`; TXT read `utf-8-sig` | GUI `pdf_to_txt` helper, then file read `utf-8-sig` | same | same |
| Structure | `epub2tts_edge.get_book` (:118): `Title:`/`Author:` header, `#` chapters, one paragraph per line | **none** — raw text (a `Title:` or `#` line would be spoken) | inline loop `kokoro_file_to_mp3` (:251): drop `Title:`/`Author:`, strip `#` | identical inline loop (:1445) | `qwen3_synth.prepare_text` (:89): same, plus a heading becomes its own paragraph |
| Sentence boundaries | NLTK Punkt, deep-copied with `i.e`/`e.g` added (`sent_tokenize` :108) | character window; last `.!?` + whitespace (`batch_convert.split_into_chunks` :57) | same window splitter, ceiling 3000 (`kokoro_synth.split_into_chunks` :178); Kokoro then splits on `\n+` | regex `_SENTENCE_BOUNDARY` + paragraph/clause hierarchy (`split_for_chatterbox` :541) | word-level `_is_sentence_end` with an abbreviation set (`plan_chunks` :208) |
| Ceiling | per sentence; then split at comma (300 ms), `...` (600 ms), `—`/`--` (400 ms) (`intra_sentence_chunks` :239) | 3000 chars | 3000 chars | **300 chars** (evidence: silent truncation, Phase 12) | **600 chars** (measured, CP5) |
| Text transforms inside the engine | `edge-tts` XML-escapes and splits at 4096 bytes; Microsoft's service normalizes server-side (not under ACT's control) | same | `misaki` G2P: `num2words` for numbers, years, ordinals, currency (`misaki/en.py:370–440`) | wheel `punc_norm`: first-letter capital, `…`→`, `, `—`/`–`→`-`, curly→straight quotes, adds a final stop; **colon→comma patched by ACT** (`_structural_colon_punc_norm`) | none known; model-native |
| Pauses | sentence 800, paragraph 850, title 1200, chapter 2000, end 3000 ms (`epub2tts_edge.py:49–57`) | 50 ms between chunks, 3 s end | preset chunk/end pauses | preset pauses + **75 ms after a prose colon** (`COLON_PAUSE_MS`) | preset paragraph pause after **every** chunk, end pause once |
| Content proof | tests only | tests only | tests only | **runtime** `_assert_content_preserved` (every non-whitespace character, in order) | **runtime** `verify_plan` (ordered source spans + same invariant) |
| Assembly | PCM (`pydub`), one final encode | decode chunks once, one final encode | PCM, one final encode | PCM, one final encode | PCM, one final encode |

The GUI's single dispatch (`epub2tts_gui.py` ~2866) chooses the engine; Edge alone has two code paths (direct vs folder).

### 3.2 What is duplicated and what is a proven necessity [V]

**Duplicated today (candidates for sharing):**

1. UTF-8-sig decoding — five copies.
2. Header/heading structure — **four** implementations that agree except where noted (Kokoro, Chatterbox, Qwen3, Edge `get_book`), plus Edge folder which has none.
3. Paragraph/line cleanup and the "newline contract".
4. Sentence boundary detection — **four** algorithms (Punkt, regex, word-level, character window).
5. Source-preservation proof — runtime for two engines, test-only for the other three paths.
6. Number, symbol, abbreviation and URL handling — **none shared**; each engine is model-native (Kokoro by its own G2P).
7. Pronunciation overrides — none (see 3.3: previously forbidden).

**Proven model-specific necessities (must survive any sharing):**

| Id | Necessity | Evidence |
|---|---|---|
| N1 | Chatterbox 300-character ceiling and the content-preservation proof | A 2,889-character chunk produced 3.84 s of audio for ~181 s of text and reported success (Phase 12). |
| N2 | Chatterbox newline contract; colon patch; prose-colon split with a 75 ms pause | Decisions 2026-09-21 iteration 5/6; `COLON_PAUSE_MS` chosen from a 0/75/125 ms listening set on 2026-08-16. |
| N3 | Chatterbox pathological-silence retry, fail-closed | Decisions 2026-09-24. |
| N4 | Edge: pause-by-splitting at comma/ellipsis/dash (SSML is escaped, so `<break>` cannot be used); `!`/`?` collapsing; PCM assembly; Punkt `i.e`/`e.g` | Decisions Phase 5 iterations 1, 2, 4; Phase 6 integration. |
| N5 | Kokoro 3000-character chunking, `split_pattern=\n+`, speed, its own G2P | `kokoro_synth.py`. |
| N6 | Qwen3 600-character whole-sentence plan, ordered source spans, per-chunk seeds, paragraph pause after every chunk, worker process | `qwen3_synth.py`; `derive_seed` hashes `chunk.index` and `chunk.text`. |
| N7 | Per-engine timing presets | `voice_registry.py`. |

### 3.3 Owner-approved fixes, rejected experiments and standing constraints [V]

| Item | Status | Source | Constraint on Plan 01B |
|---|---|---|---|
| Edge PCM-domain assembly, one final encode | Approved, integrated | Decisions 2026-09-21 it. 1/4; Phase 6 | Untouched. |
| NLTK Punkt `abbrev_types` + `i.e`/`e.g` | Approved, integrated | it. 2/4; Phase 6 | `i.e.`/`e.g.` stay as written; the normalizer must not expand them. |
| Chatterbox structural-colon patch (times, ratios, `://` keep their colon; prose colon → comma) | Approved, integrated — **temporary compatibility behaviour** (owner, 2026-10-19) | it. 5; Phase 6 | Untouched by B1 and until checkpoint A6 passes. Times (`6:45`), ratios (`3:1`) and URLs were judged **B PASS natively *with* the patch**: that is the evidence baseline retirement must meet or beat, not a veto on retiring it. |
| 75 ms pause after a prose colon (`split_at_prose_colon`) | Approved — **temporary compatibility behaviour** | `COLON_PAUSE_MS` | Same: kept through B1; A6 defines the acceptance test for replacing it. Until then a normalizer must neither add nor remove prose colons. |
| Terminal pause-supersede candidate | **Rejected** | it. 3 | Do not re-propose. |
| Kokoro colon→comma substitution | **Rejected** (no audible improvement) | 2026-09-23 | Do not re-propose; the longer Kokoro colon pause is model-native. |
| Edge sentence-pause-parity rewrite | Forbidden without new evidence | plan §15 | Segmentation differences between Edge paths remain. |
| `pysbd` instead of Punkt | Evaluated, not adopted | Phase 4 | Keep Punkt/NLTK. |
| Chatterbox HTTPS URL pronunciation | Model-native, closed | it. 6 | URLs are **protected spans**, never respelled in v1. |
| **"No pronunciation dictionary"** (P9) — `test_chatterbox_tuning.py::test_no_hardcoded_pronunciation_substitutions_exist` forbids word rules in executable engine code; `test_the_engine_does_not_rewrite_source_words_before_synthesis` forbids `.replace(` in `chatterbox_file_to_mp3` | Standing, **superseded in part** by the 2026-10-19 approval of a shared spoken-form glossary | Decisions 2026-09-21/-24; those tests | The glossary is **data** consumed by a shared module; engine files stay free of word rules, so both guards remain valid unmodified (4.5, [D9]). |
| Retry Failed reproduces the original attempt from the frozen `RunSnapshot` | Standing | Decisions Phase 6 | Speech-preparation settings and the glossary content hash are frozen into the run (4.8). |
| Content preservation: every non-whitespace character, in order | Standing invariant | Chatterbox/Qwen3 runtime, `test_segmentation_source_span.py` (37 tests) | Re-based onto source↔spoken mappings (4.4). |
| Bounded retries fail closed | Standing | Decisions 2026-09-24 | Applies to any new retry; the normalizer needs none. |

Regression anchors that already exist and must stay green: `test_segmentation_source_span`, `test_chatterbox_chunking`, `test_chatterbox_colon_integration`, `test_chatterbox_punc_norm_evidence`, `test_chatterbox_tuning`, `test_chatterbox_selected_tuning`, `test_chatterbox_silence_retry`, `test_chatterbox_longform`, `test_edge_direct_pcm_assembly`, `test_batch_convert_folders`, `test_tts_text_bom`, `test_tts_contentless_source`, `test_quality_corpus`, `test_qwen3_synth`, `test_kokoro_timing_wiring`.

### 3.4 What each engine does natively with numbers and symbols [V unless stated]

* **Kokoro (`misaki` 0.9.4, `Lexicon.get_number`)** — handles cardinals, ordinals, currency (with a currency-symbol flag), decimals, via `num2words`. **Any bare four-digit integer with no currency symbol is read as a year** (`num2words(int(word), to='year')`), regardless of context, so "1250 pages" becomes "twelve fifty pages" (code reading plus a `num2words(1250, to='year')` probe; not audio-verified today). Inline markup `[word](/phonemes/)` is supported (README example `[Kokoro](/kˈOkəɹO/)`). README states no text-normalization expectation.
* **Chatterbox Turbo (wheel 0.1.7)** — `punc_norm` as in 3.1; numbers are model-native. The pinned wheel exposes no documented tag or markup syntax that ACT relies on.
* **Edge** — Microsoft's service normalizes server-side; behaviour for the read-aloud endpoint is undocumented, so it is treated as a black box and measured, not assumed.
* **Qwen3-TTS** — model-native; the evaluation corpus is English prose with few numerals.
* **Probe, read-only today:** `num2words` 0.5.14 returns `'one thousand, two hundred and fifty'` for 1250, `'two thousand and five'` for year 2005, `'nineteen oh-five'` for year 1905, `'twelve dollars, fifty cents'` for $12.50. Its default spoken forms therefore contain **commas, "and" and hyphens** — relevant because commas trigger Edge's 300 ms intra-sentence pause (`,(?!\d)\s`) and clause splits in the Chatterbox and Qwen3 chunkers.

### 3.5 Library research [V; no installation performed]

Sources: PyPI JSON metadata (official), each project's README, and the conda-forge feedstock. All checked 2026-10-19. ACT's project licence is **GPL-3.0** (README), so every candidate below is licence-compatible; licence is not a differentiator.

| Candidate | Licence | Windows / macOS / Python 3.12 via the app's pip + venv bootstrap | Dependencies | Coverage / determinism | Verdict |
|---|---|---|---|---|---|
| **NVIDIA NeMo-text-processing** 1.2.0 (Jun 2026) | Apache-2.0 | **Not supported.** Its README: "Pip installation on MacOS and Windows are not supported due to the dependency Pynini"; recommends `conda install -c conda-forge pynini=2.1.6.post1`. It pins `pynini==2.1.6.post1`. Checked across **every** pynini release on PyPI: wheels exist only for Linux x86_64 (cp312 included) plus a source distribution that needs OpenFst and a compiler; **no Windows or macOS wheel has ever been published**. conda-forge's feedstock lists `win_64` and `osx_arm64` builds, but ACT bootstraps with Python + pip, not conda. | pandas, transformers (unpinned; ACT pins `transformers==5.2.0`), sacremoses, inflect, regex, joblib… — conflict risk with the pinned Kokoro/Chatterbox stack (cf. memory: chatterbox dependency conflict) | WFST tagger + verbalizer, whitelist class has priority over other classes, deterministic by default; compiles/caches grammars | **Reject for production.** Possible as an *offline reference oracle* on Linux only; not needed. |
| **WeTextProcessing** 1.2.0 (Jun 2026) | Apache-2.0 | README makes **no** Windows/macOS statement; depends on `pynini>=2.1.6` (same Linux-only PyPI wheels). | pynini, importlib_resources | Chinese-first; English TN exists but "no controllable options yet"; FST graphs built on first use and cached | **Reject** (same install barrier; English not configurable). |
| **num2words** 0.5.14 (Dec 2024) | LGPL (PyPI classifier; version not stated in metadata — read `COPYING` before adoption) | Pure-Python wheel; already installed in the root venv as a transitive dependency of `misaki` (so also present wherever Kokoro is); **not** in `.venv-qwen3` and **not** pinned in `scripts/requirements.txt` | docopt | cardinal, ordinal, `ordinal_num`, year, currency; English variants `en`, `en_GB`, `en_IN`, `en_NG`; README calls its test suite "rather thin"; default outputs contain commas/"and"/hyphens | Usable as a verbalizer **or** test oracle; style needs post-processing. |
| **inflect** 7.5.0 (Dec 2024) | MIT | Pure-Python wheel | more_itertools, typeguard | `number_to_words` (group, andword, zero, one, decimal, threshold), ordinals, plurals; its README documents **no year, currency or date handling** | Not needed for v1 (units can use an explicit singular/plural table). |
| **gruut** 2.4.0 (Jul 2024) | MIT | **sdist only** (no wheel published) | Babel, dateparser, num2words, numpy, python-crfsuite, language-data packages | Full G2P + number handling, English | Reject (heavy dependency set and a G2P scope far beyond the need). |
| **Microsoft Recognizers-Text (Python)** 1.0.2a2 | MIT | pure wheels | regex, datedelta | entity recognition for numbers/dates/units | **Reject** — last PyPI release 2019-11-12 (an alpha); no Python maintenance since. |
| **quantulum3** 0.10.0 (Mar 2026) | MIT | pure wheel | inflect, num2words | quantity/unit extraction with a large unit DB | Reject for v1 (ACT needs ~40 units, explicit table is clearer). |
| **spaCy** (already a `misaki` dependency, 3.8.15) | not checked | present in the root venv only because Kokoro needs it; models are separate downloads | — | NER could disambiguate | Reject: couples a universal pipeline to the Kokoro stack (`python_version < "3.13"`). |
| **pysbd** 0.3.4 (2021) / NLTK Punkt | MIT / Apache-2.0 | pure | — | sentence boundaries | Already evaluated (Phase 4): keep Punkt; **sentence splitting is not part of v1 sharing** (4.1). |
| **Unidecode** 1.4.0 | GPL-2+ | pure | — | transliteration | Not needed. |
| **ACT-owned rules** + small in-house English verbalizer | project | pure Python, `re`/stdlib | none new | exactly the contract in 4.3; US style without commas/"and"/hyphens; fully deterministic; testable against `num2words` as a dev-time oracle | **Recommended** [P] ([D5]). |

**Conclusion [P].** WFST toolkits (NeMo, WeText) are the right technology for large-scale TN but cannot be installed by ACT's non-technical, pip-only, Windows/macOS bootstrap, and they pull in dependencies that collide with the pinned stack. `num2words`/`inflect` give numbers but not context, and neither emits ACT's required comma-free style. The recommended design is therefore **ACT-owned, conservative, context-cue rules with an in-house US-English verbalizer**, using `num2words` only as an optional dev-time cross-check. Honest limit: grammar quality of NeMo/WeText on ACT's corpus was not measured (no installs allowed).

### 3.6 Script-tree facts for the relocation [V]

* Import root today is `scripts/Universal/`; code imports `shared`, `tts`, `mp3_tools` as top-level packages. **If `scripts/` becomes the import root and `shared/`, `tts/`, `mp3_tools/`, `launcher.py` move up one level, no `import` statement changes anywhere** (production 49 files import `shared`, 22 import `mp3_tools`; tests 146/76).
* `scripts/MacOS/` and `scripts/Windows/` contain only `.gitkeep`; `scripts/Universal/tests/` is an empty folder holding only `__pycache__`.
* **Depth-dependent code (must change):** `shared/paths.py:32`, `shared/bootstrap.py:57`, `shared/ffmpeg_health.py:80`, `shared/ffmpeg_portable.py:52` (`REPO_ROOT = SCRIPTS_DIR.parent.parent`); `shared/cleanup_state.py:114` (four `.parent`); `shared/cleanup_worker.py:68–69` (four `.parent` and the literal `"scripts"/"Universal"/"shared"` marker); `shared/release.py:50` (`SHARED_DIR.parent.parent`); `tts/chatterbox_synth.py:703` and `tts/qwen3_runtime.py:103` (`parents[3]`). Unchanged by the move: every `_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent` (it *is* the import root), `epub2tts_edge.py:25` (`parents[2]`).
* **Literal path strings:** `shared/config.py:120` (`DEFAULT_ENTRY_POINT`), `config.toml:35,46`, `Setup_and_Run-audiobook-creation-tool.bat:9,19`, `.command:9,75,112`, `scripts/verify.py:45–46` (`IMPORT_ROOT`), `shared/version.py`, `shared/bootstrap.py` docstrings, `files/dev-tools/{qwen_eval_baseline_worker,qwen_eval_cli,voice_previews}.py`, the local adapter notes `.claude/CLAUDE.md` and `.codex/CODEX.md`, and the live sections of `Briefing.md`/`Handoff.md`.
* **Tests:** 200 occurrences in 87 files, almost all the single pattern `"scripts" / "Universal"` (constants such as `UNIVERSAL = REPO_ROOT / "scripts" / "Universal"`), plus synthetic fake-repository fixtures that create `scripts/Universal/launcher.py` for config, bootstrap and packaging tests.
* **Packaging:** `shared/release.py` archives the tracked `scripts/` tree under the same relative names; the launchers expect `<repo>/scripts/.../bootstrap.py`. Archive-membership tests name `scripts/Universal/...`.
* **Ignored runtime state is path-independent [V]:** `.venv/.requirements-state.json` records `scripts\requirements.txt` (unchanged location); `.venv/.import-proof.json` records the interpreter; the Chatterbox derivative/conditional cache digest uses source SHA-256, package, model and clip spec — no code path; Qwen3 state records requirements/manifest hashes; no `.pth` file in either venv names `Universal`. Historic mentions exist only in old launch logs.
* **Coupling prices for the optional package split:** `mp3_tools` is referenced 79 times in 22 production files and **592 times in 76 test files** (including pinned file paths in `test_plan3_boundaries.ADOPTED`, hash-gate and AST tests).

---

## 4. Workstream A — universal speech-preparation pipeline

### 4.1 Architecture [P]

```
source (.txt, or .pdf -> existing pdf_extractor -> txt)                    unchanged
   |  decode utf-8-sig
   v
[1] structure   Title:/Author:/# -> typed Blocks (title | heading | paragraph)     shared      A1
   v
[2] hygiene     invisible characters, ligatures  -> Edits                          shared      A2
   v
[3] normalize   protected spans -> glossary -> structured classes -> numerics ->    shared      A2
                abbreviations/romans -> (everything else untouched) -> Edits
   v   SpokenDocument(source, blocks, spoken, edits, report, speech_prep_version)
[4] engine adapter   which classes this engine accepts (mode table), charset guard,  per engine  A3
                     optional phoneme markup (Kokoro only)
   v
[5] engine segmentation + ceilings + pauses (existing code, unchanged)             per engine
   v
[6] synthesis -> assembly -> one encode (existing code, unchanged)
```

* **Location [P]:** new package `scripts/tts/speech/` (after B1), pure Python, standard library only: `document.py` (structure), `normalize.py` (engine of rules, edits, mapping), `numbers_en.py` (verbalizer), `classes.py` (class rules), `glossary.py`, `profiles.py` (engine capability profiles and the mode table), `integrity.py`, `report.py`, `data/` (class tables, default glossary, mode table). It imports nothing from `tts.*` engines or `shared.job_ui` (the Plan 3 boundary pins adopters at exactly twenty modules; this package is not a UI module).
* **Sentence splitting is deliberately not unified in v1 [P].** Four splitters carry approved audio behaviour (N1, N4, N6). The pipeline normalizes *before* they run (which removes several false boundaries — "3.5", "Dr.", "No. 5" lose their stops — and can only help them) and then hands text to the unchanged engine code. A shared splitter is a possible later step behind its own A/B gate, not part of this plan.
* **Where it runs [P]:** in the app process, in the file worker, before the engine call — for Qwen3 that is already where `prepare_text`/`plan_chunks` run (the worker subprocess never sees raw text). For Edge direct it runs on the work TXT *before* `get_book`, leaving `Title:`/`Author:`/`#` markers untouched; for Edge folder before `split_into_chunks`.
* **Performance budget:** single left-to-right pass, linear; a 1 MB book prepared in well under a second; enforced by a test with a generous bound.

### 4.2 Structure stage (A1: pure refactor) [P]

`load_speech_text(path) -> SpeechDocument` replaces the three inline copies with one implementation that is byte-identical to the current behaviour of each engine, selected by `StructureOptions`: `heading_as_paragraph` (False for Kokoro/Chatterbox today, True for Qwen3), `honour_header_markers` (True for all but Edge folder today). Equivalence is proven against reference copies of the old loops kept inside the tests, on the quality corpus and a randomized header/heading generator. Edge `get_book` stays (it also builds chapters and titles); only its decode step is shared. **No audio changes in A1.** Whether Edge folder should honour `Title:`/`Author:`/`#` and whether Kokoro/Chatterbox should adopt heading-as-paragraph are audio-affecting unifications left to the owner ([D10], [D11]); the default is to preserve today's behaviour exactly.

### 4.3 Normalization contract [P]

**Scope.** English (en-US) only. Any block whose language is not recognisably English is passed through unchanged. No machine learning, no network, no randomness, no clock: the same input and the same rule/glossary versions always yield the same output and the same hash.

**Principles.**

1. **Identity by default.** Text containing no triggering pattern comes out **byte-identical**. (A direct consequence: the voice-preview sentence and the existing evaluation passages, which contain no numerals or symbols, are unaffected — enforced by a test.)
2. **Prefer unchanged to guessed.** An expansion needs a positive cue. No cue or conflicting cues ⇒ leave the token and record a diagnostic (4.3 "Ambiguity").
3. **Add no prosody.** Spoken forms consist only of letters and apostrophes separated by single spaces — **no commas, hyphens, colons, ellipses or digits** — because engines turn those into pauses or splits (Edge `,(?!\d)\s`, Chatterbox `_CLAUSE_BOUNDARIES`, Qwen3 `_CLAUSE_LEVELS`, the Chatterbox prose-colon split). An edit replaces only the matched token; it never consumes adjacent sentence punctuation, quotes or whitespace.
4. **Single pass, non-recursive.** Output of a rule is never re-scanned by another rule.
5. **Traceable.** Every change is an `Edit(source_start, source_end, spoken, rule_id, rule_version, class, confidence)`.
6. **Structure is sacred.** `Title:`, `Author:`, `#` markers, blank lines and paragraph breaks are never altered; heading *text* is normalized like body text.

**Rule precedence (highest first); longest match wins within a level, then earliest rule id.**
0. Protected spans — structural markers; URLs, e-mail addresses, file paths; anything the owner later declares (e.g. bracketed tags). Recorded, never edited.
1. User glossary entries.
2. Bundled glossary entries.
3. Hygiene (invisible characters, ligatures).
4. Structured multi-token classes: date, time, currency, measurement, range, fraction.
5. Single-token numerics: percent, ordinal, decimal, year (cue required), cardinal.
6. Abbreviations and Roman numerals (cue required).
7. Symbols (cue required).
8. Everything else: untouched.

**Classes, tiers and examples.** Tier 1 = enable once the gate in section 6 passes for that engine; Tier 2 = candidate, individually gated; Tier 3 = deliberately never expanded in v1.

| Class | Example in → out | Tier | Ambiguity handling |
|---|---|---|---|
| HYG hygiene | `ﬁsh` → `fish`; U+00AD/U+200B removed; NBSP → space | 1 (mechanical check only) | none |
| CARD cardinal | `1,250` → `one thousand two hundred fifty`; `12` → `twelve`; `1,000,000` → `one million` | 1 | leading-zero (`007`), over 15 digits, `1.2.3`, identifiers: unchanged |
| DEC decimal | `3.5` → `three point five`; `0.07` → `zero point zero seven` | 1 | `1.2.3`, section numbers at line start, `v2.0`: unchanged |
| ORD ordinal | `21st` → `twenty first` | 1 | none |
| PCT percent | `12.5%` → `twelve point five percent` | 1 | none |
| CUR currency | `$12.50` → `twelve dollars fifty cents`; `$5` → `five dollars`; `£3`, `€2` | 1 | `$` without a following number: unchanged |
| YEAR | `in 1999` → `in nineteen ninety nine`; `1905` → `nineteen oh five`; `2005` → `two thousand five`; `2024` → `twenty twenty four`; `1990s` → `nineteen nineties` | 1 (cue required) | four-digit 1100–2099 needs a cue: preceded by in/since/by/until/from/before/after/during/circa/year/of or a month name, or followed by AD/BC/CE/BCE/`s`. No cue and no count-noun context ⇒ ambiguous |
| TIME | `7:05` → `seven oh five`; `7:00` → `seven o'clock`; `7:15 p.m.` → `seven fifteen p m` | 2 | needs am/pm or a cue (at/by/until/around/before/after/o'clock); `3:15` with no cue ⇒ ambiguous with a ratio ⇒ unchanged |
| RATIO | `3:1` → `three to one` | 2 | only with minutes ≥ 60, hour > 24, or a cue (ratio/odds/score) |
| DATE | `March 5, 2024` → `March fifth twenty twenty four`; ISO `2024-03-05` → same | 2 | `03/05/2024` is locale-ambiguous ⇒ always unchanged |
| RANGE | `pages 12-15` → `pages twelve to fifteen` | 2 | needs a cue (pages/pp./ages/years/hours/from); otherwise a minus sign is possible ⇒ unchanged |
| FRAC | `1/2` → `one half`; `3/4` → `three quarters` | 2 | confusable with dates ⇒ only with a trailing noun/unit cue |
| UNIT | `5 km` → `five kilometers`; `72°F` → `seventy two degrees Fahrenheit` | 2 | explicit unit table (~40) with singular/plural; `5'10"` ⇒ unchanged |
| TITLE | `Mr.` → `Mister`; `Mrs.` → `Missus`; `Dr.` → `Doctor` (before a capitalised name) | 2 | `St.` (Saint/Street), `No.` ⇒ unchanged |
| ROMAN | `Chapter IV` → `Chapter four`; `Henry VIII` → `Henry the eighth` | 2 (cue: Chapter/Book/Part/Act/Volume/Section, or a capitalised name before) | single `I`, `V`, `X`, `L`, `C`, `D`, `M` ⇒ never |
| SYM | `&` → `and` between words; `×` → `times` between numerals | 2 | `@`, `#`, `/`, `+`, `=`, `§`, `©`: Tier 3, unchanged |
| PROT | URLs, e-mails, paths | — (protected) | never respelled in v1 (closed finding). **Their colons (`://`, `C:\`) still rely on the Chatterbox shim until A6 settles them** (see A6 prerequisites) |
| ABBR | `e.g.`, `i.e.`, `etc.`, `vs.` | 3 | unchanged (approved Punkt path) |

**Ambiguity policy.** (1) Positive cue ⇒ expand. (2) Conflicting or absent cue ⇒ **leave unchanged** and emit an `AmbiguousToken(offset, text, candidates, reason)` diagnostic. (3) The en-US convention is fixed; the pipeline never silently picks between locale conventions. (4) *Engine-risk override:* when an engine is **documented** to misread a class natively, its profile may select a candidate for an ambiguous token — the one concrete case today is Kokoro's cue-less four-digit integers (3.4), a cue-less number followed by a lower-case word is plausibly a cardinal. **No exception is approved** ([D8]): first a Kokoro-specific mechanical probe of the G2P output (1250, 1500, 2024, 1999, 2500, 5000 in cue and no-cue sentences) and then an A/B; only a documented, reviewed result may add a mode-table exception (4.6). (5) Diagnostics are summarised in the run's Details; they never block conversion.

**Spoken-form style (decisions [D7]).** Recommended: US style without "and" in whole numbers (`one hundred one`), years in pairs (`nineteen oh five`, `two thousand five`, `twenty twenty four`), `o'clock`, `oh` for the zero in minutes and years, no hyphens (`twenty one`).

### 4.4 Source mapping and integrity checks [P]

* **Mapping basis.** All offsets index the *decoded or extracted source text*: the TXT exactly as read with `utf-8-sig`, or the text that `pdf_extractor` produced from a PDF. Nothing here claims to reconstruct the original PDF's page layout, fonts or reading order; `reconstruct_source` rebuilds that text and nothing earlier.
* `NormalizedText.edits` is an ordered, non-overlapping list; `spoken_to_source(offset)` and `source_to_spoken(offset)` are monotone and answered by binary search over edit boundaries.
* Chunk plans carry **both** spans. Qwen3 `Chunk.start/end` currently index the prepared text; they become spoken-text offsets and gain `source_start/source_end`; seeds remain derived from spoken chunk text, so documents with **no edits** keep **identical chunks and seeds** (existing recordings stay reproducible), and documents with edits change only from the first edited chunk onward. `PIPELINE_REVISION` is bumped when the wiring is enabled (the module already says to bump it "whenever a change can alter generated audio").
* Existing proofs are re-based, not weakened: Chatterbox `_assert_content_preserved` and Qwen3 `verify_plan` run against the **spoken** text exactly as today; the pipeline adds an upstream proof that `reconstruct_source(spoken, edits)` equals the decoded/extracted source text byte-for-byte.
* **Versioning.** `RULESET_VERSION` (an integer, bumped on any rule, class-table or verbalizer change and recorded in the Changelog) and each rule's own `rule_version` appear in every `Edit`. `speech_prep_version = sha256(RULESET_VERSION | mode-table hash | bundled-glossary hash | user-glossary hash | user-override hash)` is recorded in the run Details for display and regression detection. The version string is metadata only: it never enters Qwen3's seed derivation, which depends solely on the chunk index and the spoken chunk text, and it is **not** what freezes a run (4.7).
* Full invariant list (each a test): (I1) identity on trigger-free text; (I2) reconstruction; (I3) edits ordered, non-overlapping, inside the source; (I4) every protected span unchanged; (I5) spoken edits contain only `[A-Za-z' ]`; (I6) idempotence — normalizing already-spoken text changes nothing except still-ambiguous tokens; (I7) no empty block created; (I8) structural markers byte-identical; (I9) determinism — same input, same `speech_prep_version`, same output hash on repeated runs; (I10) bounded time.

### 4.5 Spoken-form pronunciation glossary [P]

* **Data, not code.** `scripts/tts/speech/data/glossary.default.json` (tracked, **ships empty** — [D9]) and a user file `files/runtime-data/speech/glossary.user.json` (ignored, survives updates). Engine modules contain no word list; the existing P9 guards stay valid unchanged.
* **Entry:** `{"id", "written", "spoken", "match": "word"|"exact", "case": "sensitive"|"insensitive", "preserve_case": bool, "engines": ["*"]|[…], "note", "added"}`. `spoken` is validated to the 4.3 charset (letters, apostrophes, spaces), non-empty, ≤ 80 characters, and must not contain `written`. No regular expressions in v1 (no ReDoS surface).
* **Precedence:** user > bundled > rules; the first matching entry wins; overlaps are rejected at load. Engine scoping lets an owner give Chatterbox a respelling that Kokoro does not need.
* **Engine capability:** an optional `"phonemes"` field is honoured only by a profile that declares phoneme markup (Kokoro: `[written](/phonemes/)`); other engines ignore it and use `spoken`.
* **Validation and safety:** load errors are reported once with the offending entry; a broken user glossary never blocks a run (it is skipped with a visible note); the loaded content hash is part of `speech_prep_version`.
* **Reconciliation with P9 [D9]:** the owner's approval supersedes "no pronunciation dictionary" only for this data-driven, owner-curated glossary. Hard-coding "Ascended"/"Tamar" or any book's words in code stays forbidden; those are *user-glossary examples*, not bundled entries. A new Decisions entry records the supersession; the guard tests are not edited.

### 4.6 Engine adapters and the mode table [P]

Each engine has an `EngineProfile` (code) and a **mode table** (data) with one cell per (engine, class): `expand` | `native` | `glossary_only`. **During rollout every cell starts at `native`** ([D6]): the pipeline *computes* edits for all classes, but an engine applies only the cells that have passed review (section 6, A4/A5). This protects behaviour the owner already approved — notably Chatterbox's native handling of `6:45`, `3:1` and prose colons — *until* evidence shows a shared rule is at least as good. It is rollout state, not the destination (next paragraph).

| Profile field | Edge direct | Edge folder | Kokoro | Chatterbox | Qwen3 |
|---|---|---|---|---|---|
| Honour header markers | yes | no today ([D10]) | yes | yes | yes |
| Heading as own paragraph | n/a | n/a | no | no | yes |
| Max chunk (kept) | per sentence + intra-sentence splits | 3000 | 3000 | 300 | 600 |
| Prosodic punctuation to avoid in spoken forms | comma, `...`, dash | — | comma, colon | comma, colon, semicolon, dash | comma, colon, semicolon, dash |
| Phoneme markup | no | no | **yes** | no | no |
| Documented native risk | server TN unknown | same | any cue-less 4-digit read as a year | unknown for years/currency | unknown |
| Colon rule | unchanged | unchanged | unchanged (rejected experiment) | patched `punc_norm` + 75 ms stays | unchanged |
| Pre-existing prep kept | Punkt + `i.e`/`e.g`, `!`/`?` collapse | char window | `\n+` split | newline contract, content proof | spans, seeds |

**Convergence and the end state [D6, decided].** The final architecture is **one shared rule set applied identically to every engine**: Tier-1 classes are `expand` everywhere, and the mode table shrinks to the genuine exceptions. An exception is permitted only with (a) recorded evidence (an A/B verdict or a mechanical probe), (b) a `Decisions.md` entry naming engine, class and reason, (c) a named review checkpoint at which it is re-tested, and (d) independent (Codex) review. Profiles choose which classes apply and enforce the charset guard; **they never contain rules** — all rule code lives only in `scripts/tts/speech/`, enforced by a static test — so there are never four separately maintained normalization implementations. Every non-`expand` cell is listed in the run Details and in the Handoff as an "exception report" so none can persist silently.

### 4.7 Settings, UI surface, snapshot and Retry [P]

* No new UI in Plan 01B. A tri-state `tts.speech_prep` (`off` | `v1`) is added as a developer setting (the settings allowlist `USER_STATE_SETTINGS`/`config.toml` schema gain the key; additive, defaulted, so existing `settings.json` files remain valid).
* **Immutable run-scoped copy — a hash alone does not freeze anything.** At run start the panel builds one `SpeechPrepSnapshot` **by value**: the effective mode table (every cell), the merged and validated glossary entries (bundled + user, in precedence order, after validation), the user-override cells, `RULESET_VERSION`, and a content hash. It is deep-frozen (tuples, frozen dataclasses, read-only mappings) and stored inside the run's frozen options (`freeze_tts_options` gains `speech_prep`); worker threads read the snapshot and **never re-read a file**. The hash exists for display and tamper/regression detection only. Retry Failed re-uses the original `RunSnapshot`, hence the original snapshot, so editing `glossary.user.json` or `modes.user.json` mid-run or before a retry cannot change an attempt or its retry; a *new* run reads the files again. If a snapshot must be persisted (for example across an app restart) it is written once as a read-only JSON copy inside the run's own folder and loaded from there.
* **User overrides.** Besides the glossary, an optional `files/runtime-data/speech/modes.user.json` may switch an individual (engine, class) cell between `expand`, `native` and `glossary_only`; it is validated against the same schema, ignored with a visible note if invalid, hashed into `speech_prep_version`, and absent by default.
* After the final gate the default flips to `v1` only for approved cells (everything else behaves exactly as today). A Preferences toggle and a glossary editor are deferred ([D12]); the Details view shows "Speech preparation: N edits, M ambiguous left unchanged" so behaviour is visible.

### 4.8 Test corpus and tests [P]

* `files/tests/golden/speech/corpus/*.jsonl` (A2; `files/test-files/` is gitignored local-fixture space, so tracked fixtures live under `files/tests/`) — one case per line: `id, input, expected, classes, engines, note`. Categories: every class above; **no-change prose** (including the full `DIFFICULT_SHORT` false-boundary text — it must remain identical except cells the owner approves); adversarial strings (`Catch-22`, `R2-D2`, `24/7`, `9/11`, `3D`, `4K`, `2nd Amendment`, `Apt. 4B`, `pp. 12-15`, `1.2.3`, `1250 Elm Street`, `December 25`, `10:30 a.m.`).
* `files/tests/golden/speech/` — **characterization goldens (A0), captured from the ORIGINAL implementation before any directory is moved**: for all five text routes, metadata, paragraphs, sentence/sub-chunk splits, chunks, punctuation, protected structural colons and Qwen3 seeds, via real production functions with fakes in place of every engine call. They are text/chunk/seed baselines — **no audio is regenerated, no synthesis or network call is made**. B1 and every later pure-refactor checkpoint must show zero diff against them.
* **Snapshot tests (A3):** a glossary edited after run start does not change the remaining files; a glossary edited before Retry Failed does not change the retry; the snapshot rejects mutation; a run started after the edit uses the new glossary; a corrupt user file after run start is irrelevant to that run.
* Property tests with a seeded generator (no new dependency): I1–I10 from 4.4.
* Static guards: the `speech` package imports no network, `random`, `time`, `shared.job_ui` or any engine module; engine files contain no word rules (existing P9 guards); the bundled glossary ships without book-specific words.
* A dev-only cross-check of the in-house verbalizer against `num2words` (skipped when absent, e.g. Python 3.13 without Kokoro).
* Mutation checks on every rule family and every invariant, as in CP6.

---

## 5. Workstream B — `scripts/` reorganization

### 5.1 Target trees [P]

**Level 1 (mandatory, mechanical — checkpoint B1):**

```
scripts/
  launcher.py
  verify.py                 requirements.txt        qwen3-requirements.txt
  shared/                   application-wide: bootstrap, paths, config, settings, ui_theme, job_*, ffmpeg_*, release, ...
  tts/                      TTS panel, engines (Edge, Kokoro, Chatterbox, Qwen3), voice registry, PDF extraction
  mp3_tools/                MP3 Tool, M4B Converter / Maker / Metadata Editor, Cover Image, artwork
```
(`scripts/Universal/`, `scripts/MacOS/`, `scripts/Windows/` and the empty `Universal/tests/` are gone. Git history follows via `git mv`.)

**Level 2 (with Workstream A — no movement, a new package):** `scripts/tts/speech/` (4.1).

**Level 3 (optional, separately approved, priced — [D3]):** split `mp3_tools/` along the boundaries its filenames already encode:

```
scripts/
  mp3/        mp3_tool, mp3_plan, mp3_processing, mp3_workflow                       (4 files)
  m4b/        converter/ maker/ metadata/ + common (probe, staging, naming, numbering, chapters, commands, execution, winaudio)  (~22 files)
  artwork/    cover_resizer, m4b_artwork, m4b_artwork_ui, mp3_artwork                 (4 files; shared by MP3 Tool, Maker, Metadata Editor)
```
Cost [V]: 592 test references in 76 files and 79 production references in 22 files, plus pinned paths (`test_plan3_boundaries.ADOPTED`, Plan 6 hash-gate and AST tests). It is a scripted, reviewable codemod, but it is the single largest churn in the plan and delivers readability, not behaviour. **Recommendation: do not include it in Plan 01B;** keep `mp3_tools/` (its `mp3_*`, `m4b_*`, `cover_*` prefixes already group it) and decide Level 3 after S5. **Decided [D3]:** deferred until after S5; B1 adds `scripts/README.md` and short per-package module maps now (no code churn), so the TTS, MP3, M4B, artwork and shared components are easy to locate.

**Not recommended:** renaming TTS engine modules (`kokoro_synth` → `kokoro`, etc.) or regrouping `tts/` — they are referenced by pinned AST/path tests (`test_epub_retirement.PRODUCTION_TTS_SOURCES`, `ADOPTED`) for no behavioural gain.

### 5.2 Mechanical relocation procedure (B1) [P — authorised]

1. Branch `feature/0.6.7-speech-pipeline-and-layout` from `df0dbc28`; A0 goldens already committed from the original paths.
2. `git mv scripts/Universal/{launcher.py,shared,tts,mp3_tools} scripts/`; `git rm` the tracked `.gitkeep` placeholders in `scripts/MacOS` and `scripts/Windows`. **No other deletion:** ignored `__pycache__` folders and any untracked file under the old `scripts/Universal` are left exactly where they are ([D4]).
3. Fix the depth-dependent lines listed in 3.6 (nine sites) and the literal path strings (config, launchers, verify, release, dev-tools, live docs).
4. Reviewed mechanical update of `files/tests/` (`"scripts" / "Universal"` → `"scripts"`, synthetic fake-repository fixtures); every file that is not a pure substitution is reviewed by hand. Historical documentation is not rewritten.
5. **Layout canaries (new tests):** every module's derived repository root equals the git top level; `config.DEFAULT_ENTRY_POINT` and `config.toml`'s `entry_point` exist; no tracked source file mentions `scripts/Universal` outside an explicit historical allowlist; no tracked `scripts/MacOS|Windows|Universal` paths remain; the stale-upgrade warning (5.3) behaves as specified.
6. `scripts/README.md` and short per-package module maps ([D3]); Changelog entry (identity stays 0.6.6; no release), Briefing architecture section, Handoff.
7. Python package import names (`shared`, `tts`, `mp3_tools`) are unchanged, so no `import` statement changes.

### 5.3 Compatibility, upgrade behaviour and the bounded overlay-upgrade risk review [V/P]

* Nothing outside `scripts/` moves: `.venv`, `.venv-qwen3`, `files/`, models, recordings, settings, `config.toml` (only its entry-point string), the launchers (only their inner path strings).
* `scripts/` becomes the import root, so `scripts/verify.py` becomes importable as `verify`; no `shared`/`tts`/`mp3_tools` module has that name.
* **Stale-folder warning [D4].** Bootstrap emits a single warning when `scripts/Universal` still contains Python/JSON **source** files (bounded scan, ignoring `__pycache__`), naming the folder and telling the user it is no longer used and may be removed **by hand**. A folder holding only ignored bytecode caches triggers nothing. Bootstrap never deletes, moves or edits anything there.

| Scenario | Outcome | Handling |
|---|---|---|
| `git pull`/checkout onto an existing clone | tracked files move; ignored bytecode and any untracked local files remain in `scripts/Universal/` | no warning for bytecode-only; warning if untracked `.py` remain; nothing deleted |
| New release zip extracted over an old install | old `scripts/Universal/*.py` remain beside the new tree; inert (not on any import path) | one-line warning; user removes the folder by hand |
| Old launcher kept, new `scripts/` tree extracted | the old launcher looks for `scripts/Universal/shared/bootstrap.py` and fails with a missing-file error | the zip always carries the matching launchers at its root; release notes say to replace them together |
| Both trees present and an old tool started from the old folder | runs the old code against the same `files/` data; no data format changed | documented; no automatic action |
| macOS `.command` executable bit | preserved by the packager (existing test) | unchanged |
| `.venv`, `.venv-qwen3`, `files/runtime-data` | path-independent (3.6) | untouched |
| App running during the update | files in use may be locked on Windows | documented: close the app before updating |

---

## 6. Implementation checkpoints

**Authorised now: C0, A0 and B1 only.** Each checkpoint is a small scoped commit (or short series) on `feature/0.6.7-speech-pipeline-and-layout`, staged by explicit path, plain commit messages (no AI trailer — repository rule), pushed to the feature branch only after verification; no PR or merge. "Focused tests" are named sets, not the full suite. **★ = critical full gate** (`scripts/verify.py`, ~18 min), limited to three before S5 (B1, A5, S5). Flags default OFF until A5, so A1–A4 cannot change audio. Rollback is `git revert` of the checkpoint's commits unless stated.

| # | Checkpoint | Status | Deliverables | Focused tests | Gate / review | Owner gate |
|---|---|---|---|---|---|---|
| **C0** | Decisions, plan correction, branch | **authorised** | section 0 decisions recorded; this revision; branch from `df0dbc28` | — | — | — |
| **A0** | Characterization goldens from the **original** paths | **authorised** | `files/dev-tools/speech_characterization.py`; goldens under `files/tests/golden/speech/`; `files/tests/test_speech_characterization.py`; five routes (Edge direct, Edge folder, Kokoro, Chatterbox, Qwen3) | the new test plus the existing regression anchors; no synthesis, no network | none (no production change) | — |
| **B1** | Mechanical relocation (5.2) | **authorised** | tree per 5.1 Level 1; path fixes; test update; canaries; stale-folder warning; `scripts/README.md` maps; docs | A0 goldens zero-diff; canaries; bootstrap, paths, config, cleanup, packaging, Qwen3 and architecture-contract sets; archive layout proof (Windows and macOS, scratch paths) | ★ full gate once, after focused issues are fixed; Codex independent review | **Manual:** double-click the launcher on HOME-PC |
| **A1** | Shared structure loader (pure refactor) | proposed | `tts/speech/document.py`; Kokoro, Chatterbox, Qwen3 call it; Edge shares decode only | A0 goldens zero-diff; header/heading property tests; `test_tts_text_bom`, `test_tts_contentless_source`, `test_chatterbox_chunking`, `test_qwen3_synth`, `test_segmentation_source_span` | Codex | — |
| **A2** | Normalizer core + glossary (not wired) | proposed | rules, verbalizer, glossary, integrity, report, corpus; invariants I1–I10 | corpus goldens; property tests; static guards; mutation checks | Codex | — |
| **A3** | Adapters + wiring, flag OFF; run-scoped snapshot | proposed | profiles, mode table (all `native`), wiring at the five points, `SpeechPrepSnapshot` in `freeze_tts_options`, settings key, Details line | A0 goldens still zero-diff with the flag off; snapshot tests (mid-run edit, pre-retry edit, immutability); P9 guards; `test_plan3_boundaries` | Codex | — |
| **A4** | A/B corpus and listening | proposed | paired short clips where B ≠ A (7.2) | tool tests; mechanical checks per clip | — | **G1:** per engine × class verdicts, with every change to approved pronunciation or pacing listed (7.2) |
| **A5** | Enable reviewed cells | proposed | mode table from G1; glossary active; docs; Decisions entry; Qwen3 `PIPELINE_REVISION` | focused set + corpus; identity tests on the preview sentence and evaluation passages | ★ full gate; Codex | **G2:** one ~3-minute mixed passage per engine |
| **A6** | Retire the Chatterbox colon compatibility behaviour | proposed, **optional and gated** | remove `_ensure_structural_colon_patch`/`_structural_colon_punc_norm` and/or `split_at_prose_colon` + `COLON_PAUSE_MS` **only if** the criteria below pass; otherwise record a permanent, evidenced exception | the existing colon tests rewritten to the new contract (never deleted unreplaced) | Codex | **G3** |
| **B2** | Deep MP3/M4B package split | **deferred until after S5 [D3]** | own plan | — | own ★ gate | — |
| **S5** | Final CP6 qualification on the final tree | proposed | as in the CP6 addendum | — | ★ final full gate | owner manual gates |

### A6 — retirement of the Chatterbox colon compatibility behaviour (explicit criteria)

The structural-colon monkeypatch and the 75 ms prose-colon pause exist because the pinned wheel's `punc_norm` replaces **every** colon with a comma. They are **temporary**: B1 and A1–A5 leave them untouched, and nothing may claim they are removable until all of the following hold.

1. **Every structured colon has a defined fate.** Times and ratios are handled by the TIME/RATIO rules (expanded or deliberately left with a cue-based reason); the remaining colons that the wheel would corrupt — URL schemes (`://`), Windows-style paths (`C:\`), an ambiguous `3:15` left unchanged by the ambiguity policy, anything inside a protected span — each have either (a) an approved spoken form for the protected span (an owner decision, since URL respelling was previously closed as a forbidden word substitution), or (b) a replacement that keeps them intact without patching the wheel, or (c) an explicit, accepted, documented residual risk. "Unexpanded" and "protected" colons are the cases the first draft did not cover; none may be assumed harmless.
2. **A/B acceptance, three seeds, ≥ 2 Chatterbox voices:** against the current patched baseline on (i) times, (ii) ratios, (iii) ordinary prose colons, (iv) URLs and paths, (v) the full `DIFFICULT_SHORT` passage — the candidate is not worse than the baseline on any item, and the owner explicitly reviews each pacing change at prose colons (the 75 ms pause was chosen from a 0/75/125 ms listening set).
3. **Mechanical:** zero change for text without colons; the wheel's own `punc_norm` is still pinned and its byte-parity guard still passes; no new generate-call splitting unless intended.
4. **Rollback:** the compatibility code is removed in its own commit so it can be restored by revert.
5. **If criteria 1–2 cannot be met,** the shim stays as an explicit, evidenced engine exception (4.6 convergence rule) with a review date — it is retired, not forgotten, either way.

---

## 7. Verification economy

### 7.1 Test runs and counts

* **Three ★ full gates before S5:** B1, A5, S5. Everything else uses the named focused sets.
* **Counts are recorded as two separate numbers** (correction 4): (i) the **pre-existing suite** — baseline at `df0dbc2`: 8,517 passed / 60 skipped — must show **no regression** (every test that passed still passes; none newly skipped or deselected); (ii) the **new tests** added by each checkpoint (A0 characterization, B1 canaries and stale-warning tests, …) must all pass. The headline total is allowed, and expected, to rise; it is never required to equal the old total.
* Focused sets are run *before* the ★ gate so the gate is a confirmation, not a debugging loop.

### 7.2 Audio budget and acceptance rule

* **No regeneration** of the 28-voice evaluation, the sustained recordings or the 11 voice previews (their texts contain no triggers; identity tests prove it). A0 and B1 generate **no audio at all**.
* A4 builds only short snippets (≤ ~25 s) for texts the normalizer changes: about 14 snippets × 4 engines × 2 sides, minus identical pairs — on the order of 100 clips, ~20 minutes of audio in total, **one representative voice per engine** ([D13]): Edge default voice, one Kokoro voice, one Chatterbox voice, Qwen3 Aiden.
* Neutral names, shuffled order, A/B assignment in a manifest kept outside the listening folder; verdicts recorded in `Decisions.md` per cell.
* **Acceptance rule (correction 7).** Each changed cell is labelled in the manifest as **"affects previously approved behaviour: none | pronunciation | pacing"**, with the earlier evidence cited. The owner reviews every labelled cell explicitly and decides. Earlier approvals are *evidence baselines*, not permanent vetoes: the owner has approved the architecture direction (shared normalization), so a cell may move to `expand` when the owner prefers B or hears no difference, the mechanical checks pass and no invariant is violated — including where B differs from audio approved earlier. A preferred A keeps the cell as a **documented exception** (convergence rule 4.6), recorded so it is revisited at its review checkpoint rather than re-proposed blindly.

---

## 8. Decisions

Recorded in section 0.1 (D1–D15, all decided as working decisions on 2026-10-19). Remaining detail that the working decisions deliberately leave to evidence, none of which blocks C0, A0 or B1:

| Item | Resolved by |
|---|---|
| Final spoken-style details (D7): "and" in whole numbers, `oh`/`zero`, `o'clock`, hyphen-free numerals | A4 verdicts |
| Kokoro four-digit exception (D8) | mechanical probe, then A4 |
| URL/path spoken forms (A6 criterion 1) | owner decision when A6 is authorised |
| Edge folder metadata consistency (D10) | separate tested change after B1 |
| Heading timing for Kokoro/Chatterbox (D11) | only if evidence supports a change |

Still outstanding for S5, **not** decided here: the six clone transcripts (`verified.json`, all `approved: false`), then six short and six sustained clone recordings and their listening, and the Q5 rights questions.

---

## 9. Risks and mitigations

* **[R1] Silent regression of approved audio.** Flags OFF until A5; A0 goldens prove zero diff through B1–A4; rollout modes `native`; identity property; per-cell A/B with explicit labelling of any change to approved behaviour (7.2).
* **[R2] Normalizer errs on ambiguity.** Cue-required rules, unchanged-by-default, diagnostics, adversarial corpus, owner A/B per cell.
* **[R3] New pauses from spoken forms.** Charset invariant I5 (no commas/hyphens/colons) and per-engine prosodic-punctuation list in the profile.
* **[R4] Qwen3 seeds/spans shift.** Seeds depend on spoken chunk text, so trigger-free documents keep identical plans; `PIPELINE_REVISION` bump at A5; no existing recording is regenerated.
* **[R5] Kokoro G2P double-processing.** Spoken forms are plain words so misaki's number logic no-ops; the markup path is tested against the pinned misaki.
* **[R6] Repo-wide move breaks hidden depth assumptions.** Nine enumerated sites, A0 goldens, layout canaries, reviewed test update, ★ gate, archive-layout proof, one manual launch.
* **[R7] Test churn masks real failures.** The pre-existing suite must show no regression, and new tests are counted separately (7.1).
* **[R8] Overlay-upgrade confusion (bounded review in 5.3).** Residual risk is an old launcher against a new tree, or two trees side by side. Mitigations: matching launchers ship at the archive root, warning-only detection of stale *source* files, documentation; nothing is deleted automatically and no ignored or untracked file is touched to make the folder disappear.
* **[R9] User glossary mistakes (loops, huge entries).** Literal/word matching only, length limits, load-time overlap rejection, broken file skipped with a visible note; the run uses its frozen snapshot.
* **[R10] Edge server-side normalization unknown.** Edge cells default `native` during rollout; any expansion needs review; no assumption of server behaviour.
* **[R11] Dependency drift.** No new runtime dependency in the recommended design ([D5]); if `num2words` is ever used outside developer comparison it is pinned in `scripts/requirements.txt` with a stated purpose.
* **[R12] Scope creep into sentence splitting or GUI rewrites.** Both excluded; any proposal needs its own plan.
* **[R13] Premature removal of the colon compatibility behaviour.** Removing the patch would let the wheel's blanket replacement corrupt every colon that the normalizer leaves unexpanded or protects (URLs, paths, ambiguous times). Mitigation: A6 criteria; the shim is untouched by B1–A5.
* **[R14] A hash mistaken for a freeze.** A content hash cannot restore a glossary the user has since edited. Mitigation: the run-scoped immutable snapshot (4.7) and the mid-run / pre-retry edit tests; the hash is display-only.
* **[R15] Four normalizers by accretion.** Engine-specific exceptions can multiply. Mitigation: the convergence rule (4.6) — evidence, Decisions entry, review checkpoint, Codex review — and a static test that rule code lives only in the shared package.
* **[R16] Hygiene rules damaging legitimate text.** Zero-width joiners matter in some scripts. Mitigation ([D14], [D15]): v1 hygiene is a narrow, individually validated list applied only to English blocks; no wholesale control-character stripping.

---

## 10. Done when

**For the current authorisation (C0, A0, B1):**
* Section 0 recorded; branch exists; A0 goldens committed, captured from the original paths with no synthesis or network.
* B1 on the feature branch: tree per 5.1 Level 1; **A0 goldens zero-diff**; layout canaries and README maps present; the **pre-existing suite shows no regression against the 8,517 / 60 baseline and all new tests pass** (old and new counts recorded separately); Windows and macOS archive layouts proven in scratch paths; the before/after path map recorded; no deviation unexplained.
* The owner has completed the manual Windows launch, and Codex has independently reviewed the checkpoint, **before A1 begins**.

**For the whole plan:** A1–A5 (and A6 if authorised) complete with their gates; invariants I1–I10 green and mutation-checked; engine P9 guards untouched and green; the run-scoped snapshot proven; the mode table reflects the owner's verdicts with every exception documented; Decisions, Changelog, Briefing and Handoff updated; everything preserved as listed in section 1. S5 then runs once on the final tree. No release, merge or Plan 02 work is implied.

---

## 11. References (retrieved 2026-10-19)

* NVIDIA NeMo-text-processing README (platform statement, Apache-2.0): https://github.com/NVIDIA/NeMo-text-processing
* NeMo inverse text normalization paper (tagger/verbalizer, whitelist priority): https://arxiv.org/pdf/2104.05055
* WeTextProcessing README (Apache-2.0, FST cache, English "no controllable options yet"): https://github.com/wenet-e2e/WeTextProcessing
* pynini on PyPI (wheel inventory by release) and conda-forge feedstock (platform variants): https://pypi.org/project/pynini/ , https://github.com/conda-forge/pynini-feedstock
* PyPI JSON metadata used for versions, licences, wheels and dependencies: `nemo_text_processing`, `WeTextProcessing`, `num2words`, `inflect`, `pysbd`, `gruut`, `quantulum3`, `recognizers-text-*`, `misaki`, `nltk` (https://pypi.org/pypi/<name>/json)
* num2words README (converters, English variants, "thin" test suite): https://github.com/savoirfairelinux/num2words
* inflect README (`number_to_words` options): https://github.com/jaraco/inflect
* misaki README (inline `[word](/phonemes/)` example, Apache-2.0): https://github.com/hexgrad/misaki
* Repository evidence: `md-instructions/Decisions.md` (2026-09-20 … 2026-09-24 audio rulings; 2026-10-19 CP6 entries); `files/tests/test_chatterbox_tuning.py` (P9 guards); `files/plans/ACT-v0.6.7-Plan-01-CP6-Qwen3-Integration-Addendum.md`.

**Limits of this research.** No candidate library was installed or executed (task constraint), so NeMo/WeText English grammar quality on ACT's corpus is unmeasured; the Kokoro four-digit behaviour is from code reading, not audio; `num2words`' exact licence version is unverified beyond the PyPI classifier.

---

## Appendix A — Executive summary (revised 2026-10-19)

**Recommended design.** One ACT-owned, dependency-free, conservative English speech-preparation package (`scripts/tts/speech/`) that parses document structure once, normalizes only when a positive cue exists, records every edit with a mapping to the decoded/extracted source, applies an owner-curated data glossary, and runs against an immutable run-scoped snapshot so Retry Failed cannot see later edits. The end state is one shared rule set for every engine; the per-engine mode table (all `native` during rollout) is temporary scaffolding with a convergence rule. In parallel, lift `scripts/Universal/{launcher.py,shared,tts,mp3_tools}` to `scripts/` as a purely mechanical move that changes no import statements.

**Alternatives considered.** NeMo-text-processing and WeTextProcessing (rejected: pynini has never had Windows/macOS wheels on PyPI; heavy conflicting dependencies); `num2words`/`inflect` as the whole solution (no context; comma/"and"/hyphen output); gruut and Recognizers-Text (dependency weight / unmaintained); spaCy NER (couples to the Kokoro stack); unifying the four sentence splitters now (would change approved audio); an immediate `mp3_tools` split (592 test references, deferred by [D3]).

**Decisions.** D1–D15 are decided (section 0.1). Details left to evidence: spoken-style specifics (A4), the Kokoro four-digit exception (probe, then A4), URL/path spoken forms (A6).

**Authorised work.** C0 (this revision and the branch), A0 (characterization goldens from the original code), B1 (mechanical relocation with canaries, README maps and a warning-only stale-folder notice). Nothing else; A1 begins only after the owner's manual Windows launch and Codex's independent review of B1.

**Open for S5 regardless:** six clone transcripts remain unapproved (`approved: false`); no clone recording exists.
