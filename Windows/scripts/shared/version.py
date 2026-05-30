"""Single source of truth for the application version.

Bumped on each release. Read by ``scripts/shared/release.py`` to name the
distribution zips, and available to any future about-box / ``--version`` output.
Kept byte-identical in the ``Windows/`` and ``MacOS/`` trees.
"""

VERSION = "0.1.2"
