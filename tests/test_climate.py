"""Tests for the climate entity (v0.2.1)."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.climate import HVACMode

from custom_components.ventaxia_econiq.climate import EconiqClimate
from custom_components.ventaxia_econiq.const import SELECT_MODES


def _coordinator(t3: float | None = 21.5) -> MagicMock:
    c = MagicMock()
    c.subscribe_topic = MagicMock(return_value=lambda: None)
    c.subscribe_connection = MagicMock(return_value=lambda: None)
    c.latest = MagicMock(side_effect=lambda key: t3 if key == "io/t3" else None)
    c.available = True
    c.device_id = "BZPKB-TEST"
    c.override_duration_minutes = 60
    return c


def test_hvac_modes_are_off_and_fan_only() -> None:
    cli = EconiqClimate(_coordinator())
    assert HVACMode.OFF in cli.hvac_modes
    assert HVACMode.FAN_ONLY in cli.hvac_modes


def test_fan_modes_match_select_modes() -> None:
    cli = EconiqClimate(_coordinator())
    assert tuple(cli.fan_modes) == SELECT_MODES


def test_current_temperature_from_io_t3() -> None:
    cli = EconiqClimate(_coordinator(t3=22.3))
    assert cli.current_temperature == 22.3


def test_current_temperature_none_when_t3_missing() -> None:
    cli = EconiqClimate(_coordinator(t3=None))
    assert cli.current_temperature is None


def test_initial_hvac_mode_is_fan_only() -> None:
    """Default state when no override has been issued — unit follows schedule."""
    cli = EconiqClimate(_coordinator())
    assert cli.hvac_mode == HVACMode.FAN_ONLY


async def test_set_hvac_off_calls_service_with_off_mode() -> None:
    cli = EconiqClimate(_coordinator())
    cli.hass = MagicMock()
    cli.hass.services = MagicMock()
    cli.hass.services.async_call = AsyncMock()
    cli.async_write_ha_state = MagicMock()

    await cli.async_set_hvac_mode(HVACMode.OFF)

    args, _kw = cli.hass.services.async_call.call_args
    assert args[0] == "ventaxia_econiq"
    assert args[1] == "set_user_override"
    assert args[2]["mode"] == "off"
    assert args[2]["duration"] == timedelta(minutes=60)
    assert cli.hvac_mode == HVACMode.OFF


async def test_set_hvac_fan_only_defaults_to_normal() -> None:
    cli = EconiqClimate(_coordinator())
    cli.hass = MagicMock()
    cli.hass.services = MagicMock()
    cli.hass.services.async_call = AsyncMock()
    cli.async_write_ha_state = MagicMock()

    await cli.async_set_hvac_mode(HVACMode.FAN_ONLY)

    args, _kw = cli.hass.services.async_call.call_args
    assert args[2]["mode"] == "normal"
    assert cli.hvac_mode == HVACMode.FAN_ONLY


async def test_set_fan_mode_publishes_corresponding_gtm() -> None:
    cli = EconiqClimate(_coordinator())
    cli.hass = MagicMock()
    cli.hass.services = MagicMock()
    cli.hass.services.async_call = AsyncMock()
    cli.async_write_ha_state = MagicMock()

    await cli.async_set_fan_mode("low")
    args, _kw = cli.hass.services.async_call.call_args
    assert args[2]["mode"] == "low"
    assert cli.fan_mode == "low"
    assert cli.hvac_mode == HVACMode.FAN_ONLY


async def test_set_fan_mode_off_flips_hvac_to_off() -> None:
    cli = EconiqClimate(_coordinator())
    cli.hass = MagicMock()
    cli.hass.services = MagicMock()
    cli.hass.services.async_call = AsyncMock()
    cli.async_write_ha_state = MagicMock()

    await cli.async_set_fan_mode("off")
    assert cli.fan_mode == "off"
    assert cli.hvac_mode == HVACMode.OFF


async def test_set_fan_mode_rejects_unknown() -> None:
    cli = EconiqClimate(_coordinator())
    cli.async_write_ha_state = MagicMock()
    with pytest.raises(ValueError):
        await cli.async_set_fan_mode("turbo")
