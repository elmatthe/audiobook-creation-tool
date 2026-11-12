# Six-tool consistency matrix

How the six tools behave where a person would expect them to behave alike. Written at the close of v0.7.2 Phase 6 from the
source as it stands and the inventory in `coverage.json`; each cell names the feature whose verification proves it. It holds no
test ids: look a feature up in `coverage.json` to see how it is verified. **Differs** marks a place where the tools do not
behave alike today; none of those differences was changed in Phase 6, and each is listed at the end as a proposal for the owner.

Columns: **TTS** TTS Audiobook · **MP3** MP3 Tool · **Conv** M4B Converter · **Maker** M4B Maker · **Editor** M4B Metadata
Editor · **Cover** Cover Image.

## Importing

| Behaviour | TTS | MP3 | Conv | Maker | Editor | Cover |
|---|---|---|---|---|---|---|
| What an import makes | files in one queue (`ACT.TTS.IMPORT`) | one Book per folder (`ACT.MP3.IMPORT-FOLDER`) | files in one list (`ACT.CONVERTER.IMPORT`) | one Book per folder (`ACT.MAKER.IMPORT-FOLDER`) | one Book per file (`ACT.METADATA.IMPORT`) | files in one list (`ACT.COVER.IMPORT`) |
| Folder import over Books that hold work | n/a: adds to the queue | asks "Replace the current Books?"; No keeps them | n/a: adds | asks; No keeps them | asks; No keeps them | n/a: adds |
| Broad folder and large result asked about first | yes (`ACT.SHARED.IMPORTING`) | yes, in its own words | yes | yes, in its own words | yes (`ACT.METADATA.IMPORT-SCAN`) | yes |
| Cancel Import during a folder scan leaves things as they were | yes (`ACT.SHARED.IMPORTING.CANCEL`) | yes | yes | yes | yes | yes |
| A file added twice | list option (`ACT.SHARED.FILE-LIST`) | skipped in its Book, counted in the log (`ACT.MP3.ADD-FILES`) | list option | skipped in its Book, counted (`ACT.MAKER.ADD-FILES`) | skipped in the workspace, counted | refused by default (`ACT.COVER.IMPORT.DUPLICATES`) |
| Last input folder remembered | **differs**: none | yes | yes | yes (and the cover folder) | yes (and the cover folder, `ACT.METADATA.REMEMBERED-FOLDERS`) | yes (`ACT.COVER.PERSISTENCE`) |
| Closing during a folder scan | shared coordinator (`ACT.SHARED.CLOSE-DURING-WORK`; driven natively in Cover Image) | same | same | same | same | native journey |

## Starting a run

| Behaviour | TTS | MP3 | Conv | Maker | Editor | Cover |
|---|---|---|---|---|---|---|
| A typed value outside its range | refused at Start: Kokoro speed (`ACT.TTS.ENGINE.KOKORO`) | refused: Start #, Time, naming the Book (`ACT.MP3.INVALID-VALUES`) | **differs**: corrected silently: quality to 0–9 or 2, Start # to 1 or more (`ACT.CONVERTER.QUALITY`, `ACT.CONVERTER.NUMBERING`) | refused: Silence, naming the Book (`ACT.MAKER.SILENCE`) | refused: Start Part (`ACT.METADATA.AUTO-NUMBER`) | refused: size 256–4096 (`ACT.COVER.SIZE`) |
| FFmpeg not proved | **differs**: no up-front check | warned on opening; each Book fails, nothing published (`ACT.MP3.FFMPEG-REQUIRED`) | refused at Convert, nothing starts (`ACT.CONVERTER.FFMPEG-READY`) | each Book fails at Build | **differs**: no up-front check | n/a: no FFmpeg |
| Run folder | one numbered folder per run, after validation (`ACT.TTS.OUTPUT-FOLDER`) | same (`ACT.MP3.OUTPUT-RUN`) | same (`ACT.CONVERTER.OUTPUT-FOLDER`) | same, or a custom folder (`ACT.MAKER.RUN-FOLDER`) | same (`ACT.METADATA.RUN-START`) | same, or beside the sources (`ACT.COVER.STANDARD-OUTPUT`) |
| A run folder that cannot be made | error, nothing starts | error, nothing starts | error, nothing starts | error, nothing starts | error, nothing starts | error, nothing starts |
| A plan refused after the folder was reserved | the empty folder is released | released | released | released | released | released (left behind until v0.7.2 Phase 6, ACT72-061) |
| Open Output Folder | tool folder, then the run (`ACT.TTS.OUTPUT-FOLDER`) | **differs**: none | tool folder, then the run | **differs**: none | tool folder, then the run (`ACT.METADATA.OPEN-OUTPUT`) | **differs**: none |
| Options frozen at Start and locked while running | yes (`ACT.TTS.LOCK-DURING-RUN`) | yes | yes | yes (`ACT.MAKER.RUN-LOCK`) | yes (`ACT.METADATA.RUN-LOCKING`) | yes (`ACT.COVER.RUN`) |

## During and after a run

| Behaviour | TTS | MP3 | Conv | Maker | Editor | Cover |
|---|---|---|---|---|---|---|
| Pause, Resume, Cancel, Retry Failed | shared controller (`ACT.SHARED.JOB-CONTROL`) | same | same | same | same | same |
| Cancel and a running FFmpeg step | stopped at once (`ACT.TTS.CANCEL.FFMPEG`) | stopped at once (`ACT.MP3.CANCEL`) | stopped at once (`ACT.CONVERTER.CANCEL`) | stopped at once (`ACT.MAKER.CANCEL`) | a running remux stopped at once (`ACT.METADATA.CANCEL`) | n/a: the current image finishes, then the run stops (`ACT.COVER.CANCEL`) |
| What a Cancel stopped part-way is called | counted as stopped in the closing line | the Book reads Cancelled, counted as stopped by Cancel | its book is taken back | Cancelled, counted | Cancelled, counted | n/a: nothing is stopped part-way; images not reached are not attempted |
| What Retry Failed can reach is kept, and nothing else | owned work area (`ACT.TTS.CLEANUP`) | yes (`ACT.MP3.STAGING-PUBLISH`) | failed books leave no empty folders | yes (`ACT.MAKER.STAGING`) | yes (`ACT.SHARED.M4B-STAGING`) | temporary sibling only (`ACT.SHARED.OUTPUT-PATHS.REPLACE`) |
| Summary: the run's lines, its end once, then the closing line | yes (`ACT.SHARED.LOG-VIEW`) | yes | yes (`ACT.CONVERTER.ACTIVITY`) | yes | yes | yes (`ACT.COVER.RUN-REPORT`) |
| Each attempt under its own divider | yes (`ACT.TTS.ACTIVITY-LOG`) | yes (`ACT.MP3.ACTIVITY-LOG`) | **differs**: an "Output folder" line instead | yes (`ACT.MAKER.ACTIVITY-LOG`) | yes (`ACT.METADATA.ACTIVITY-LOG`) | **differs**: an "Output folder" line instead |
| Clear Log forgets the view only | yes | yes | yes | yes | yes | yes |
| Closing the window during a run | exit 0, nothing orphaned (`ACT.SHARED.CLOSE-DURING-WORK`) | same | same | same | same | same |

## Differences found, left for the owner

None of these is a defect against a written contract; each is a place where one tool does what a person would not predict from
the others. Changing any of them changes what a person sees, so each waits for an owner decision.

1. **Typed values in the Converter are corrected, not refused.** Every other tool refuses an out-of-range value at Start and
   names it; the Converter turns a typed quality of 15 into 9 and a Start # of 0 into 1 without a word. Proposal: refuse at
   Convert like the others ("MP3 quality must be a whole number from 0 to 9"), or say in the Summary what was used.
2. **FFmpeg readiness is checked three ways.** The Converter refuses before anything starts, the MP3 Tool warns on opening and
   fails each Book, the Maker fails each Book, and TTS and the Metadata Editor have no up-front check. Proposal: one shared
   check at Start, refusing before a run folder is reserved, in every FFmpeg-using tool.
3. **Open Output Folder exists in three tools of six.** TTS, the Converter and the Metadata Editor have it; the MP3 Tool, the
   Maker and Cover Image do not, though each shows its output path. Proposal: add it to the other three with the same rule
   (tool folder before a run, the run after).
4. **Per-attempt dividers.** The Converter and Cover Image start each run with an "Output folder" line rather than the divider
   the other four rule. Proposal: the shared divider in all six.
5. **The TTS tool remembers no input folder.** The other five reopen their file dialogs where the last choice was made.
