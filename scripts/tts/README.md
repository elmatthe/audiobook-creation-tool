# tts/ — the TTS Audiobook tool and its voice engines

Turns PDF and TXT files into narrated MP3s. One queue, four engines, 28 voices.

## The panel and the voice list

| Module | Role |
|---|---|
| `epub2tts_gui.py` | The TTS panel (Tk): the queue, options, run/cancel/retry, and the one dispatch that sends each file to an engine |
| `voice_registry.py` | The single list of every voice (id, label, engine, timing preset) and the order they appear in; identity is engine + id (labels and order are cosmetic, checked on import), plus the fixed table of the six reference recordings |
| `generate_voice_samples.py` | Developer helper: one short sample per registered voice, for listening checks |
| `quality_corpus.py` | Copyright-safe test passages used by the quality work and the A0 characterization baselines |
| `output_names.py` | The one output file name every route uses (v0.7.0 P02B): `<source-stem>-<display label>.mp3`, with the label frozen when the run starts. Stem and label are cleaned separately (forbidden characters and separators become `_`, Unicode NFC, device names guarded); only the stem is shortened, and only when the name, a `-N` collision suffix and an engine's temporary publish name would not fit; an impossible name is refused before synthesis. Clashes are numbered `-1`, `-2` by the shared planner |

## Getting text in

| Module | Role |
|---|---|
| `pdf_extractor.py` | PDF → plain text (PyMuPDF), including dehyphenation and page-gap repair |
| `batch_convert.py` | Edge **folder** route: raw text, 3000-character chunks, one MP3 per source file. Run standalone, it names files the same way (`--label`, defaulting to the speaker's registered label) and never overwrites an earlier file |
| `edge_failures.py` | Edge failure classification shared by both Edge routes: what is retried, the one-line recovery advice, token-free diagnostics |
| `epub2tts_edge/epub2tts_edge.py` | Edge **direct** route: `Title:`/`Author:`/`#` structure, sentence splitting, comma/ellipsis/dash pauses, paragraph and chapter assembly |
| `epub2tts_edge/runner.py` | Runs one direct Edge conversion in a private working folder |
| `audio_tail.py` | The final-tail policy (v0.7.0 Q1) the local engines apply at their one final MP3 encode: no closing pause, only the terminal near-silence is shortened (150 ms kept after the last sound, never a quiet final sound cut); pure numpy |

## The engines

Optional-setup v3 planning and the disposable locked model-acquisition seam live in `optional_setup_authority.py`.
See the [Stage 4B-3A contract](../../files/plans/ACT-v0.7.0-P05B-Stage4B3A-Authority.md).
Production acquisition remains disabled. The explicitly injected disposable engine runner uses
`qwen3_packages.py` (live protected wheel sets) and `qwen3_engine_authority.py` (spent engine mutation authority)
through the existing installer; see the [Stage 4B-3B contract](../../files/plans/ACT-v0.7.0-P05B-Stage4B3B-Offline-Execution.md).
Manual Qwen install/repair keeps its separate index/cache contract outside v3; spaCy installation remains deferred.

`spacy_consumer.py` provides a separate versioned **disposable-only** M3 qualification:
an exact wheel, retained v3 confirmation, pinned target, sealed offline pip and
distinct installed/import-health results. It cannot authorize production `.venv`
mutation; v1 acquisition terms still lack consumer-target/recovery authority.
Portable sox production supply remains pending; local provenance checks grant no redistribution approval.

`qwen3-artifacts.json` version 2 adds one closed `sox_derivative.distribution` record: the exact
commit-pinned raw URL of ACT's published sox derivative (repository, full commit, path, size, SHA-256, tags),
checked against code constants in `qwen3_package_manifest.py`. It is artifact **identity**, not eligibility:
`portable_supply` stays `pending`, `publisher_wheel`/`build_authorized` stay false, the original lock and the
89-wheel effective lock are unchanged, and the production `fresh-machine` Planner still refuses sox. Only the
explicit non-production `published-supply-qualification` purpose emits it as a real `pinned-https` transfer
(revision = the supply commit). It contains no native `sox.exe`; clean-Windows runtime qualification is pending.

| Engine | Modules | Notes |
|---|---|---|
| Edge TTS (network) | `batch_convert.py`, `epub2tts_edge/` | five voices |
| Kokoro (local) | `kokoro_synth.py` | nine voices; Kokoro's own G2P handles numbers |
| Chatterbox Turbo (local, cloned) | `chatterbox_synth.py` | six voices from the bundled reference recordings; 300-character chunks |
| Shared speech preparation | `speech/document.py` | one decode and `Title:`/`Author:`/`#` structure loader for Kokoro, Chatterbox and Qwen3 (A1); standard library only |
| Qwen3-TTS (local, optional, Windows first) | `qwen3_runtime.py`, `qwen3_synth.py`, `qwen3_worker.py`, `qwen3_process.py`, `qwen3_setup.py`, `qwen3_install_ui.py`, `qwen3_clone_setup.py`, `qwen3_clone_setup_ui.py`, `qwen3_models.json`, `data/bundled_clone_transcripts.json` | eight voices in a separate `.venv-qwen3`; only `qwen3_worker.py` runs inside it. The six clones' owner-approved reference transcripts ship in `data/bundled_clone_transcripts.json`, each bound to its recording's SHA-256 (v0.7.0 P03C); `qwen3_runtime.load_bundle` checks the whole file and narration reads nothing else. `qwen3_clone_setup` is the maintainer's local draft-and-approve workflow, a developer tool since v0.7.0 P03D: its "Developer tools → Reference transcripts" entry and every restricted step exist only with `[development] developer_mode = true` in `config.toml` (shipped `false`); a locally approved text reaches narration only after a deliberate per-voice selection bound to the voice id and the recording and text hashes |

## Text-route baselines

The text each route produces (structure, paragraphs, chunks, what each engine is handed, Qwen3 seeds) is pinned by the characterization goldens in `../../files/tests/golden/speech/`, generated by `../../files/dev-tools/speech_characterization.py` and checked by `../../files/tests/test_speech_characterization.py`.
