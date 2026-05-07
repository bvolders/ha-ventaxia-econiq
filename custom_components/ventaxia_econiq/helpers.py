"""Pure-Python helpers usable from anywhere in the integration."""
from __future__ import annotations

from datetime import timedelta


def format_treq(duration: timedelta) -> str:
    """Format a timedelta as the unit's HH:MM:SS treq string.

    The Vent-Axia firmware accepts a fixed two-digit hour field, so we cap
    the input at <100h and reject negatives.
    """
    total_seconds = int(duration.total_seconds())
    if total_seconds < 0:
        raise ValueError(f"duration cannot be negative: {duration!r}")
    if total_seconds >= 100 * 3600:
        raise ValueError(f"duration exceeds 99:59:59: {duration!r}")
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
