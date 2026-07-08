"""Drop 2 QA — Jack Ryan finished-product inspection.

The Jack Ryan set was built with every tool except TTS (MP3 Tool, M4B Maker,
Cover Resizer, M4B Metadata Editor), so it is the best single canary for
regressions in a *finished* product. Gated on JACK_RYAN_M4B_FOLDER because the
fixtures are gitignored, copyrighted, and local-only — CI and other machines
skip cleanly.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from shared import metadata

_FIXTURE_ENV = "JACK_RYAN_M4B_FOLDER"  # point at the Jack Ryan test folder
_folder = os.environ.get(_FIXTURE_ENV)

pytestmark = pytest.mark.skipif(
    not _folder or not Path(_folder).is_dir(),
    reason=f"set {_FIXTURE_ENV} to the Jack Ryan fixture folder to run",
)


def _m4bs():
    # Guard: this runs at collection time even when the module is skipped, so
    # an unset env var must yield [] rather than crash Path(None).
    if not _folder or not Path(_folder).is_dir():
        return []
    # NOTE: the Jack Ryan fixtures are nested one level deeper than the other
    # series — the .m4b files sit in an inner "Jack Ryan/" subfolder, not at
    # the folder root. rglob covers both the root-level and nested layouts so
    # the env var can point at either the outer or inner dir.
    return sorted(Path(_folder).rglob("*.m4b"))


def test_folder_has_m4bs():
    assert _m4bs(), "no .m4b files in the Jack Ryan fixture folder"


@pytest.mark.parametrize("path", _m4bs(), ids=lambda p: p.name)
def test_finished_product_invariants(path):
    tags = metadata.read_m4b_tags(path)
    # 1. Core tags present (built by MP3 Tool / M4B Maker).
    assert tags.get("title"), f"{path.name}: missing Title"
    assert tags.get("artist"), f"{path.name}: missing Author/Artist"
    # 2. Cover art embedded (Cover Resizer step).
    assert tags.get("has_cover"), f"{path.name}: no embedded cover"
    # 3. Chapters present and titled (M4B Maker).
    titles = metadata.read_chapter_titles(path)
    assert titles, f"{path.name}: no chapters"
    # 4. If a series part is present it must be a clean integer, and any
    #    written series must be ABS-readable (real name, not album-implied).
    part = (tags.get("series_part") or "").strip()
    if part:
        assert part.isdigit(), f"{path.name}: series-part '{part}' not an int"
    if tags.get("series") and tags.get("series_source") != "album-implied":
        assert tags["series"].strip(), f"{path.name}: empty series name written"


def test_series_is_consistent_across_the_set():
    # All Jack Ryan books should agree on one series name (or none should set it).
    names = {
        (metadata.read_m4b_tags(p).get("series") or "").strip()
        for p in _m4bs()
    }
    names.discard("")
    assert len(names) <= 1, f"Jack Ryan set has conflicting series names: {names}"
