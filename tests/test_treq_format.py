"""Tests for the treq (HH:MM:SS) duration formatter."""
from __future__ import annotations

from datetime import timedelta

import pytest

from custom_components.ventaxia_econiq.helpers import format_treq


def test_one_hour() -> None:
    assert format_treq(timedelta(hours=1)) == "01:00:00"


def test_thirty_minutes() -> None:
    assert format_treq(timedelta(minutes=30)) == "00:30:00"


def test_eight_hours() -> None:
    assert format_treq(timedelta(hours=8)) == "08:00:00"


def test_fifteen_minutes() -> None:
    assert format_treq(timedelta(minutes=15)) == "00:15:00"


def test_combined_h_m_s() -> None:
    assert format_treq(timedelta(hours=2, minutes=15, seconds=30)) == "02:15:30"


def test_zero() -> None:
    assert format_treq(timedelta()) == "00:00:00"


def test_rejects_negative() -> None:
    with pytest.raises(ValueError):
        format_treq(timedelta(seconds=-1))


def test_rejects_over_99h() -> None:
    with pytest.raises(ValueError):
        format_treq(timedelta(hours=100))
