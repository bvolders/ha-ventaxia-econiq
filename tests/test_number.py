"""Tests for the override-duration number entity."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.ventaxia_econiq.number import EconiqOverrideDurationNumber


def _coordinator() -> MagicMock:
    c = MagicMock()
    c.subscribe_connection = MagicMock(return_value=lambda: None)
    c.available = True
    c.device_id = "BZPKB-TEST"
    return c


def test_default_value_is_60_minutes() -> None:
    n = EconiqOverrideDurationNumber(_coordinator())
    assert n.native_value == 60


def test_min_max_step() -> None:
    n = EconiqOverrideDurationNumber(_coordinator())
    assert n.native_min_value == 15
    assert n.native_max_value == 480
    assert n.native_step == 15


async def test_set_value_persists() -> None:
    n = EconiqOverrideDurationNumber(_coordinator())
    n.async_write_ha_state = MagicMock()
    await n.async_set_native_value(120)
    assert n.native_value == 120


async def test_set_value_does_not_publish() -> None:
    """Number changes are HA-side-only; nothing is sent to the unit."""
    coord = _coordinator()
    coord.publish_user_override = MagicMock()
    n = EconiqOverrideDurationNumber(coord)
    n.async_write_ha_state = MagicMock()
    await n.async_set_native_value(120)
    coord.publish_user_override.assert_not_called()


async def test_set_value_mirrors_to_coordinator() -> None:
    """The select reads coordinator.override_duration_minutes — keep them in sync."""
    coord = _coordinator()
    n = EconiqOverrideDurationNumber(coord)
    n.async_write_ha_state = MagicMock()
    await n.async_set_native_value(180)
    assert coord.override_duration_minutes == 180
