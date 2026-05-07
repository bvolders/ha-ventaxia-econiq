"""Tests for the override_remaining computation in sensor.py."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.ventaxia_econiq.sensor import _override_remaining_seconds


def test_idle_returns_none() -> None:
    assert _override_remaining_seconds({"ot": 1, "os": 130, "trem": "", "treq": "00:00:00"}) is None


def test_garbage_payload_returns_none() -> None:
    assert _override_remaining_seconds("not-a-dict") is None
    assert _override_remaining_seconds({"trem": "garbage", "treq": "00:30:00"}) is None
    assert _override_remaining_seconds({"trem": "2026-05-07T14:00:00", "treq": "garbage"}) is None


def test_just_started_returns_full_duration_minus_seconds_elapsed() -> None:
    """If trem is now, remaining ≈ treq."""
    now = datetime.now()
    trem = now.isoformat(timespec="seconds")
    payload = {"trem": trem, "treq": "00:30:00"}
    remaining = _override_remaining_seconds(payload)
    # 30 minutes minus a few millis of test execution
    assert remaining is not None
    assert 1790 < remaining <= 1800


def test_expired_returns_zero() -> None:
    """Override that started 1h ago with treq=30min should be 0 (clamped)."""
    started = datetime.now() - timedelta(hours=1)
    trem = started.isoformat(timespec="seconds")
    payload = {"trem": trem, "treq": "00:30:00"}
    assert _override_remaining_seconds(payload) == 0


def test_missing_treq_returns_none() -> None:
    payload = {"trem": "2026-05-07T14:00:00"}
    assert _override_remaining_seconds(payload) is None
