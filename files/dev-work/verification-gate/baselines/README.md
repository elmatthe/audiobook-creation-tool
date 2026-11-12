# Visual baselines

`approved.json` lists visual baselines the owner has approved. It is empty until the owner reviews candidates. A gate run only reads it and lists what it captured in its own `visual-candidates.md`. A missing or changed baseline is a candidate for review, never approved automatically. An agent cannot approve one.

Each entry needs `approved_by: owner` plus `name`, `sha256`, `os`, `tk`, `dpi` and `client`, because a picture only means something on the configuration it came from.
