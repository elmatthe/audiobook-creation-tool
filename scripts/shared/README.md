# shared/ — code every tool uses

| Group | Modules |
|---|---|
| **First-run setup, launch and release** | `bootstrap.py` (setup, repair, launch), `venv_layout.py` (environments held inside `.venv`: what replacing or clearing it must keep; read-only), `engine_lease.py` (the locks a held voice engine's users hold, taken together before the environment is changed), `base_packages.py` (the app environment's hash lock, the verified package store in `files/runtime-data/python-packages` and the one pip policy: cache in the app's folder, no pip configuration; standard library only), `nltk_store.py` (the Edge voices' English sentence data, pinned and verified in `files/runtime-data/nltk_data`, fetched only with consent; standard library only), `close_terminal.py` (macOS), `espeak_data.py`, `logging_setup.py`, `version.py`, `release.py` (developer packaging, not part of the running app) |
| **Paths, configuration, settings** | `paths.py` (every project-relative path), `config.py` (the typed effective configuration), `settings.py` (user state saved as settings.json under files/runtime-data), `output_paths.py` (output folders and run reservations), `preferences_ui.py` (Preferences & Data) |
| **FFmpeg and subprocesses** | `ffmpeg_health.py` (prove one working ffmpeg + ffprobe pair), `ffmpeg_portable.py` (pinned portable build, Windows), `ffmpeg_utils.py`, `subprocess_utils.py` |
| **Jobs, importing and the multi-book workspace** | `job_control.py`, `job_ui.py`, `importing.py`, `import_coordination.py`, `book_workspace.py`, `book_workspace_ui.py`, `cancellation.py` |
| **Look and feel** | `appearance.py` (Light/Dark), `ui_theme.py` |
| **Data helpers** | `metadata.py` (M4B/MP4 metadata), `numbering.py` (success numbering), `image_capabilities.py` |
| **Downloaded-data cleanup** | `maintenance.py` (the catalog), `cleanup_state.py`, `cleanup_worker.py` (the only code that deletes an asset) |
| **Optional voice setup (v0.7.0 release installer)** | `optional_setup_protocol.py` (the four components, consent and the contained setup-worker bridge; standard library only), `optional_setup_client.py` (plan / disclosure / consent / install for the wizard and Install & Continue), `optional_setup_panel.py` (the Tk review → install → result panel), `spacy_store.py` (the approved spaCy English wheel and the verified copy kept beside the models, so a rebuilt `.venv` reinstalls it offline; standard library only) |
| **Optional setup v3 qualification harness** (in the tree, not used by production) | `optional_setup_v3.py`, `optional_setup_wire_v3.py`, `optional_setup_exchange_v3.py`, `optional_setup_resource_budget.py`, `optional_setup_supervisor_v3.py`, `optional_setup_planning_bridge_v3.py`, `optional_setup_readonly_context_v3.py`, `optional_setup_display_controller_v3.py`, `optional_setup_tk_harness_v3.py` |
| **Artifact acquisition foundation** | `artifact_store.py` (reviewed identities and contained local objects), `artifact_transfer.py` (strict HTTPS and persistent v3 transfer accounting; read-only history disclosure). Used only by the disposable v3 model-acquisition seam, not the production worker; see [Stage 4B-2 contract](../../files/plans/ACT-v0.7.0-P05B-Stage4B2-Artifact-Foundation.md) and [Stage 4B-3A contract](../../files/plans/ACT-v0.7.0-P05B-Stage4B3A-Authority.md). |

The artifact foundation also supports the explicitly injected protected offline Qwen execution seam;
see the [Stage 4B-3B contract](../../files/plans/ACT-v0.7.0-P05B-Stage4B3B-Offline-Execution.md).
Since v0.7.0 production acquisition runs through `optional_setup_client.py` and the v2 worker instead (Decisions 2026-10-30).

Every path is derived from `paths.py`, except the few modules that must work before the virtual environment exists (`bootstrap.py`, `ffmpeg_health.py`, `ffmpeg_portable.py`); those derive the repository root from their own location and are kept in step with `paths.py` by the layout canary test (files/tests/test_layout_canary.py).
