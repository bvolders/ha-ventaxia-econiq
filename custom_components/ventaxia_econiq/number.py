"""Override-duration number entity for Vent-Axia Econiq."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import VentAxiaEconiqCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VentAxiaEconiqCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EconiqOverrideDurationNumber(coordinator)])


class EconiqOverrideDurationNumber(NumberEntity, RestoreEntity):
    """How long the next override should run, in minutes.

    Pure HA-side state — does not publish on change. The select consumes this
    value via coordinator.override_duration_minutes when it fires an override.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "override_duration"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_min_value = 15
    _attr_native_max_value = 480
    _attr_native_step = 15
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: VentAxiaEconiqCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.device_id}_override_duration"
        self._attr_native_value: float = 60.0
        # Seed the coordinator's shared value so the select can read it
        # before this entity has been added to HA.
        coordinator.override_duration_minutes = int(self._attr_native_value)

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
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable"):
            try:
                self._attr_native_value = float(last.state)
            except (TypeError, ValueError):
                pass
        self._coordinator.override_duration_minutes = int(self._attr_native_value)

        @callback
        def _on_conn(_avail: bool) -> None:
            self.async_write_ha_state()

        self.async_on_remove(self._coordinator.subscribe_connection(_on_conn))

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self._coordinator.override_duration_minutes = int(value)
        self.async_write_ha_state()
