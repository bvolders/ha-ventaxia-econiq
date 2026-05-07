"""Tests for override_active binary sensor."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.ventaxia_econiq.binary_sensor import (
    EconiqOverrideActiveBinarySensor,
)


def _coordinator() -> MagicMock:
    c = MagicMock()
    c.subscribe_topic = MagicMock(return_value=lambda: None)
    c.subscribe_connection = MagicMock(return_value=lambda: None)
    c.available = True
    c.device_id = "BZPKB-TEST"
    return c


def test_idle_means_off() -> None:
    """ot=1 is the idle/schedule-driven state per Phase A."""
    bs = EconiqOverrideActiveBinarySensor(_coordinator())
    bs.async_write_ha_state = MagicMock()
    bs._on_vent_cor({"ot": 1, "os": 130, "trem": "", "treq": "00:00:00"})
    assert bs.is_on is False


def test_low_class_override_means_on() -> None:
    """ot=9 (off/low/normal) is an active override."""
    bs = EconiqOverrideActiveBinarySensor(_coordinator())
    bs.async_write_ha_state = MagicMock()
    bs._on_vent_cor({"ot": 9, "os": 129, "trem": "2026-05-07T14:29:18", "treq": "00:01:00"})
    assert bs.is_on is True


def test_high_class_override_means_on() -> None:
    """ot=10 (boost/purge/max) is an active override."""
    bs = EconiqOverrideActiveBinarySensor(_coordinator())
    bs.async_write_ha_state = MagicMock()
    bs._on_vent_cor({"ot": 10, "os": 130, "trem": "", "treq": "00:00:00"})
    assert bs.is_on is True


def test_transition_state_means_on() -> None:
    """ot=16 was observed during off-mode transition; treat as active."""
    bs = EconiqOverrideActiveBinarySensor(_coordinator())
    bs.async_write_ha_state = MagicMock()
    bs._on_vent_cor({"ot": 16, "os": 129, "trem": "2026-05-07T14:26:52", "treq": "00:01:00"})
    assert bs.is_on is True


def test_no_payload_yet_is_unknown() -> None:
    bs = EconiqOverrideActiveBinarySensor(_coordinator())
    assert bs.is_on is None


def test_garbage_payload_does_not_crash() -> None:
    bs = EconiqOverrideActiveBinarySensor(_coordinator())
    bs.async_write_ha_state = MagicMock()
    bs._on_vent_cor({"ot": "not-an-int"})
    # Should silently ignore; state stays unknown
    assert bs.is_on is None
