"""Select entities for Vent-Axia Econiq.

- **Control mode** (Fixed / Constant-Volume / Constant-Pressure) — ``vent/cm``.
- **Summer-bypass mode** + **Summer-bypass fan speed** — ``vent/sbc``.

The v0.3 user-override "fan mode" select is gone in v0.4: airflow is now the
``fan`` entity (see fan.py), which sets the *persistent* ``vent/daf`` preset and
reads true state from ``vent/caf``. The bypass selects are unchanged in function
but relabelled "Summer-bypass …" (translations) so they can't be mistaken for
the main fan control.
"""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VentAxiaEconiqCoordinator
from .const import (
    BYPASS_FAN_MODES,
    BYPASS_MODE_FROM_INT,
    BYPASS_MODE_TO_INT,
    BYPASS_SELECT_MODES,
    CONTROL_MODE_FROM_INT,
    CONTROL_MODE_OPTIONS,
    CONTROL_MODE_TO_INT,
    DOMAIN,
    MODE_TO_GTM,
    TOPIC_BYPASS_CONFIG,
    TOPIC_CONTROL_MODE,
)

_LOGGER = logging.getLogger(__name__)

# Reverse map for the bypass fan select (gtm int → mode name).
_GTM_TO_FAN_MODE = {MODE_TO_GTM[m]: m for m in BYPASS_FAN_MODES}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VentAxiaEconiqCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            EconiqControlModeSelect(coordinator),
            EconiqBypassModeSelect(coordinator),
            EconiqBypassFanSelect(coordinator),
        ]
    )


class EconiqControlModeSelect(SelectEntity):
    """Control mode: Fixed / Constant-Volume / Constant-Pressure (vent/cm)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "control_mode"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: VentAxiaEconiqCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.device_id}_control_mode"
        self._attr_options = list(CONTROL_MODE_OPTIONS)
        self._mode: int | None = None

    @property
    def device_info(self):
        return self._coordinator.device_info

    @property
    def available(self) -> bool:
        return self._coordinator.available

    @property
    def current_option(self) -> str | None:
        if self._mode is None:
            return None
        return CONTROL_MODE_FROM_INT.get(self._mode)

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_cm(payload) -> None:
            try:
                self._mode = int(payload)
            except (TypeError, ValueError):
                return
            self.async_write_ha_state()

        @callback
        def _on_conn(_avail: bool) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            self._coordinator.subscribe_topic(TOPIC_CONTROL_MODE, _on_cm)
        )
        self.async_on_remove(self._coordinator.subscribe_connection(_on_conn))

    async def async_select_option(self, option: str) -> None:
        if option not in CONTROL_MODE_TO_INT:
            raise ValueError(f"unknown control mode: {option}")
        await self._coordinator.publish_control_mode(CONTROL_MODE_TO_INT[option])
        self._mode = CONTROL_MODE_TO_INT[option]
        self.async_write_ha_state()


class _EconiqBypassFieldSelect(SelectEntity):
    """Base for a select that owns one field of the shared bypass config.

    Reads from ``coordinator.bypass_config`` and, on change, merges the new value
    into the whole config and republishes via ``publish_bypass_config``. State
    stays put if the publish raises.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: VentAxiaEconiqCoordinator) -> None:
        self._coordinator = coordinator

    @property
    def device_info(self):
        return self._coordinator.device_info

    @property
    def available(self) -> bool:
        return self._coordinator.available

    async def async_added_to_hass(self) -> None:
        @callback
        def _refresh(_value=None) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            self._coordinator.subscribe_topic(TOPIC_BYPASS_CONFIG, _refresh)
        )
        self.async_on_remove(self._coordinator.subscribe_connection(_refresh))

    async def _publish_field(self, key: str, value: int) -> None:
        cfg = dict(self._coordinator.bypass_config)
        cfg[key] = value
        await self._coordinator.publish_bypass_config(
            mod=cfg["mod"], gtm=cfg["gtm"], ect=cfg["ect"], ict=cfg["ict"]
        )
        self.async_write_ha_state()


class EconiqBypassModeSelect(_EconiqBypassFieldSelect):
    """Summer-bypass mode (SummerBypassModes → vent/sbc.mod)."""

    _attr_translation_key = "bypass_mode"

    def __init__(self, coordinator: VentAxiaEconiqCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_bypass_mode"
        self._attr_options = list(BYPASS_SELECT_MODES)

    @property
    def current_option(self) -> str | None:
        return BYPASS_MODE_FROM_INT.get(self._coordinator.bypass_config.get("mod"))

    async def async_select_option(self, option: str) -> None:
        if option not in BYPASS_MODE_TO_INT:
            raise ValueError(f"unknown bypass mode: {option}")
        await self._publish_field("mod", BYPASS_MODE_TO_INT[option])


class EconiqBypassFanSelect(_EconiqBypassFieldSelect):
    """Fan speed to run WHILE the summer bypass is open (vent/sbc.gtm).

    Only affects airflow while the bypass damper is actually open (firmware-gated
    to ≤20 °C outdoor). NOT the main fan control — that's the `fan` entity.
    """

    _attr_translation_key = "bypass_fan"

    def __init__(self, coordinator: VentAxiaEconiqCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_bypass_fan"
        self._attr_options = list(BYPASS_FAN_MODES)

    @property
    def current_option(self) -> str | None:
        return _GTM_TO_FAN_MODE.get(self._coordinator.bypass_config.get("gtm"))

    async def async_select_option(self, option: str) -> None:
        if option not in BYPASS_FAN_MODES:
            raise ValueError(f"unknown bypass fan mode: {option}")
        await self._publish_field("gtm", MODE_TO_GTM[option])
