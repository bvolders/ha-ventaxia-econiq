"""Climate entity for Vent-Axia Econiq.

Wraps the same publish path as the select but exposes it through HA's
climate platform so the device categorises under Climate in the UI.

Modeling notes:
- The MVHR doesn't heat or cool — it ventilates with heat exchange. So
  the only HVAC modes are OFF and FAN_ONLY.
- target_temperature is intentionally NOT a supported feature. The unit
  doesn't aim for a setpoint; it just moves air. Users wanting to see a
  thermostat setpoint can place the Bosch heat-pump card next to this one.
- current_temperature is taken from io/t3 (extract air = home return air),
  the closest proxy the unit publishes for "what the home feels like".
- fan_modes mirrors SELECT_MODES (off/low/normal). Picking "off" implicitly
  flips hvac_mode to OFF; picking "low"/"normal" flips it to FAN_ONLY.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VentAxiaEconiqCoordinator
from .const import DOMAIN, SELECT_MODES

_LOGGER = logging.getLogger(__name__)


def _coerce_float(v):
    if v is None or v == "nan":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VentAxiaEconiqCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EconiqClimate(coordinator)])


class EconiqClimate(ClimateEntity):
    """MVHR exposed as a climate entity (FAN_ONLY only — no heating/cooling)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "mvhr"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.FAN_ONLY]
    _attr_fan_modes = list(SELECT_MODES)
    _attr_supported_features = (
        ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    # HA 2024.2+ requires this when declaring TURN_ON/TURN_OFF explicitly,
    # or the entity is silently dropped during registration.
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator: VentAxiaEconiqCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.device_id}_climate"
        # Default state: unit is on FAN_ONLY (running schedule), no specific fan mode known.
        self._fan_mode: str | None = None

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
    def current_temperature(self) -> float | None:
        return _coerce_float(self._coordinator.latest("io/t3"))

    @property
    def hvac_mode(self) -> HVACMode:
        if self._fan_mode == "off":
            return HVACMode.OFF
        return HVACMode.FAN_ONLY

    @property
    def fan_mode(self) -> str | None:
        return self._fan_mode

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_t3(_value) -> None:
            self.async_write_ha_state()

        @callback
        def _on_conn(_avail: bool) -> None:
            self.async_write_ha_state()

        self.async_on_remove(self._coordinator.subscribe_topic("io/t3", _on_t3))
        self.async_on_remove(self._coordinator.subscribe_connection(_on_conn))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._publish_mode("off")
        elif hvac_mode == HVACMode.FAN_ONLY:
            # Going from OFF (or anywhere) back to FAN_ONLY: default to Normal.
            await self._publish_mode("normal")
        else:
            raise ValueError(f"unsupported hvac_mode: {hvac_mode}")

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if fan_mode not in SELECT_MODES:
            raise ValueError(f"unknown fan_mode: {fan_mode}")
        await self._publish_mode(fan_mode)

    async def _publish_mode(self, mode: str) -> None:
        duration_minutes = getattr(self._coordinator, "override_duration_minutes", 60)
        await self.hass.services.async_call(
            DOMAIN,
            "set_user_override",
            {"mode": mode, "duration": timedelta(minutes=duration_minutes)},
            blocking=True,
        )
        self._fan_mode = mode
        self.async_write_ha_state()
