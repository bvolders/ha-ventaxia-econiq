"""Tests for summer-bypass control: coordinator publish + entities."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError

from custom_components.ventaxia_econiq import VentAxiaEconiqCoordinator
from custom_components.ventaxia_econiq.binary_sensor import (
    EconiqBypassOpenBinarySensor,
)
from custom_components.ventaxia_econiq.const import (
    BYPASS_MODE_TO_INT,
    CONF_HOST,
    CONF_IDENTITY,
    CONF_PORT,
    CONF_PSK_KEY,
    CONF_TOPIC_PREFIX,
)
from custom_components.ventaxia_econiq.number import EconiqBypassTempNumber
from custom_components.ventaxia_econiq.select import (
    EconiqBypassFanSelect,
    EconiqBypassModeSelect,
)
from custom_components.ventaxia_econiq.switch import EconiqBypassFreecoolSwitch


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


def _mock_coordinator() -> MagicMock:
    c = MagicMock()
    c.subscribe_topic = MagicMock(return_value=lambda: None)
    c.subscribe_connection = MagicMock(return_value=lambda: None)
    c.available = True
    c.device_id = "BZPKB-TEST"
    c.bypass_config = {"mod": 0, "gtm": 2, "ect": 20.0, "ict": 22.0}
    c.publish_bypass_config = AsyncMock()
    return c


# ---- Coordinator publish + echo sync -------------------------------------

async def test_publish_bypass_config_topic_and_payload(hass) -> None:
    coordinator = _make_coordinator(hass)
    fake_client = MagicMock()
    fake_info = MagicMock()
    fake_info.is_published.return_value = True
    fake_client.publish.return_value = fake_info
    coordinator._client = fake_client

    await coordinator.publish_bypass_config(mod=1, gtm=2, ect=24.5, ict=21.0)

    args, _kw = fake_client.publish.call_args
    assert args[0] == "BZPKB-TEST/vent/sbc/wr"
    assert json.loads(args[1]) == {"mod": 1, "gtm": 2, "ect": 24.5, "ict": 21.0}
    # cache updated optimistically
    assert coordinator.bypass_config == {"mod": 1, "gtm": 2, "ect": 24.5, "ict": 21.0}


async def test_publish_bypass_config_raises_when_offline(hass) -> None:
    coordinator = _make_coordinator(hass)
    coordinator._client = None
    with pytest.raises(HomeAssistantError):
        await coordinator.publish_bypass_config(mod=1, gtm=2, ect=20.0, ict=22.0)
    # cache NOT mutated on failure (stays at the default off config)
    assert coordinator.bypass_config["mod"] == BYPASS_MODE_TO_INT["off"]


def test_on_bypass_echo_merges(hass) -> None:
    coordinator = _make_coordinator(hass)
    coordinator._on_bypass_echo({"mod": 3, "ect": 18.0})
    assert coordinator.bypass_config["mod"] == 3
    assert coordinator.bypass_config["ect"] == 18.0
    # untouched keys preserved
    assert "gtm" in coordinator.bypass_config and "ict" in coordinator.bypass_config


def test_on_bypass_echo_ignores_non_dict(hass) -> None:
    coordinator = _make_coordinator(hass)
    before = dict(coordinator.bypass_config)
    coordinator._on_bypass_echo("garbage")
    assert coordinator.bypass_config == before


# ---- Switch ---------------------------------------------------------------

async def test_switch_on_writes_normal_preserving_other_fields() -> None:
    coord = _mock_coordinator()
    coord.bypass_config = {"mod": 0, "gtm": 3, "ect": 24.0, "ict": 21.0}
    sw = EconiqBypassFreecoolSwitch(coord)
    sw.async_write_ha_state = MagicMock()

    await sw.async_turn_on()

    coord.publish_bypass_config.assert_awaited_once_with(
        mod=BYPASS_MODE_TO_INT["normal"], gtm=3, ect=24.0, ict=21.0
    )


async def test_switch_off_writes_off() -> None:
    coord = _mock_coordinator()
    coord.bypass_config = {"mod": 1, "gtm": 2, "ect": 20.0, "ict": 22.0}
    sw = EconiqBypassFreecoolSwitch(coord)
    sw.async_write_ha_state = MagicMock()

    await sw.async_turn_off()

    _args, kw = coord.publish_bypass_config.call_args
    assert kw["mod"] == BYPASS_MODE_TO_INT["off"]


def test_switch_is_on_reflects_mode() -> None:
    coord = _mock_coordinator()
    coord.bypass_config = {"mod": 0, "gtm": 2, "ect": 20.0, "ict": 22.0}
    assert EconiqBypassFreecoolSwitch(coord).is_on is False
    coord.bypass_config = {"mod": 1, "gtm": 2, "ect": 20.0, "ict": 22.0}
    assert EconiqBypassFreecoolSwitch(coord).is_on is True


# ---- Selects --------------------------------------------------------------

async def test_bypass_mode_select_writes_mod() -> None:
    coord = _mock_coordinator()
    sel = EconiqBypassModeSelect(coord)
    sel.async_write_ha_state = MagicMock()

    await sel.async_select_option("night_fresh")

    _args, kw = coord.publish_bypass_config.call_args
    assert kw["mod"] == BYPASS_MODE_TO_INT["night_fresh"]


def test_bypass_mode_select_current_option() -> None:
    coord = _mock_coordinator()
    coord.bypass_config = {"mod": 2, "gtm": 2, "ect": 20.0, "ict": 22.0}
    assert EconiqBypassModeSelect(coord).current_option == "evening_fresh"


async def test_bypass_mode_select_rejects_unknown() -> None:
    sel = EconiqBypassModeSelect(_mock_coordinator())
    with pytest.raises(ValueError):
        await sel.async_select_option("turbo")


async def test_bypass_fan_select_maps_gtm() -> None:
    coord = _mock_coordinator()
    sel = EconiqBypassFanSelect(coord)
    sel.async_write_ha_state = MagicMock()

    await sel.async_select_option("max")

    _args, kw = coord.publish_bypass_config.call_args
    assert kw["gtm"] == 255  # AirflowPreset.Max


def test_bypass_fan_select_current_option() -> None:
    coord = _mock_coordinator()
    coord.bypass_config = {"mod": 1, "gtm": 4, "ect": 20.0, "ict": 22.0}
    assert EconiqBypassFanSelect(coord).current_option == "purge"


# ---- Numbers --------------------------------------------------------------

async def test_bypass_ect_number_writes_merged() -> None:
    coord = _mock_coordinator()
    coord.bypass_config = {"mod": 1, "gtm": 2, "ect": 20.0, "ict": 22.0}
    num = EconiqBypassTempNumber(coord, "ect", "bypass_ect")
    num.async_write_ha_state = MagicMock()

    await num.async_set_native_value(25.5)

    coord.publish_bypass_config.assert_awaited_once_with(
        mod=1, gtm=2, ect=25.5, ict=22.0
    )


def test_bypass_ict_number_reads_value() -> None:
    coord = _mock_coordinator()
    coord.bypass_config = {"mod": 1, "gtm": 2, "ect": 20.0, "ict": 19.5}
    num = EconiqBypassTempNumber(coord, "ict", "bypass_ict")
    assert num.native_value == 19.5


# ---- Status binary sensor -------------------------------------------------

def test_bypass_open_binary_sensor_open_states() -> None:
    coord = _mock_coordinator()
    bs = EconiqBypassOpenBinarySensor(coord)
    bs.async_write_ha_state = MagicMock()

    bs._on_vent_sbs({"op": 100, "pos": 4, "am": 1})  # Open / Normal
    assert bs.is_on is True
    assert bs.extra_state_attributes["position"] == "open"
    assert bs.extra_state_attributes["status_mode"] == "normal"
    assert bs.extra_state_attributes["open_level"] == 100

    bs._on_vent_sbs({"op": 0, "pos": 2, "am": 0})  # Closed / Inactive
    assert bs.is_on is False
    assert bs.extra_state_attributes["position"] == "closed"


def test_bypass_open_binary_sensor_modulated_is_open() -> None:
    coord = _mock_coordinator()
    bs = EconiqBypassOpenBinarySensor(coord)
    bs.async_write_ha_state = MagicMock()
    bs._on_vent_sbs({"op": 50, "pos": 5, "am": 1})  # Modulated
    assert bs.is_on is True
