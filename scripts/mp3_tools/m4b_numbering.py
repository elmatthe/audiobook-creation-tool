"""Compatibility re-export -- the allocator now lives in ``shared.numbering``.

v0.6.3 Plan 6 Phase 6 promoted the implementation so one allocator serves every
consumer. This module exists so the M4B Converter's existing import path keeps
working unchanged; it re-exports the very same objects rather than wrapping or
subclassing them, so ``mp3_tools.m4b_numbering.SuccessNumbers`` **is**
``shared.numbering.SuccessNumbers``. There is one implementation, not two.
"""

from __future__ import annotations

from shared.numbering import NumberingError, SuccessNumbers, Tentative

__all__ = ["NumberingError", "Tentative", "SuccessNumbers"]
