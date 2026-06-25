"""Tests for the summer-bypass comfort-threshold number entities.

(The override-duration number was removed in v0.4 — timed overrides now carry
their own duration via the `set_user_override` service.)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.ventaxia_econiq.const import (
    BYPASS_TEMP_MAX,
    BYPASS_TEMP_MIN,
    BYPASS_TEMP_STEP,
)
from custom_components.ventaxia_econiq.number import EconiqBypassTempNumber


def _coordinator() -> MagicMock:
    c = MagicMock()
    c.subscribe_topic = MagicMock(return_value=lambda: None)
    c.subscribe_connection = MagicMock(return_value=lambda: None)
    c.available = True
    c.device_id = "BZPKB-TEST"
    c.bypass_config = {"mod": 0, "gtm": 2, "ect": 20.0, "ict": 22.0}
    c.publish_bypass_config = AsyncMock()
    return c


def test_value_reflects_bypass_config() -> None:
    n = EconiqBypassTempNumber(_coordinator(), "ect", "bypass_ect")
    assert n.native_value == 20.0


def test_min_max_step() -> None:
    n = EconiqBypassTempNumber(_coordinator(), "ect", "bypass_ect")
    assert n.native_min_value == BYPASS_TEMP_MIN
    assert n.native_max_value == BYPASS_TEMP_MAX
    assert n.native_step == BYPASS_TEMP_STEP


def test_range_allows_above_app_cap() -> None:
    """The 20 °C Connect-app cap on ect is deliberately exceeded for free-cooling."""
    n = EconiqBypassTempNumber(_coordinator(), "ect", "bypass_ect")
    assert n.native_max_value > 20.0


async def test_set_value_merges_and_publishes() -> None:
    coord = _coordinator()
    n = EconiqBypassTempNumber(coord, "ect", "bypass_ect")
    n.async_write_ha_state = MagicMock()

    await n.async_set_native_value(24.5)

    coord.publish_bypass_config.assert_awaited_once_with(
        mod=0, gtm=2, ect=24.5, ict=22.0
    )
