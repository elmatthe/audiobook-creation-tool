"""Behaviour preservation: bootstrap's Kokoro-compatibility gate.

Kokoro's PyPI wheels require Python >=3.10,<3.13, so the venv base must be
gated on that range (the v0.5.0 macOS fix: a 3.13-only Mac must trigger a
Python 3.12 install instead of building a Kokoro-less venv). Pure logic —
no network, no venv, no interpreter probing.
"""

from __future__ import annotations

import pytest

from shared.bootstrap import _is_kokoro_compatible


@pytest.mark.parametrize(
    ("ver", "expected"),
    [
        ((3, 10), True),
        ((3, 11), True),
        ((3, 12), True),
        ((3, 13), False),
        ((3, 14), False),
        ((3, 9), False),
        (None, False),
    ],
)
def test_is_kokoro_compatible(ver, expected):
    assert _is_kokoro_compatible(ver) is expected
