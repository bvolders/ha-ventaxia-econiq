"""Fan-mode select entity for Vent-Axia Econiq.

State model: last-successful-write. Phase A (2026-05-07) confirmed that
vent/cor's (ot, os) tuple does NOT uniquely identify the mode (off/low/normal
all collapse to (9, 129); boost/purge/max all collapse to (10, 130)). So
the select reflects the most recent successful publish_user_override call,
not a derived state from the wire. Mode changes from the unit's physical
keypad will not update this select — known limitation.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Callable

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VentAxiaEconiqCoordinator
from .const import (
    BYPASS_FAN_MODES,
    BYPASS_MODE_FROM_INT,
    BYPASS_MODE_TO_INT,
    BYPASS_SELECT_MODES,
    DOMAIN,
    MODE_TO_GTM,
    SELECT_MODES,
    TOPIC_BYPASS_CONFIG,
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

    def _duration_provider() -> int:
        """Read the override-duration carried on the coordinator (minutes)."""
        return getattr(coordinator, "override_duration_minutes", 60)

    async_add_entities(
        [
            EconiqFanModeSelect(coordinator, _duration_provider),
            EconiqBypassModeSelect(coordinator),
            EconiqBypassFanSelect(coordinator),
        ]
    )


class EconiqFanModeSelect(SelectEntity):
    """Select entity for the unit's user-override airflow mode."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "fan_mode"

    def __init__(
        self,
        coordinator: VentAxiaEconiqCoordinator,
        default_duration_provider: Callable[[], int],
    ) -> None:
        self._coordinator = coordinator
        self._default_duration_provider = default_duration_provider
        self._attr_unique_id = f"{coordinator.device_id}_fan_mode"
        self._attr_options = list(SELECT_MODES)
        self._current_option: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._coordinator.device_id)},
            name=f"Vent-Axia Econiq {self._coordinator.device_id}",
            manufacturer="Vent-Axia",
            model="Econiq 600",
        )

    @property
    def current_option(self) -> str | None:
        return self._current_option

    @property
    def available(self) -> bool:
        return self._coordinator.available

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_conn(_avail: bool) -> None:
            self.async_write_ha_state()

        self.async_on_remove(self._coordinator.subscribe_connection(_on_conn))

    async def async_select_option(self, option: str) -> None:
        if option not in SELECT_MODES:
            raise ValueError(f"unknown mode: {option}")

        duration_minutes = self._default_duration_provider()
        # Service call first; only update state if it succeeds. If the broker
        # times out or the unit is offline, the service raises and the select
        # stays at its previous value.
        await self.hass.services.async_call(
            DOMAIN,
            "set_user_override",
            {
                "mode": option,
                "duration": timedelta(minutes=duration_minutes),
            },
            blocking=True,
        )
        self._current_option = option
        self.async_write_ha_state()


class _EconiqBypassFieldSelect(SelectEntity):
    """Base for a select that owns one field of the shared bypass config.

    Reads its option from ``coordinator.bypass_config`` and, on change, merges
    the new value into the whole config and republishes via
    ``publish_bypass_config``. State stays put if the publish raises.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: VentAxiaEconiqCoordinator) -> None:
        self._coordinator = coordinator

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
    """Fan speed to run while bypassing (AirflowPreset → vent/sbc.gtm)."""

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
