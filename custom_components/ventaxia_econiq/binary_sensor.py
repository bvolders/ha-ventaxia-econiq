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
from .const import (
    BYPASS_OPEN_POSITIONS,
    BYPASS_POSITION_FROM_INT,
    BYPASS_STATUS_MODE_FROM_INT,
    DOMAIN,
    IDLE_OT,
    TOPIC_BYPASS_STATUS,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VentAxiaEconiqCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            EconiqOverrideActiveBinarySensor(coordinator),
            EconiqBypassOpenBinarySensor(coordinator),
        ]
    )


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


class EconiqBypassOpenBinarySensor(BinarySensorEntity):
    """True when the summer-bypass damper is open (vent/sbs.pos ∈ {3,4,5}).

    Replaces the provisional template heuristic. Exposes the decoded damper
    position, active bypass mode, and raw open-level as attributes.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "bypass_open"
    _attr_device_class = BinarySensorDeviceClass.OPENING

    def __init__(self, coordinator: VentAxiaEconiqCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.device_id}_bypass_open"
        self._is_on: bool | None = None
        self._attrs: dict[str, Any] = {}

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
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attrs

    @property
    def available(self) -> bool:
        return self._coordinator.available

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_sbs(payload: Any) -> None:
            if isinstance(payload, dict):
                self._on_vent_sbs(payload)

        @callback
        def _on_conn(_avail: bool) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            self._coordinator.subscribe_topic(TOPIC_BYPASS_STATUS, _on_sbs)
        )
        self.async_on_remove(self._coordinator.subscribe_connection(_on_conn))

    @callback
    def _on_vent_sbs(self, payload: dict) -> None:
        try:
            pos = int(payload.get("pos"))
        except (TypeError, ValueError):
            return
        self._is_on = pos in BYPASS_OPEN_POSITIONS
        am = payload.get("am")
        self._attrs = {
            "position": BYPASS_POSITION_FROM_INT.get(pos, "unknown"),
            "status_mode": BYPASS_STATUS_MODE_FROM_INT.get(am),
            "open_level": payload.get("op"),
        }
        self.async_write_ha_state()
