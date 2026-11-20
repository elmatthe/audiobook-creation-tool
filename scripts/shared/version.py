"""Single source of truth for the application version.

Bumped at the approved release-candidate checkpoint. ``0.8.0+macos.1`` (D16, owner route 2026-11-20): the first
macOS revision of the v0.8.0 generation, built from different source than the published Windows v0.8.0 (``d1701e9``),
so it never claims plain ``0.8.0``; its tag is ``v0.8.0-macos.1`` (``release.release_tag``). Read by
``scripts/shared/release.py`` to name
the distribution zips, and available to any future about-box / ``--version``
output.
"""

VERSION = "0.8.0+macos.1"
