# sox 1.5.0 Python wrapper wheel (ACT supply)

This directory holds one exact artifact that Audiobook Creation Tool (ACT) may
download as an immutable, commit-pinned supply:

| Field | Value |
|---|---|
| File | `sox-1.5.0-py3-none-any.whl` |
| Size | 40,164 bytes |
| SHA-256 | `d7f2d5a2390fa235b4195700e72d5bd9b507d88e4598cadcfd17aaccae2b8934` |
| Distribution | `sox` 1.5.0, `py3-none-any`, no `Requires-Python` declared |
| Runtime requirements | `numpy>=1.9.0`, `typing-extensions>=3.7.4.2` |
| Upstream | pysox by Rachel Bittner, <https://github.com/rabitt/pysox> |
| License | BSD-3-Clause (full text in `LICENSE`) |

## What this is

The wheel was generated locally from the original PyPI source distribution
`sox-1.5.0.tar.gz` (63,905 bytes, SHA-256
`12c7be5bb1f548d891fe11e82c08cf5f1a1d74e225298f60082e5aeb2469ada0`). It is
**not** a wheel published by the upstream project.

`COMPARISON.json` lists every entry of both archives by name, size and SHA-256.
The seven Python modules are byte-identical to the source, the license file is
relocated byte-identically to `sox-1.5.0.dist-info/licenses/LICENSE`, and all 12
`RECORD` rows verify. The only other wheel entries are the generated
`METADATA`, `WHEEL`, `RECORD` and `top_level.txt`. `PROVENANCE.json` records the
identities, the historical build-tool evidence and the owner decision.

**Byte-for-byte reproducible generation has NOT been proven.** This
distribution preserves the exact audited existing artifact accepted by the
owner. A different artifact cannot inherit that acceptance.

## What this is not

- **Not native SoX.** This is only the pure-Python `sox` wrapper. Its audio
  transformations run an external native SoX program, which is not supplied
  here. Importing the wrapper probes for that program (`sox -h`).
- **Not an install path.** Do not import Python from this directory or use it
  as an installation prefix. ACT verifies the downloaded bytes and installs the
  wheel offline into its own environment.
- **Not a production authorization.** Its presence enables nothing on its own.

## Delivery identity

The delivery identity is the full 40-character ID of the commit that added this
directory, combined with this exact path:

```text
https://raw.githubusercontent.com/elmatthe/audiobook-creation-tool/<commit>/supply/python/sox/1.5.0/sha256-d7f2d5a2390fa235b4195700e72d5bd9b507d88e4598cadcfd17aaccae2b8934/sox-1.5.0-py3-none-any.whl
```

A commit cannot contain its own ID, so the resolved commit is recorded outside
this directory. Branch names, tags and `latest` URLs are never valid identities.
Consumers must still check the exact size and SHA-256 and refuse redirects.

## License notice

The wheel and the `LICENSE` file in this directory retain the original notice:
Copyright (c) 2016, Rachel Bittner. All rights reserved. Redistribution is
under the BSD 3-Clause conditions and disclaimer reproduced in full in
`LICENSE`. This supply is not endorsed by pysox or its contributors.
