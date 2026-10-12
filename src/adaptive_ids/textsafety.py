"""Helpers for writing untrusted text into files people open in other tools."""

from __future__ import annotations

from typing import Any

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(v: Any) -> str:
    """Neutralise spreadsheet formula injection (CSV injection) in one exported cell.

    Text that a spreadsheet would treat as a formula is prefixed with an apostrophe.
    Real numbers are left alone so negative values stay numeric.
    """
    if v is None:
        return ""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    s = str(v)
    return "'" + s if s.startswith(_FORMULA_START) else s
