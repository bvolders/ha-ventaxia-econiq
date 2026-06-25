"""Tests for the control-mode select entity (v0.4).

The old user-override "fan mode" select was replaced by the `fan` entity; see
test_fan.py. This covers the new control-mode select (vent/cm).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ventaxia_econiq.const import (
    CONTROL_MODE_OPTIONS,
    CONTROL_MODE_TO_INT,
)
from custom_components.ventaxia_econiq.select import EconiqControlModeSelect


def _coordinator() -> MagicMock:
    c = MagicMock()
    c.subscribe_topic = MagicMock(return_value=lambda: None)
    c.subscribe_connection = MagicMock(return_value=lambda: None)
    c.available = True
    c.device_id = "BZPKB-TEST"
    c.publish_control_mode = AsyncMock()
    return c


def test_options_match_control_modes() -> None:
    sel = EconiqControlModeSelect(_coordinator())
    assert tuple(sel.options) == CONTROL_MODE_OPTIONS


def test_initial_state_is_none() -> None:
    assert EconiqControlModeSelect(_coordinator()).current_option is None


async def test_select_publishes_control_mode() -> None:
    coord = _coordinator()
    sel = EconiqControlModeSelect(coord)
    sel.async_write_ha_state = MagicMock()

    await sel.async_select_option("cv")

    coord.publish_control_mode.assert_awaited_once_with(CONTROL_MODE_TO_INT["cv"])
    assert sel.current_option == "cv"


async def test_select_rejects_unknown_mode() -> None:
    sel = EconiqControlModeSelect(_coordinator())
    sel.async_write_ha_state = MagicMock()
    with pytest.raises(ValueError):
        await sel.async_select_option("turbo")
