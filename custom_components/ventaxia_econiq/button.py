"""BBQ-bypass button for Vent-Axia Econiq.

One-tap button that asks the unit for 2h of total intake silence —
useful when neighbours barbecue and the F7 filter can't keep up.
"""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VentAxiaEconiqCoordinator
from .const import DOMAIN

BBQ_BYPASS_DURATION = timedelta(hours=2)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VentAxiaEconiqCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            EconiqBbqBypassButton(coordinator),
            EconiqFilterResetButton(coordinator),
        ]
    )


class EconiqBbqBypassButton(ButtonEntity):
    """Halt intake for 2h via the set_user_override service."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "bbq_bypass"

    def __init__(self, coordinator: VentAxiaEconiqCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.device_id}_bbq_bypass"

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

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_conn(_avail: bool) -> None:
            self.async_write_ha_state()

        self.async_on_remove(self._coordinator.subscribe_connection(_on_conn))

    async def async_press(self) -> None:
        await self.hass.services.async_call(
            DOMAIN,
            "set_user_override",
            {"mode": "off", "duration": BBQ_BYPASS_DURATION},
            blocking=True,
        )


class EconiqFilterResetButton(ButtonEntity):
    """Reset the filter-change timer (publishes the literal ``Cleaned``)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "filter_reset"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: VentAxiaEconiqCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.device_id}_filter_reset"

    @property
    def device_info(self):
        return self._coordinator.device_info

    @property
    def available(self) -> bool:
        return self._coordinator.available

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_conn(_avail: bool) -> None:
            self.async_write_ha_state()

        self.async_on_remove(self._coordinator.subscribe_connection(_on_conn))

    async def async_press(self) -> None:
        await self._coordinator.publish_filter_reset()
