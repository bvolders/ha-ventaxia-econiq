"""Tests for the EconiqFan entity (v0.4 persistent airflow control)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ventaxia_econiq.const import FAN_PRESET_MODES, MODE_TO_GTM
from custom_components.ventaxia_econiq.fan import EconiqFan


def _coordinator() -> MagicMock:
    c = MagicMock()
    c.device_id = "BZPKB-TEST"
    c.available = True
    c.subscribe_topic = MagicMock(return_value=lambda: None)
    c.subscribe_connection = MagicMock(return_value=lambda: None)
    c.publish_default_airflow = AsyncMock()
    c.publish_cancel_override = AsyncMock()
    return c


def test_preset_modes() -> None:
    assert tuple(EconiqFan(_coordinator()).preset_modes) == FAN_PRESET_MODES


def test_state_unknown_initially() -> None:
    fan = EconiqFan(_coordinator())
    assert fan.is_on is None
    assert fan.preset_mode is None


def test_state_derived_from_caf_ps() -> None:
    fan = EconiqFan(_coordinator())
    fan._ps = MODE_TO_GTM["normal"]
    assert fan.is_on is True
    assert fan.preset_mode == "normal"
    fan._ps = MODE_TO_GTM["off"]
    assert fan.is_on is False
    assert fan.preset_mode is None  # off is not a preset


async def test_set_preset_writes_persistent_daf_and_clears_override() -> None:
    coord = _coordinator()
    fan = EconiqFan(coord)
    fan.async_write_ha_state = MagicMock()

    await fan.async_set_preset_mode("boost")

    coord.publish_default_airflow.assert_awaited_once_with(MODE_TO_GTM["boost"])
    coord.publish_cancel_override.assert_awaited_once()
    assert fan.preset_mode == "boost"


async def test_turn_off_sets_daf_off() -> None:
    coord = _coordinator()
    fan = EconiqFan(coord)
    fan.async_write_ha_state = MagicMock()

    await fan.async_turn_off()

    coord.publish_default_airflow.assert_awaited_once_with(MODE_TO_GTM["off"])
    assert fan.is_on is False


async def test_turn_on_restores_last_preset() -> None:
    coord = _coordinator()
    fan = EconiqFan(coord)
    fan.async_write_ha_state = MagicMock()
    fan._last_preset = "low"

    await fan.async_turn_on()

    coord.publish_default_airflow.assert_awaited_once_with(MODE_TO_GTM["low"])


async def test_set_preset_rejects_unknown() -> None:
    fan = EconiqFan(_coordinator())
    fan.async_write_ha_state = MagicMock()
    with pytest.raises(ValueError):
        await fan.async_set_preset_mode("turbo")
