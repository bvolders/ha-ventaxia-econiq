"""Tests for the fan-mode select entity."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ventaxia_econiq.const import MODE_TO_GTM
from custom_components.ventaxia_econiq.select import EconiqFanModeSelect


def _coordinator() -> MagicMock:
    c = MagicMock()
    c.subscribe_topic = MagicMock(return_value=lambda: None)
    c.subscribe_connection = MagicMock(return_value=lambda: None)
    c.latest = MagicMock(return_value=None)
    c.available = True
    c.device_id = "BZPKB-TEST"
    c.override_duration_minutes = 60
    return c


def test_select_options_match_mode_to_gtm() -> None:
    sel = EconiqFanModeSelect(_coordinator(), default_duration_provider=lambda: 60)
    assert set(sel.options) == set(MODE_TO_GTM)


def test_initial_state_is_none() -> None:
    sel = EconiqFanModeSelect(_coordinator(), default_duration_provider=lambda: 60)
    assert sel.current_option is None


async def test_select_calls_set_user_override_service_with_current_duration() -> None:
    coord = _coordinator()
    sel = EconiqFanModeSelect(coord, default_duration_provider=lambda: 120)
    sel.hass = MagicMock()
    sel.hass.services = MagicMock()
    sel.hass.services.async_call = AsyncMock()
    sel.async_write_ha_state = MagicMock()

    await sel.async_select_option("boost")

    sel.hass.services.async_call.assert_awaited_once()
    args, _kw = sel.hass.services.async_call.call_args
    assert args[0] == "ventaxia_econiq"
    assert args[1] == "set_user_override"
    payload = args[2]
    assert payload["mode"] == "boost"
    assert payload["duration"] == timedelta(minutes=120)


async def test_state_updates_only_on_successful_publish() -> None:
    """If the service raises, the select state stays at the previous value."""
    coord = _coordinator()
    sel = EconiqFanModeSelect(coord, default_duration_provider=lambda: 60)
    sel.hass = MagicMock()
    sel.hass.services = MagicMock()
    sel.hass.services.async_call = AsyncMock(side_effect=RuntimeError("broker offline"))
    sel.async_write_ha_state = MagicMock()

    with pytest.raises(RuntimeError):
        await sel.async_select_option("boost")
    # current_option remains None — service raised before we update state
    assert sel.current_option is None


async def test_state_persists_after_successful_publish() -> None:
    coord = _coordinator()
    sel = EconiqFanModeSelect(coord, default_duration_provider=lambda: 60)
    sel.hass = MagicMock()
    sel.hass.services = MagicMock()
    sel.hass.services.async_call = AsyncMock()
    sel.async_write_ha_state = MagicMock()

    await sel.async_select_option("low")
    assert sel.current_option == "low"


async def test_select_rejects_unknown_mode() -> None:
    sel = EconiqFanModeSelect(_coordinator(), default_duration_provider=lambda: 60)
    sel.async_write_ha_state = MagicMock()
    with pytest.raises(ValueError):
        await sel.async_select_option("turbo")
