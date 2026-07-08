"""Drop 2 — shared-value detection in the M4B Metadata Editor.

Exercises ``M4BMetadataEditorUI._shared_tags`` without Tk: the method only
touches ``self.files`` and ``self._tags_for``, so a bare stub calling the
unbound method keeps these tests fast, deterministic, and display-free.
"""

from __future__ import annotations

from mp3_tools.m4b_metadata_editor import M4BMetadataEditorUI


def _shared_tags(tags_by_path: dict):
    """Run the real _shared_tags over canned per-file tag dicts (no Tk)."""

    class Stub:
        files = list(tags_by_path)

        def _tags_for(self, path):
            return tags_by_path[path]

    return M4BMetadataEditorUI._shared_tags(Stub())


def test_shared_artist_varying_title():
    shared, varies = _shared_tags(
        {
            "a": {"artist": "X", "title": "Book 1"},
            "b": {"artist": "X", "title": "Book 2"},
            "c": {"artist": "X", "title": "Book 3"},
        }
    )
    assert shared == {"artist": "X"}
    assert "title" in varies


def test_missing_key_on_one_file_is_not_shared():
    shared, varies = _shared_tags(
        {
            "a": {"artist": "X", "title": "Book 1"},
            "b": {"title": "Book 2"},  # no artist -> artist cannot be shared
        }
    )
    assert "artist" not in shared
    assert "artist" in varies  # present on some files, not all -> "(varies)"


def test_album_implied_series_never_shared():
    shared, varies = _shared_tags(
        {
            "a": {"series": "S", "series_source": "album-implied"},
            "b": {"series": "S", "series_source": "album-implied"},
        }
    )
    assert "series" not in shared  # display-only, must never be written back


def test_series_part_is_display_only():
    shared, varies = _shared_tags(
        {
            "a": {"series_part": "1"},
            "b": {"series_part": "1"},
        }
    )
    # Owned by the auto-number toggle: never pre-filled even when identical.
    assert "series_part" not in shared
    assert "series_part" not in varies


def test_unreadable_file_is_excluded_not_fatal():
    tags_by_path = {
        "a": {"artist": "X"},
        "broken": None,  # _tags_for returns None for a failed read
        "c": {"artist": "X"},
    }

    class Stub:
        files = list(tags_by_path)

        def _tags_for(self, path):
            return tags_by_path[path]

    shared, varies = M4BMetadataEditorUI._shared_tags(Stub())
    assert shared == {"artist": "X"}


def test_empty_file_list():
    assert _shared_tags({}) == ({}, set())


def test_values_compared_after_strip():
    shared, _varies = _shared_tags(
        {
            "a": {"artist": " X "},
            "b": {"artist": "X"},
        }
    )
    assert shared == {"artist": "X"}
