# mp3/ — the MP3 Tool

The **MP3 Tool** launcher tile: re-encode, tag and add cover art to MP3 files.

| Module | Role |
|---|---|
| `mp3_tool.py` | The panel |
| `mp3_workflow.py` | The workflow model (what the user can do, in what order) |
| `mp3_plan.py` | The frozen run plan |
| `mp3_processing.py` | FFmpeg helpers and the Write-ID3 engine |

What a selected image becomes in an ID3 tag lives with the other artwork code: `../artwork/mp3_artwork.py` (see `../artwork/README.md`).
