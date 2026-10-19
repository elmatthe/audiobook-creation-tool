# mp3_tools/ — the MP3, M4B and Cover Image tools

Five launcher tools live here, plus the artwork code several of them share. The filename prefixes already group the files: `mp3_*`, `m4b_*` and `cover_*`. (Splitting this package into `mp3/`, `m4b/` and `artwork/` is deliberately deferred until after the Qwen3 qualification; see Plan 01B.)

## MP3 Tool — `mp3_tool.py`

| Module | Role |
|---|---|
| `mp3_tool.py` | The panel |
| `mp3_workflow.py` | The workflow model (what the user can do, in what order) |
| `mp3_plan.py` | The frozen run plan |
| `mp3_processing.py` | FFmpeg helpers and the Write-ID3 engine |
| `mp3_artwork.py` | What a selected image becomes in an ID3 tag |

## M4B Converter — `m4b_converter.py`

| Module | Role |
|---|---|
| `m4b_converter.py` | The panel |
| `m4b_plan.py` | One run, decided completely before anything is written |
| `m4b_destinations.py` | Where each imported file's outputs go |
| `m4b_commands.py` | The ffmpeg argument lists (built here, never executed here) |
| `m4b_execution.py` | Running one planned segment, and stopping it |
| `m4b_chapters.py` | Chapter vocabulary |
| `m4b_metadata.py` | What metadata and artwork each conversion mode writes |
| `m4b_probe.py` | Reading one source file once, on a worker thread |
| `m4b_naming.py` | One chapter title → one safe output filename |
| `m4b_winaudio.py` | Windows Media Foundation decoding, for what ffmpeg cannot read |

## M4B Maker — `m4b_maker.py`

| Module | Role |
|---|---|
| `m4b_maker.py` | The panel |
| `m4b_maker_workflow.py` | The workflow model |
| `m4b_maker_plan.py` | The frozen run plan |
| `m4b_maker_batch.py` | Batch execution, success numbering and Retry Failed |
| `m4b_maker_processing.py` | One book: staging to atomic publication |

## M4B Metadata Editor — `m4b_metadata_editor.py`

| Module | Role |
|---|---|
| `m4b_metadata_editor.py` | The panel |
| `m4b_metadata_workflow.py` | The workflow model |
| `m4b_metadata_plan.py` | The frozen action plans |
| `m4b_metadata_batch.py` | Batch execution and Retry Failed |
| `m4b_metadata_processing.py` | One book: private staging to atomic publication |

## Shared by the M4B tools

| Module | Role |
|---|---|
| `m4b_staging.py` | Private staging and atomic publication (Maker and Metadata Editor) |
| `m4b_numbering.py` | Compatibility re-export; the allocator lives in `../shared/numbering.py` |

## Artwork

| Module | Role |
|---|---|
| `cover_resizer.py` | The **Cover Image** tool: batch-resize cover art to a square |
| `m4b_artwork.py` | What a selected image becomes in an MP4 `covr` atom |
| `m4b_artwork_ui.py` | The shared artwork control (Tk) used by the Maker and the Metadata Editor |
| `mp3_artwork.py` | What a selected image becomes in an ID3 tag (MP3 Tool) |
| `../shared/image_capabilities.py` | Which image formats this computer can read |
