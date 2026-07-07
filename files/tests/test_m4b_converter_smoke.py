"""Behaviour preservation: M4B Converter filename handling."""

from __future__ import annotations

from mp3_tools.m4b_converter import sanitize_filename


def test_sanitize_filename_behaviour():
    # Slashes and NULs become dashes; colons become ' - '; whitespace collapses.
    assert sanitize_filename("Book/Title") == "Book-Title"
    assert sanitize_filename("Series: Part 1") == "Series - Part 1"
    assert sanitize_filename("  lots   of   space  ") == "lots of space"
    # Unicode passes through untouched.
    assert sanitize_filename("Café テスト") == "Café テスト"
