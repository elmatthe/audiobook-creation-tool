"""Single source of truth for the application version.

Bumped at the approved release-candidate checkpoint. ``0.8.1`` is the next shared Windows and macOS version: it
follows both the published Windows v0.8.0 and the macOS revision ``0.8.0+macos.1`` (D16, which carried build metadata
because it was built from different source than the Windows v0.8.0). Read by
``scripts/shared/release.py`` to name
the distribution zips, and available to any future about-box / ``--version``
output.
"""

VERSION = "0.8.1"
