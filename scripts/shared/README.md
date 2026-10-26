# shared/ — code every tool uses

| Group | Modules |
|---|---|
| **First-run setup, launch and release** | `bootstrap.py` (setup, repair, launch), `venv_layout.py` (environments held inside `.venv`: what replacing or clearing it must keep; read-only), `engine_lease.py` (the locks a held voice engine's users hold, taken together before the environment is changed), `close_terminal.py` (macOS), `espeak_data.py`, `logging_setup.py`, `version.py`, `release.py` (developer packaging, not part of the running app) |
| **Paths, configuration, settings** | `paths.py` (every project-relative path), `config.py` (the typed effective configuration), `settings.py` (user state saved as settings.json under files/runtime-data), `output_paths.py` (output folders and run reservations), `preferences_ui.py` (Preferences & Data) |
| **FFmpeg and subprocesses** | `ffmpeg_health.py` (prove one working ffmpeg + ffprobe pair), `ffmpeg_portable.py` (pinned portable build, Windows), `ffmpeg_utils.py`, `subprocess_utils.py` |
| **Jobs, importing and the multi-book workspace** | `job_control.py`, `job_ui.py`, `importing.py`, `import_coordination.py`, `book_workspace.py`, `book_workspace_ui.py`, `cancellation.py` |
| **Look and feel** | `appearance.py` (Light/Dark), `ui_theme.py` |
| **Data helpers** | `metadata.py` (M4B/MP4 metadata), `numbering.py` (success numbering), `image_capabilities.py` |
| **Downloaded-data cleanup** | `maintenance.py` (the catalog), `cleanup_state.py`, `cleanup_worker.py` (the only code that deletes an asset) |
| **Artifact acquisition foundation** | `artifact_store.py` (reviewed identities and contained local objects), `artifact_transfer.py` (strict HTTPS and persistent v3 transfer accounting). Unused by the production worker/installer; see [Stage 4B-2 contract](../../files/plans/ACT-v0.7.0-P05B-Stage4B2-Artifact-Foundation.md). |

Every path is derived from `paths.py`, except the few modules that must work before the virtual environment exists (`bootstrap.py`, `ffmpeg_health.py`, `ffmpeg_portable.py`); those derive the repository root from their own location and are kept in step with `paths.py` by the layout canary test (files/tests/test_layout_canary.py).
