"""Tests for the BBQ-bypass button."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from custom_components.ventaxia_econiq.button import EconiqBbqBypassButton


def _coordinator() -> MagicMock:
    c = MagicMock()
    c.subscribe_connection = MagicMock(return_value=lambda: None)
    c.available = True
    c.device_id = "BZPKB-TEST"
    return c


async def test_press_calls_service_with_off_and_2h() -> None:
    btn = EconiqBbqBypassButton(_coordinator())
    btn.hass = MagicMock()
    btn.hass.services = MagicMock()
    btn.hass.services.async_call = AsyncMock()

    await btn.async_press()

    btn.hass.services.async_call.assert_awaited_once()
    args, _kw = btn.hass.services.async_call.call_args
    assert args[0] == "ventaxia_econiq"
    assert args[1] == "set_user_override"
    payload = args[2]
    assert payload["mode"] == "off"
    assert payload["duration"] == timedelta(hours=2)
