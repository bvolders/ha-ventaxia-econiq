"""Number entities for Vent-Axia Econiq: summer-bypass comfort thresholds."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VentAxiaEconiqCoordinator
from .const import (
    BYPASS_TEMP_MAX,
    BYPASS_TEMP_MIN,
    BYPASS_TEMP_STEP,
    DOMAIN,
    TOPIC_BYPASS_CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VentAxiaEconiqCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            EconiqBypassTempNumber(coordinator, "ect", "bypass_ect"),
            EconiqBypassTempNumber(coordinator, "ict", "bypass_ict"),
        ]
    )


class EconiqBypassTempNumber(NumberEntity):
    """A summer-bypass comfort-temperature threshold (ect or ict).

    ``ect`` = ExternalComfortTemperature (outdoor threshold),
    ``ict`` = RoomComfortTemperature (indoor target). Editing one merges it
    into the shared bypass config and republishes to vent/sbc/wr. The range
    intentionally exceeds the Connect app's 20 °C cap on ``ect`` so HA can
    drive free-cooling the app forbids. Value reflects coordinator.bypass_config.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = BYPASS_TEMP_MIN
    _attr_native_max_value = BYPASS_TEMP_MAX
    _attr_native_step = BYPASS_TEMP_STEP
    _attr_mode = NumberMode.BOX

    def __init__(
        self, coordinator: VentAxiaEconiqCoordinator, field: str, translation_key: str
    ) -> None:
        self._coordinator = coordinator
        self._field = field
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{coordinator.device_id}_{translation_key}"

    @property
    def device_info(self):
        return self._coordinator.device_info

    @property
    def available(self) -> bool:
        return self._coordinator.available

    @property
    def native_value(self) -> float | None:
        value = self._coordinator.bypass_config.get(self._field)
        return float(value) if value is not None else None

    async def async_added_to_hass(self) -> None:
        @callback
        def _refresh(_value=None) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            self._coordinator.subscribe_topic(TOPIC_BYPASS_CONFIG, _refresh)
        )
        self.async_on_remove(self._coordinator.subscribe_connection(_refresh))

    async def async_set_native_value(self, value: float) -> None:
        cfg = dict(self._coordinator.bypass_config)
        cfg[self._field] = value
        await self._coordinator.publish_bypass_config(
            mod=cfg["mod"], gtm=cfg["gtm"], ect=cfg["ect"], ict=cfg["ict"]
        )
        self.async_write_ha_state()
