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


def _connected(coordinator):
    fake_client = MagicMock()
    fake_info = MagicMock()
    fake_info.is_published.return_value = True
    fake_client.publish.return_value = fake_info
    coordinator._client = fake_client
    return fake_client


async def test_publish_default_airflow_writes_daf_bare(hass) -> None:
    coordinator = _make_coordinator(hass)
    fake_client = _connected(coordinator)
    await coordinator.publish_default_airflow(2)
    args, _kw = fake_client.publish.call_args
    assert args[0] == "BZPKB-TEST/vent/daf/wr"
    assert args[1] == "2"  # bare value (not a JSON dict)


async def test_publish_control_mode_writes_cm_bare(hass) -> None:
    coordinator = _make_coordinator(hass)
    fake_client = _connected(coordinator)
    await coordinator.publish_control_mode(1)
    args, _kw = fake_client.publish.call_args
    assert args[0] == "BZPKB-TEST/vent/cm/wr"
    assert args[1] == "1"


async def test_publish_filter_reset_is_unquoted_literal(hass) -> None:
    """Reset must be the bare literal `Cleaned`, NOT JSON-quoted '"Cleaned"'."""
    coordinator = _make_coordinator(hass)
    fake_client = _connected(coordinator)
    await coordinator.publish_filter_reset()
    args, _kw = fake_client.publish.call_args
    assert args[0] == "BZPKB-TEST/vent/filtertmr/reset"
    assert args[1] == "Cleaned"
    assert args[1] != json.dumps("Cleaned")  # proves _publish_raw doesn't JSON-encode


async def test_publish_raw_raises_when_not_connected(hass) -> None:
    coordinator = _make_coordinator(hass)
    coordinator._client = None
    with pytest.raises(HomeAssistantError, match="not connected"):
        await coordinator.publish_default_airflow(2)
