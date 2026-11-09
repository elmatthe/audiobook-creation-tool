# Cover Image

Part of the ACT feature map (`README.md`). Written in v0.7.2 Phase 4 from the source, the live widget trees of a running instance, the registered journeys and the existing tests. Each feature is named by its stable id; how it is verified (exact tests, journeys, qualification, owner checks and planned gaps) lives only in `files/dev-work/verification-gate/coverage.json`. A "known gap" below names an open issue in that file's ledger. Nothing here claims a feature passed: a run's `coverage-report.md` says what it satisfied.

## Cover Image

Cover Image turns a batch of pictures into square audiobook covers. The user imports images (files or folders), picks a target size and either letterboxing (keep the whole picture on a black square) or center crop, chooses where the results go, and presses **Resize Covers**. By default each run writes into its own numbered run folder and never touches the sources; the user can instead save numbered copies beside the sources or, behind a per-run confirmation, replace the originals. The panel is built from the shared importing, job-control and log foundations, with a Cover-only three-view source browser.

Source: `scripts/artwork/cover_resizer.py` (the panel `CoverResizerUI`, the browser `CoverBrowser`, the replacement dialog, the image logic `resize_for_audiobook`, and the standalone `main`), with `scripts/artwork/__init__.py` as the package marker. HEIC/HEIF availability comes from `scripts/shared/image_capabilities.py`; run folders, numbered names and safe replacement come from `scripts/shared/output_paths.py`.

### Open the Cover Image panel and its first-open defaults
`ACT.COVER.OPEN`

- **Purpose:** the launcher's Cover Image entry builds the panel into its content area. A standalone `main()` opens the same panel in its own 900x640 window for developers; users go through the launcher.
- **How to reach it:** click Cover Image in the launcher.
- **First-open state:** Keep full image ticked, target size 1024, Save beside source images off with Create numbered copies preselected (both choices disabled), browser on Details, every offered image type ticked, Include subfolders on. The Output field names the tool's output folder, never a run number.
- **Inputs/outputs:** opening the panel creates no folder and writes nothing.
- **Failure:** if HEIC support is missing or broken, the panel still opens with JPEG and PNG only.
- **Persistence:** resize options are not restored from earlier sessions (see "What Cover Image remembers").

### Import cover images
`ACT.COVER.IMPORT`

- **Purpose:** bring images into the list. The shared imported-file manager is the only record of what is imported and in what order.
- **How to reach it:** in **1. Sources**: Add Files… (dialog "Select cover images"), Add Folder… (dialog "Select a folder of cover images"), Move Up, Move Down, Remove, Clear All; the type boxes PNG image, JPEG image and HEIC / HEIF image; Include subfolders, Include hidden folders, Allow duplicate files; Cancel Import while a folder scan runs.
- **States:** the HEIC / HEIF box appears only on machines that can decode HEIC. The shared importer's own list box is kept but hidden, because the browser is the visible list. During a resize the list and import options are locked, but Cancel Import stays usable for a scan already running.
- **Inputs/outputs:** .jpg, .jpeg, .png, and .heic/.heif when decodable. Add Files keeps the dialog's order. Add Folder scans sub-folders and imports only ticked types; other files are reported as unsupported, folder links are reported and not followed.
- **Confirmations:** a whole drive or the home folder asks "Scan a very broad folder?" before any scan starts; more than the large-result threshold (1000 by default) asks "Add a large number of images?" before anything is added.
- **Failure/cancel:** a failed, cancelled or declined scan leaves the previous list unchanged; closing the panel mid-scan adds nothing. Cancel Import stops only the scan, never a running resize.
- **Persistence:** the last folder used is remembered; the list is not.

### Duplicate images
`ACT.COVER.IMPORT.DUPLICATES`

- **Purpose:** let a user process the same file twice on purpose while stopping accidental double imports.
- **How to reach it:** the Allow duplicate files box in 1. Sources.
- **Behaviour:** off by default, so adding a file already in the list adds nothing and reports it as a duplicate. With it on, the file becomes a second occurrence that is selected, removed, processed and retried on its own. In a standard run the two get separate names (cover.jpg, cover-1.jpg); as numbered copies they get separate numbers.
- **Persistence:** the box is not saved between sessions.

### HEIC / HEIF support
`ACT.COVER.HEIC`

- **Purpose:** resize phone photos in HEIC/HEIF when the optional support is installed, without promising a format the machine cannot handle.
- **States:** reading and writing are checked separately. A machine that can read HEIC offers it for import (type box and dialog filter); a machine that can also write it produces HEIC output.
- **Inputs/outputs:** a HEIC source is planned and written as HEIC at quality 95. It is never silently written as JPEG.
- **Failure/retry:** if the machine can read but not write HEIC, that image fails with a clear message, nothing is written under any name, and the image is offered for Retry Failed.
- **Intentional difference:** other unknown formats fall back to .jpg; HEIC deliberately does not.

### Source browser views
`ACT.COVER.BROWSER`

- **Purpose:** three views of the one imported list.
- **How to reach it:** the Details / List / Medium Thumbnails choices at the top of 1. Sources.
- **Behaviour:** Details (default) shows Filename, Dimensions, Format, File size and Folder. List shows full paths. Medium Thumbnails shows 128 px tiles with file names. Switching view never changes the order, the selection or the list, and every view follows imports, Remove, Clear All and moves.
- **States:** only the shown view is a Tab stop. During a run the row views look disabled and selection is locked, but the view can still be switched.
- **Persistence:** the view is not saved; every panel opens on Details.

### Browser selection and keyboard
`ACT.COVER.BROWSER.SELECTION`

- **Purpose:** choose which images Move Up, Move Down and Remove act on.
- **Behaviour:** click, Ctrl/Command-click and Shift-click work the same in all three views, and ranges follow list order. Arrow keys, Home, End, Shift+arrows and Ctrl+A move and select without wrapping. Delete/BackSpace remove the selection and Alt+Up/Alt+Down move it, using the same actions as the buttons. The browser and the hidden shared list always show the same selection.
- **States:** selection is refused during a run.

### Browser scrolling and previews
`ACT.COVER.BROWSER.PREVIEWS`

- **Purpose:** keep a large import responsive.
- **Behaviour:** details and thumbnails are read only for what is on screen, at most 60 items per request, on a background thread. Up to 96 decoded thumbnails are kept, least recently used dropped first. Scrolling by scrollbar, keyboard or mouse wheel fills in newly visible rows and tiles; the wheel works over the thumbnail area without taking scrolling from other panels. Results that arrive after an item was removed, after the list changed, or after close are ignored. Closing waits a bounded time for decoder threads.
- **States:** rows show … until their details arrive; tiles show a grey placeholder until decoded.
- **Inputs/outputs:** reads images only, never writes them; nothing is cached on disk.

### Target size
`ACT.COVER.SIZE`

- **Purpose:** the side length of the square cover.
- **How to reach it:** 2. Resize Options, "Target size (square, px)" (spin range 256 to 4096 in steps of 64, default 1024; the value can be typed).
- **Behaviour:** every output is exactly size x size for the size in effect when Resize Covers was pressed; changing it during a run has no effect on that run.
- **Failure:** a non-numeric value shows "Bad size: Target size must be a number."; a negative value shows "Bad size: Target size must be positive." Nothing starts and no run folder is reserved.
- **Persistence:** not saved; each panel starts at 1024.
- **Known gap:** 0 silently becomes 1024, and typed values outside 256-4096 (very small or very large) are accepted with no upper bound. Only the negative case has a test. New finding, Phase 6.

### Keep full image (letterbox)
`ACT.COVER.LETTERBOX`

- **Purpose:** a square cover from a non-square picture without losing any of it.
- **How to reach it:** 2. Resize Options, "Keep full image (letterbox into square, no cropping)", ticked by default.
- **Behaviour:** the long side is scaled to the target size and the whole image is centred on a black square. Images are converted to RGB, so transparency is not kept.
- **Persistence:** not saved.

### Center crop
`ACT.COVER.CROP`

- **Purpose:** fill the whole square with picture.
- **How to reach it:** untick Keep full image.
- **Behaviour:** the short side is scaled to the target size and the centre square is kept; what lies outside it is left out of the output (the source is unchanged).
- **Persistence:** not saved.

### Output format
`ACT.COVER.OUTPUT-FORMAT`

- **Purpose:** keep each cover in a common format without asking.
- **Behaviour:** JPG/JPEG sources are written as JPEG (quality 95), PNG as PNG, HEIC/HEIF as HEIC/HEIF; anything else that can be read is written as .jpg, and its destination is planned under that .jpg name. There is no format or quality control.

### Upright phone photos
`ACT.COVER.ORIENTATION`

- **Purpose:** a photo stored sideways with an orientation tag comes out as viewers show it.
- **Behaviour:** the tag is applied before resizing and the output carries no rotating tag. Thumbnails are upright and Details shows the dimensions as the photo is seen. HEIC photos are not turned twice.

### Save beside source images (mode switch)
`ACT.COVER.SOURCE-SIDE-MODE`

- **Purpose:** switch between the standard run folder and writing next to each source.
- **How to reach it:** 2. Resize Options, "Save beside source images", then "Create numbered copies" or "Replace original files".
- **States:** off on every fresh panel; the two choices are disabled until it is ticked; unticking resets the choice to numbered copies so a hidden Replace can never stay active. All three are disabled during a run.
- **Persistence:** never saved or restored.

### Standard output (numbered run folder)
`ACT.COVER.STANDARD-OUTPUT`

- **Purpose:** the default, non-destructive route.
- **How to reach it:** Resize Covers with Save beside source images off. The read-only Output field in 3. Output & Run shows where results go; the base folder is changed in Preferences & Data.
- **Behaviour:** after validation, one new folder `<output base>/Cover-Image-Outputs/Cover-Image-N` is reserved and everything is written inside it. Individually added files land flat; one imported folder keeps its sub-folders; several imported folders each get their own container. Name clashes are resolved before the run starts (cover.jpg, cover-1.jpg). Once the run starts the Output field shows the run folder.
- **Failure/retry:** if the run folder cannot be reserved, an "Output folder" error is shown and nothing starts. Retried images go to the paths planned for them originally and never overwrite an earlier success.
- **Known gap:** no test drives the "Output folder" error path (Phase 6).

### Create numbered copies beside the source
`ACT.COVER.NUMBERED-COPIES`

- **Purpose:** put the resized cover next to the book files without touching the original.
- **How to reach it:** tick Save beside source images, keep Create numbered copies, press Resize Covers.
- **Behaviour:** each output is `name-1.ext` beside its source, never the source's own name; existing numbers are skipped (cover-1.jpg exists, so cover-2.jpg); numbering is per folder. No run folder is reserved. The log says "Writing beside each source image."
- **Retry:** retries plan new numbers beside the same sources and keep this mode.

### Replace original files
`ACT.COVER.REPLACE`

- **Purpose:** overwrite originals with their resized versions.
- **How to reach it:** tick Save beside source images, choose Replace original files, press Resize Covers, then confirm.
- **Before anything happens:** every source is checked. A missing file, a folder, a link, or a format that would be written as .jpg (anything but JPG/JPEG/PNG/HEIC/HEIF) stops the whole run with "Cannot replace originals", and no confirmation is shown.
- **How it writes:** each result goes to a temporary file beside the original, is read back and checked to be size x size, and only then replaces the original in one step. A failure before that step leaves the original byte-for-byte unchanged and removes only its own temporary file.
- **Cancel/failure:** originals already replaced stay replaced after a later failure or Cancel; the log ends with "N of M original(s) replaced; any not reached are unchanged." A retry checks the sources again and asks for confirmation again.
- **Persistence:** never saved; a rebuilt panel is back in standard mode.

### Replacement confirmation
`ACT.COVER.REPLACE.CONFIRM`

- **Purpose:** the last explicit check before originals are overwritten.
- **Behaviour:** titled "Confirm replacement of original images", it states the exact count, that the change is permanent and cannot be undone, that each replacement goes through a temporary file, and that images already replaced stay replaced after a failure or cancel. The destructive button reads "Replace N Original Files" ("Replace 1 Original File"). Cancel is the default and has focus, so Enter cancels; Escape and closing the window also cancel. It is built new for every run and every retry, and no answer is remembered.
- **Declining:** creates no run, no temporary file and no output; the Detailed log says "Replacement cancelled. Nothing was changed."
- **Known gap:** no native journey opens this modal dialog in the running app and answers it with real input; focus on Cancel is checked only from the source (Phase 6).

### Sources are never changed in the copy modes
`ACT.COVER.SOURCE-PROTECTION`

- **Purpose:** only the confirmed Replace route may change an original.
- **Behaviour:** in standard and numbered-copy modes no destination is ever an imported file, and every source is unchanged after the run, including a file imported twice. Removing or clearing rows never deletes files, and showing details or thumbnails never writes to an image.

### Resize Covers (start a run)
`ACT.COVER.RUN`

- **Purpose:** process every imported image, in list order, on a background worker.
- **How to reach it:** 3. Output & Run, Resize Covers (the panel's default button).
- **Behaviour:** with an empty list it shows "No files: Please import images first." and starts nothing. The list, size, crop/letterbox choice and mode are fixed when the run starts; later edits or imports cannot change it. Only one run at a time. During the run the list, import options and resize options are disabled; Cancel Import and the view switch stay usable; everything unlocks when the run ends.
- **States:** running, pause requested, paused, cancel requested, then succeeded, completed with failures, or cancelled.

### Progress, estimate and run report
`ACT.COVER.RUN-REPORT`

- **Purpose:** show how far the batch is and what happened to each image.
- **How to reach it:** the progress, stage and estimate under Resize Covers; the Activity area's Summary and Detailed tabs; Clear Log.
- **Behaviour:** progress counts only images actually finished, also after Cancel. The estimate says calculating until three images have succeeded, and again while paused or finished. Summary names each failed file ("<name> could not be resized.") without tracebacks or commands; Detailed has the per-image transcript and error text. The closing "All done." or "Cancelled." appears in both panes. Clear Log empties the visible text only.
- **Known gap:** the Summary shows "All done." above "Running." and "Finished." twice (ACT72-018, Phase 6). Log following in the panes is shared (ACT.SHARED.LOG-VIEW).

### Pause and Resume
`ACT.COVER.PAUSE`

- **Purpose:** halt a long batch without losing finished work.
- **How to reach it:** Pause and Resume in the shared run controls.
- **Behaviour:** Pause lets the current image finish and starts no new one; a paused run holds no half-written output. Resume continues with the next image without redoing finished ones. Cancel during a pause ends the run.

### Cancel
`ACT.COVER.CANCEL`

- **Purpose:** stop a batch early with an honest record.
- **How to reach it:** Cancel in the shared run controls (running or paused).
- **Behaviour:** the log says "Cancelling… will stop after the current image."; the current image always finishes (one image is the longest wait). Images not reached are reported as not attempted, not as failures; finished outputs and completed replacements stay. The run is reported cancelled only after the worker has stopped. Cancel never touches an import scan, and Cancel Import never touches the run.
- **Difference:** resizing happens inside the app, so there is no external process to stop.

### Retry Failed
`ACT.COVER.RETRY`

- **Purpose:** try again only what failed, exactly as the first attempt would have.
- **Behaviour:** offered only after a run with failures. Re-runs only the failed images with the original size, crop/letterbox choice and mode; standard-mode retries use the originally planned paths and never overwrite an earlier success; numbered-copy retries plan new numbers; replace retries check and confirm again.
- **Persistence:** the retryable result lives only in the open panel.

### Corrupt or unreadable images
`ACT.COVER.CORRUPT`

- **Purpose:** one bad file must not spoil a batch.
- **Behaviour:** a truncated or non-image file keeps its row, shows Unavailable for dimensions and format, shows a placeholder tile, and is never modified. In a run it fails alone, is named in the log, produces no output, and the other images are still written; the run ends as completed with failures.
- **Retry:** every failure is marked retryable, so Retry Failed is offered even though a corrupt file will fail again.

### Closing during work
`ACT.COVER.CLOSE`

- **Purpose:** leaving mid-batch must not hang, crash or leave threads running.
- **Behaviour:** closing asks a running or paused resize to stop, waits up to 5 seconds for it, then shuts down the import scan, browser decoders, run controls and the panel's scheduler; late events are ignored. The panel finishes its own cleanup on the main thread.
- After the window closes, its Tk variables, images and fonts are finished on the main thread, so a collection that lands on a worker makes no Tk call; the forced-shutdown case exits at once (it took about 17 to 18 seconds before; ACT72-017, fixed in v0.7.2 Phase 6).

### Panel layout
`ACT.COVER.LAYOUT`

- **Purpose:** keep 1. Sources, 2. Resize Options, 3. Output & Run and Activity usable at every supported size.
- **Behaviour:** at 920x600, 1024x720 and larger every required control is on screen with no whole-panel scrollbar; only the browser and the log scroll. The arrangement is chosen from measured sizes; Activity stays on the right unless the panel is too narrow, and the browser keeps at least one thumbnail row whenever Sources sits on top.
- **Owner checks:** visual baselines, and display scaling other than 100%.

### Light and Dark appearance
`ACT.COVER.APPEARANCE`

- **Purpose:** follow the app's appearance with no light patches in Dark.
- **Behaviour:** switching recolours the panel in place, including the thumbnail area and the log, without rebuilding widgets or losing imports, selection, view, settings or log text; a switch during a run leaves the run alone. The replacement dialog takes the current appearance when it opens.

### What Cover Image remembers
`ACT.COVER.PERSISTENCE`

- **Saved:** the folder last used by Add Files (the first chosen file's folder) or Add Folder, under `cover_resizer.input_dir`; the next dialog opens there, or at the home folder if it no longer exists.
- **Not saved:** target size, letterbox, Save beside source images, Replace original files, browser view, the imported list, run results. A rebuilt panel is always in standard mode.
- **Known gap:** no test shows the folder being saved, reused, or falling back to home (Phase 6).

### Intentional differences from other tools

- Cover Image is the only tool that can write beside its sources or replace them, and the only destructive route in the app; it needs three separate user actions plus a per-run confirmation.
- Its source list is shown through its own browser with Details, List and Medium Thumbnails views instead of the shared list widget (which is kept hidden but in step).
- Pause and Cancel take effect between images; the work is done inside the app, with no external process.
- Unknown input formats are written as .jpg; HEIC is never substituted.
- Every per-image failure is offered for retry, including corrupt files.

### Not verified here

- Display scaling at 125%, 150% and 200%, and approval of the captured visual baselines (owner).
- The replacement confirmation answered with real input in the running app, and real HEIC files through the real dialog (no native journey).
- Behaviour when the disk fills or the output base is unwritable during a run.
- Very large batches (thousands of images) for memory and responsiveness beyond the decoding caps.
- The standalone `main()` window.
- macOS and Windows versions other than the gate machine.
