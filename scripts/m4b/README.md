# m4b/ — the three M4B tools

Three launcher tiles, one sub-package each, plus the M4B code they share (the modules directly in this folder).

## Shared by the M4B tools — this folder

| Module | Role |
|---|---|
| `m4b_probe.py` | Reading one source file once, on a worker thread |
| `m4b_commands.py` | The ffmpeg argument lists (built here, never executed here) |
| `m4b_execution.py` | Running one planned segment, and stopping it |
| `m4b_chapters.py` | Chapter vocabulary |
| `m4b_naming.py` | One chapter title → one safe output filename |
| `m4b_winaudio.py` | Windows Media Foundation decoding, for what ffmpeg cannot read |
| `m4b_staging.py` | Private staging and atomic publication (Maker and Metadata Editor) |
| `m4b_numbering.py` | Compatibility re-export; the allocator lives in `../shared/numbering.py` |

## M4B Converter — `converter/m4b_converter.py`

| Module | Role |
|---|---|
| `converter/m4b_converter.py` | The panel |
| `converter/m4b_plan.py` | One run, decided completely before anything is written |
| `converter/m4b_destinations.py` | Where each imported file's outputs go |
| `converter/m4b_metadata.py` | What metadata and artwork each conversion mode writes |

## M4B Maker — `maker/m4b_maker.py`

| Module | Role |
|---|---|
| `maker/m4b_maker.py` | The panel |
| `maker/m4b_maker_workflow.py` | The workflow model |
| `maker/m4b_maker_plan.py` | The frozen run plan |
| `maker/m4b_maker_batch.py` | Batch execution, success numbering and Retry Failed |
| `maker/m4b_maker_processing.py` | One book: staging to atomic publication |

## M4B Metadata Editor — `metadata/m4b_metadata_editor.py`

| Module | Role |
|---|---|
| `metadata/m4b_metadata_editor.py` | The panel |
| `metadata/m4b_metadata_workflow.py` | The workflow model |
| `metadata/m4b_metadata_plan.py` | The frozen action plans |
| `metadata/m4b_metadata_batch.py` | Batch execution and Retry Failed |
| `metadata/m4b_metadata_processing.py` | One book: private staging to atomic publication |

Cover art for the Maker and the Metadata Editor comes from `../artwork/m4b_artwork.py` and `../artwork/m4b_artwork_ui.py` (see `../artwork/README.md`).
