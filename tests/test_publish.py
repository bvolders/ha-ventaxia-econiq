"""Tests for VentAxiaEconiqCoordinator publish methods."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError

from custom_components.ventaxia_econiq import VentAxiaEconiqCoordinator
from custom_components.ventaxia_econiq.const import (
    CONF_HOST,
    CONF_IDENTITY,
    CONF_PORT,
    CONF_PSK_KEY,
    CONF_TOPIC_PREFIX,
)


def _make_coordinator(hass) -> VentAxiaEconiqCoordinator:
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test-entry-id"
    entry.data = {
        CONF_HOST: "10.1.5.33",
        CONF_PORT: 8883,
        CONF_IDENTITY: "00" * 16,
        CONF_PSK_KEY: "11" * 8,
        CONF_TOPIC_PREFIX: "BZPKB-TEST",
    }
    return VentAxiaEconiqCoordinator(hass, entry)


async def test_publish_user_override_publishes_correct_topic_and_payload(hass) -> None:
    coordinator = _make_coordinator(hass)
    fake_client = MagicMock()
    fake_info = MagicMock()
    fake_info.is_published.return_value = True
    fake_client.publish.return_value = fake_info
    coordinator._client = fake_client

    await coordinator.publish_user_override(gtm=3, treq="00:30:00")

    fake_client.publish.assert_called_once()
    args, kwargs = fake_client.publish.call_args
    topic = args[0]
    payload = args[1]
    assert topic == "BZPKB-TEST/vent/uo"
    assert json.loads(payload) == {"gtm": 3, "treq": "00:30:00"}


async def test_publish_raises_when_not_connected(hass) -> None:
    coordinator = _make_coordinator(hass)
    coordinator._client = None
    with pytest.raises(HomeAssistantError, match="not connected"):
        await coordinator.publish_user_override(gtm=3, treq="00:30:00")


async def test_publish_raises_on_timeout(hass) -> None:
    coordinator = _make_coordinator(hass)
    fake_client = MagicMock()
    fake_info = MagicMock()
    fake_info.is_published.return_value = False
    fake_client.publish.return_value = fake_info
    coordinator._client = fake_client

    with pytest.raises(HomeAssistantError, match="publish"):
        await coordinator.publish_user_override(gtm=3, treq="00:30:00")


async def test_publish_cancel_uses_canonical_payload(hass) -> None:
    coordinator = _make_coordinator(hass)
    fake_client = MagicMock()
    fake_info = MagicMock()
    fake_info.is_published.return_value = True
    fake_client.publish.return_value = fake_info
    coordinator._client = fake_client

    await coordinator.publish_cancel_override()

    fake_client.publish.assert_called_once()
    args, _kw = fake_client.publish.call_args
    assert args[0] == "BZPKB-TEST/vent/uo"
    assert json.loads(args[1]) == {"gtm": 254, "treq": "00:00:00"}
