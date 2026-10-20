# artwork/ — cover art, shared by several tools

The **Cover Image** launcher tile, plus the artwork code the MP3 Tool, the M4B Maker and the M4B Metadata Editor share.

| Module | Role |
|---|---|
| `cover_resizer.py` | The **Cover Image** tool: batch-resize cover art to a square |
| `m4b_artwork.py` | What a selected image becomes in an MP4 `covr` atom |
| `m4b_artwork_ui.py` | The shared artwork control (Tk) used by the Maker and the Metadata Editor |
| `mp3_artwork.py` | What a selected image becomes in an ID3 tag (MP3 Tool) |
| `../shared/image_capabilities.py` | Which image formats this computer can read |
