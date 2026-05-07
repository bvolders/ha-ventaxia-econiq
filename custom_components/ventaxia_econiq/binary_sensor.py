"""Binary sensor: override_active.

True whenever the unit is running a user override (vent/cor.ot != IDLE_OT).
Phase A confirmed: ot=1 means schedule-driven; ot ∈ {9, 10, 16} means an
override is active.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VentAxiaEconiqCoordinator
from .const import DOMAIN, IDLE_OT


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VentAxiaEconiqCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EconiqOverrideActiveBinarySensor(coordinator)])


class EconiqOverrideActiveBinarySensor(BinarySensorEntity):
    """True when the unit is running a user override (not following schedule)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "override_active"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: VentAxiaEconiqCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.device_id}_override_active"
        self._is_on: bool | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._coordinator.device_id)},
            name=f"Vent-Axia Econiq {self._coordinator.device_id}",
            manufacturer="Vent-Axia",
            model="Econiq 600",
        )

    @property
    def is_on(self) -> bool | None:
        return self._is_on

    @property
    def available(self) -> bool:
        return self._coordinator.available

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_cor(payload: Any) -> None:
            if isinstance(payload, dict):
                self._on_vent_cor(payload)

        @callback
        def _on_conn(_avail: bool) -> None:
            self.async_write_ha_state()

        self.async_on_remove(self._coordinator.subscribe_topic("vent/cor", _on_cor))
        self.async_on_remove(self._coordinator.subscribe_connection(_on_conn))

    @callback
    def _on_vent_cor(self, payload: dict) -> None:
        try:
            ot = int(payload.get("ot"))
        except (TypeError, ValueError):
            return
        self._is_on = ot != IDLE_OT
        self.async_write_ha_state()
