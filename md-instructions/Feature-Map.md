# Audiobook Creation Tool — Feature Map

> The permanent entrypoint to what the application does (one of the five permanent documents since v0.8.2 Phase 0A).
> It is an index only. The detailed maps stay where the verification gate reads them, `files/dev-work/feature-map/`,
> and nothing here repeats them.

**Authority.** `files/dev-work/verification-gate/coverage.json` is the only machine-readable record of feature ids,
their source and how each is verified. The detailed maps hold prose and name features by those ids; they hold no test
ids or mapping tables. To see how a feature is verified, look its id up in `coverage.json`. Which verification an agent
may run is `files/dev-work/verification-gate/GATE.md`'s policy, not this document's.

## Detailed maps

| Map | Covers |
|---|---|
| `files/dev-work/feature-map/README.md` | The maps' own index, how the inventory is kept honest, and the verification gate's own features (`ACT.GATE.*`) |
| `files/dev-work/feature-map/tts-audiobook.md` | TTS Audiobook: sources, voices and engines, Edge narration, local engines and their setup, publication, Cancel, Pause, Retry |
| `files/dev-work/feature-map/mp3-tool.md` | MP3 Tool: Books, tracks, metadata, Write ID3 Tags, Combine, artwork, numbering |
| `files/dev-work/feature-map/m4b-converter.md` | M4B Converter: whole book or by chapter, metadata modes, quality, decoding routes, naming and collisions |
| `files/dev-work/feature-map/m4b-maker.md` | M4B Maker: Books, ordering, chapters, metadata, artwork, Build M4B(s), naming and destinations |
| `files/dev-work/feature-map/m4b-metadata-editor.md` | M4B Metadata Editor: Save Tags, Clear All Tags, Remove Series Numbering, chapter titles, artwork |
| `files/dev-work/feature-map/cover-image.md` | Cover Image: browsing, size, crop or letterbox, numbered copies or replacement, corrupt inputs |
| `files/dev-work/feature-map/consistency-matrix.md` | The six tools side by side where a person expects them to behave alike |
| `files/dev-work/feature-map/shared-workflows.md` | Launcher, shared job/log/import/Book/output machinery, settings, appearance, Preferences, installation, launch, repair and optional assets |

## Keeping it current

A new or renamed detailed map is added to the table above in the same commit
(`files/tests/test_repository_contract.py` holds this index to the folder's real contents). Feature changes are
recorded in the detailed map and in `coverage.json`, as `files/dev-work/feature-map/README.md` describes; this
document changes only when the set of maps changes.
