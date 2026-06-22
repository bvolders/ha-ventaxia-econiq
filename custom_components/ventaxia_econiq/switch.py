"""Free-cooling convenience switch for the summer bypass.

ON  → write the bypass config with ``mod = Normal`` (bypass enabled), keeping
      the fan speed / comfort thresholds the user (or an automation) has set.
OFF → write ``mod = Off`` (bypass disabled), thresholds preserved.

The actual damper open/close is then governed by the unit's firmware using the
``ect``/``ict`` thresholds — which the HA number entities can push beyond the
Connect app's 20 °C cap, enabling free-cooling the supplier app forbids.

State is optimistic (the last-written ``mod``), re-synced from the unit's
``vent/sbc`` echo. See PROTOCOL.md.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VentAxiaEconiqCoordinator
from .const import (
    BYPASS_MODE_TO_INT,
    BYPASS_SWITCH_OFF_MODE,
    BYPASS_SWITCH_ON_MODE,
    DOMAIN,
    TOPIC_BYPASS_CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VentAxiaEconiqCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EconiqBypassFreecoolSwitch(coordinator)])


class EconiqBypassFreecoolSwitch(SwitchEntity):
    """Enable/disable the summer bypass (free-cooling) in one tap."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "bypass_freecool"

    def __init__(self, coordinator: VentAxiaEconiqCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.device_id}_bypass_freecool"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._coordinator.device_id)},
            name=f"Vent-Axia Econiq {self._coordinator.device_id}",
            manufacturer="Vent-Axia",
            model="Econiq 600",
        )

    @property
    def available(self) -> bool:
        return self._coordinator.available

    @property
    def is_on(self) -> bool:
        return self._coordinator.bypass_config.get("mod") != BYPASS_MODE_TO_INT[
            BYPASS_SWITCH_OFF_MODE
        ]

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_sbc(_payload: Any) -> None:
            self.async_write_ha_state()

        @callback
        def _on_conn(_avail: bool) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            self._coordinator.subscribe_topic(TOPIC_BYPASS_CONFIG, _on_sbc)
        )
        self.async_on_remove(self._coordinator.subscribe_connection(_on_conn))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._write_mode(BYPASS_SWITCH_ON_MODE)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._write_mode(BYPASS_SWITCH_OFF_MODE)

    async def _write_mode(self, mode: str) -> None:
        cfg = dict(self._coordinator.bypass_config)
        await self._coordinator.publish_bypass_config(
            mod=BYPASS_MODE_TO_INT[mode],
            gtm=cfg["gtm"],
            ect=cfg["ect"],
            ict=cfg["ict"],
        )
        self.async_write_ha_state()
