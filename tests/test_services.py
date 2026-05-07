"""Tests for HA services exposed by ventaxia_econiq."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ventaxia_econiq import (
    VentAxiaEconiqCoordinator,
    _async_register_services,
)
from custom_components.ventaxia_econiq.const import (
    CONF_HOST,
    CONF_IDENTITY,
    CONF_PORT,
    CONF_PSK_KEY,
    CONF_TOPIC_PREFIX,
    DOMAIN,
)


@pytest.fixture
def mock_entry_with_coordinator(hass):
    """Set up a config entry with a mocked-out coordinator."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "10.1.5.33",
            CONF_PORT: 8883,
            CONF_IDENTITY: "00" * 16,
            CONF_PSK_KEY: "11" * 8,
            CONF_TOPIC_PREFIX: "BZPKB-TEST",
        },
        unique_id="BZPKB-TEST",
    )
    entry.add_to_hass(hass)

    coordinator = MagicMock(spec=VentAxiaEconiqCoordinator)
    coordinator.publish_user_override = AsyncMock()
    coordinator.publish_cancel_override = AsyncMock()
    coordinator.topic_prefix = "BZPKB-TEST"
    coordinator.entry = entry

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    return entry, coordinator


async def test_set_user_override_translates_mode_and_duration(
    hass, mock_entry_with_coordinator
) -> None:
    _entry, coordinator = mock_entry_with_coordinator
    await _async_register_services(hass)

    await hass.services.async_call(
        DOMAIN,
        "set_user_override",
        {"mode": "normal", "duration": "00:30:00"},
        blocking=True,
    )

    coordinator.publish_user_override.assert_awaited_once_with(gtm=2, treq="00:30:00")


async def test_set_user_override_rejects_unsupported_mode(
    hass, mock_entry_with_coordinator
) -> None:
    """boost/purge/max are in MODE_TO_GTM but not in SELECT_MODES — service rejects."""
    await _async_register_services(hass)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "set_user_override",
            {"mode": "boost", "duration": "00:30:00"},
            blocking=True,
        )


async def test_set_user_override_rejects_unknown_mode(
    hass, mock_entry_with_coordinator
) -> None:
    await _async_register_services(hass)

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "set_user_override",
            {"mode": "turbo", "duration": "00:30:00"},
            blocking=True,
        )


async def test_cancel_user_override_calls_coordinator(
    hass, mock_entry_with_coordinator
) -> None:
    _entry, coordinator = mock_entry_with_coordinator
    await _async_register_services(hass)

    await hass.services.async_call(
        DOMAIN, "cancel_user_override", {}, blocking=True
    )
    coordinator.publish_cancel_override.assert_awaited_once()


async def test_set_user_override_off_maps_to_gtm_0(
    hass, mock_entry_with_coordinator
) -> None:
    _entry, coordinator = mock_entry_with_coordinator
    await _async_register_services(hass)

    await hass.services.async_call(
        DOMAIN,
        "set_user_override",
        {"mode": "off", "duration": "02:00:00"},
        blocking=True,
    )

    coordinator.publish_user_override.assert_awaited_once_with(gtm=0, treq="02:00:00")
