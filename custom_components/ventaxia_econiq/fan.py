"""Fan entity for Vent-Axia Econiq — the primary airflow control.

Replaces the v0.3 `fan_mode` select + `mvhr` climate entity. Models the unit's
airflow as a HA fan with preset modes:

- **Setting a preset is PERSISTENT** — it writes the unit's default/idle airflow
  (`vent/daf/wr`), not a timed `vent/uo` override, and additionally clears any
  active user override so the new default takes effect immediately.
- **State is the TRUE current preset** reported on `vent/caf` (`.ps`), so changes
  made at the unit's keypad or by its schedule are reflected — unlike the old
  "last thing HA wrote" select.

Timed boosts remain available via the `set_user_override` service / BBQ button
(`vent/uo`); the fan entity deliberately does not use that path.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VentAxiaEconiqCoordinator
from .const import (
    AIRFLOW_PRESET_FROM_INT,
    DOMAIN,
    FAN_PRESET_MODES,
    MODE_TO_GTM,
    TOPIC_CURRENT_AIRFLOW,
)

_LOGGER = logging.getLogger(__name__)

_OFF = MODE_TO_GTM["off"]       # 0
_CANCEL = MODE_TO_GTM["none"]   # 254 (cancel sentinel, never a fan preset)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VentAxiaEconiqCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EconiqFan(coordinator)])


class EconiqFan(FanEntity):
    """The unit's airflow as a persistent fan with preset modes."""

    _attr_has_entity_name = True
    _attr_name = None  # the fan *is* the device → entity_id fan.<device>
    _attr_should_poll = False
    _attr_preset_modes = list(FAN_PRESET_MODES)
    _attr_supported_features = (
        FanEntityFeature.PRESET_MODE
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: VentAxiaEconiqCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.device_id}_fan"
        self._ps: int | None = None       # raw vent/caf.ps
        self._last_preset: str = "normal"  # restore target for turn_on

    @property
    def device_info(self):
        return self._coordinator.device_info

    @property
    def available(self) -> bool:
        return self._coordinator.available

    @property
    def is_on(self) -> bool | None:
        if self._ps is None:
            return None
        return self._ps not in (_OFF, _CANCEL)

    @property
    def preset_mode(self) -> str | None:
        if self._ps is None:
            return None
        name = AIRFLOW_PRESET_FROM_INT.get(self._ps)
        return name if name in FAN_PRESET_MODES else None

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_caf(payload: Any) -> None:
            if not isinstance(payload, dict) or "ps" not in payload:
                return
            try:
                self._ps = int(payload["ps"])
            except (TypeError, ValueError):
                return
            name = AIRFLOW_PRESET_FROM_INT.get(self._ps)
            if name in FAN_PRESET_MODES:
                self._last_preset = name
            self.async_write_ha_state()

        @callback
        def _on_conn(_avail: bool) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            self._coordinator.subscribe_topic(TOPIC_CURRENT_AIRFLOW, _on_caf)
        )
        self.async_on_remove(self._coordinator.subscribe_connection(_on_conn))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in FAN_PRESET_MODES:
            raise ValueError(f"unknown preset: {preset_mode}")
        # Persistent baseline, then clear any active timed override so it bites now.
        await self._coordinator.publish_default_airflow(MODE_TO_GTM[preset_mode])
        await self._coordinator.publish_cancel_override()
        self._ps = MODE_TO_GTM[preset_mode]  # optimistic; vent/caf confirms/corrects
        self._last_preset = preset_mode
        self.async_write_ha_state()

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        await self.async_set_preset_mode(preset_mode or self._last_preset)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._coordinator.publish_default_airflow(_OFF)
        await self._coordinator.publish_cancel_override()
        self._ps = _OFF
        self.async_write_ha_state()
