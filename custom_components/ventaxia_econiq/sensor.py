"""Sensor entities for Vent-Axia Econiq."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    EntityCategory,
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import VentAxiaEconiqCoordinator
from .const import (
    AIR_QUALITY_FROM_INT,
    ANTIFROST_STATUS_FROM_INT,
    DOMAIN,
    TOPIC_AIR_QUALITY,
    TOPIC_ANTIFROST_STATUS,
    TOPIC_FILTER_LAST,
    TOPIC_FILTER_REMAINING,
    TOPIC_NOTIFICATIONS,
    TOPIC_RUNTIME,
)


@dataclass(frozen=True, kw_only=True)
class EconiqSensorDescription(SensorEntityDescription):
    """Describe a sensor mapped to a single MQTT topic suffix."""

    topic_suffix: str
    """Topic under the device prefix (e.g. ``io/t1``)."""
    value_fn: Callable[[Any], Any] = lambda v: v
    """Convert raw payload to entity state."""
    attr_fn: Callable[[Any], dict[str, Any] | None] = lambda v: None
    """Optional extra-state-attributes derived from payload."""


def _coerce_float(v: Any) -> float | None:
    if v is None or v == "nan":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _lps_to_m3h(v: Any) -> float | None:
    """Convert the unit's raw L/s airflow reading to m³/h.

    The ``vent/afs/fm`` / ``vent/afe/fm`` flow-measurement topics report in
    litres/second (Vent-Axia commissioning convention), NOT m³/h as originally
    assumed. Evidence: on this 600 m³/h unit the raw value never exceeded ~80
    over 10 days (= 288 m³/h ≈ 48% of rating at ~50% fan RPM); 80 m³/h would be
    only 13% of rating and is implausible. Multiply by 3.6 to present m³/h.
    """
    f = _coerce_float(v)
    return round(f * 3.6, 1) if f is not None else None


def _attr_passthrough(v: Any) -> dict[str, Any] | None:
    if isinstance(v, dict):
        return v
    return None


def _enum_from(mapping: dict[int, str]) -> Callable[[Any], str | None]:
    """Build a value_fn mapping a bare-int enum payload to its label."""

    def fn(v: Any) -> str | None:
        try:
            return mapping.get(int(v))
        except (TypeError, ValueError):
            return None

    return fn


def _antifrost_status(v: Any) -> str | None:
    if not isinstance(v, dict):
        return None
    try:
        return ANTIFROST_STATUS_FROM_INT.get(int(v.get("sta")))
    except (TypeError, ValueError):
        return None


def _filter_last(v: Any) -> str | None:
    """vent/filtertmr/last is an ISO datetime, or "0" when never set."""
    if v in (None, "", "0"):
        return None
    return str(v)


def _int_or_none(v: Any) -> int | None:
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _override_remaining_seconds(payload: Any) -> int | None:
    """Compute remaining seconds on an active override.

    Phase A confirmed vent/cor publishes ``trem`` as the override START timestamp
    (ISO local time, e.g. ``"2026-05-07T14:29:18"``) and ``treq`` as the requested
    duration (``HH:MM:SS``). Idle echoes both as empty/zero.

    Value is recomputed only when vent/cor echoes; for a live countdown the HA
    UI should compare against the last-changed timestamp.
    """
    if not isinstance(payload, dict):
        return None
    trem = payload.get("trem")
    treq = payload.get("treq")
    if not trem or not treq or treq == "00:00:00":
        return None
    try:
        start = datetime.fromisoformat(trem)
        parts = treq.split(":")
        if len(parts) != 3:
            return None
        h, m, s = (int(p) for p in parts)
        total = h * 3600 + m * 60 + s
        elapsed = (datetime.now() - start).total_seconds()
        return max(0, int(total - elapsed))
    except (TypeError, ValueError):
        return None


SENSORS: tuple[EconiqSensorDescription, ...] = (
    # ---- Temperatures (4 stations across the heat exchanger) ----
    EconiqSensorDescription(
        key="t1_outdoor_intake",
        translation_key="t1_outdoor_intake",
        topic_suffix="io/t1",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_coerce_float,
        suggested_display_precision=1,
    ),
    EconiqSensorDescription(
        key="t2_supply",
        translation_key="t2_supply",
        topic_suffix="io/t2",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_coerce_float,
        suggested_display_precision=1,
    ),
    EconiqSensorDescription(
        key="t3_extract",
        translation_key="t3_extract",
        topic_suffix="io/t3",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_coerce_float,
        suggested_display_precision=1,
    ),
    EconiqSensorDescription(
        key="t4_exhaust",
        translation_key="t4_exhaust",
        topic_suffix="io/t4",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_coerce_float,
        suggested_display_precision=1,
    ),
    # ---- Humidities ----
    # `irh` is intake RH (outdoor air being drawn in), not indoor — historically
    # misread. `erh` (extract) is the actual indoor RH, mirroring `eco2` below.
    EconiqSensorDescription(
        key="outdoor_rh",
        translation_key="outdoor_rh",
        topic_suffix="io/irh/val",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_coerce_float,
        suggested_display_precision=1,
    ),
    EconiqSensorDescription(
        key="indoor_rh",
        translation_key="indoor_rh",
        topic_suffix="io/erh/val",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_coerce_float,
        suggested_display_precision=1,
    ),
    EconiqSensorDescription(
        key="indoor_co2",
        translation_key="indoor_co2",
        topic_suffix="io/eco2/val",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_coerce_float,
        entity_registry_enabled_default=False,  # not installed on most units
    ),
    # ---- Airflows ----
    EconiqSensorDescription(
        key="supply_airflow",
        translation_key="supply_airflow",
        topic_suffix="vent/afs/fm",
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        native_unit_of_measurement=UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_lps_to_m3h,
        suggested_display_precision=1,
    ),
    EconiqSensorDescription(
        key="extract_airflow",
        translation_key="extract_airflow",
        topic_suffix="vent/afe/fm",
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        native_unit_of_measurement=UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_lps_to_m3h,
        suggested_display_precision=1,
    ),
    # ---- Fan RPM ----
    EconiqSensorDescription(
        key="supply_rpm",
        translation_key="supply_rpm",
        topic_suffix="vent/afs/rpm",
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_coerce_float,
        suggested_display_precision=0,
    ),
    EconiqSensorDescription(
        key="extract_rpm",
        translation_key="extract_rpm",
        topic_suffix="vent/afe/rpm",
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_coerce_float,
        suggested_display_precision=0,
    ),
    # ---- Fan PWM ----
    EconiqSensorDescription(
        key="supply_pwm",
        translation_key="supply_pwm",
        topic_suffix="vent/afs/pwm",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_coerce_float,
        suggested_display_precision=1,
    ),
    EconiqSensorDescription(
        key="extract_pwm",
        translation_key="extract_pwm",
        topic_suffix="vent/afe/pwm",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_coerce_float,
        suggested_display_precision=1,
    ),
    # ---- Fan power ----
    EconiqSensorDescription(
        key="supply_power",
        translation_key="supply_power",
        topic_suffix="vent/afs/pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_coerce_float,
        suggested_display_precision=1,
    ),
    EconiqSensorDescription(
        key="extract_power",
        translation_key="extract_power",
        topic_suffix="vent/afe/pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_coerce_float,
        suggested_display_precision=1,
    ),
    EconiqSensorDescription(
        key="total_power",
        translation_key="total_power",
        topic_suffix="mdet/pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_coerce_float,
        suggested_display_precision=1,
    ),
    # ---- Status / diagnostic ----
    EconiqSensorDescription(
        key="faults",
        translation_key="faults",
        topic_suffix="mdet/faults",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: int(v) if v is not None else None,
        entity_category=None,
    ),
    EconiqSensorDescription(
        key="warnings",
        translation_key="warnings",
        topic_suffix="mdet/warns",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: int(v) if v is not None else None,
    ),
    EconiqSensorDescription(
        key="wifi_rssi",
        translation_key="wifi_rssi",
        topic_suffix="mdet/wifi/sta",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda v: v.get("rssi") if isinstance(v, dict) else None,
        attr_fn=_attr_passthrough,
    ),
    # ---- Override state (the timed boost/intensive/etc) ----
    EconiqSensorDescription(
        key="override",
        translation_key="override",
        topic_suffix="vent/cor",
        # State is the operating-type integer; full payload exposed as attrs
        value_fn=lambda v: v.get("ot") if isinstance(v, dict) else None,
        attr_fn=_attr_passthrough,
    ),
    # ---- Current airflow program ----
    EconiqSensorDescription(
        key="current_airflow_program",
        translation_key="current_airflow_program",
        topic_suffix="vent/caf",
        value_fn=lambda v: v.get("ps") if isinstance(v, dict) else None,
        attr_fn=_attr_passthrough,
    ),
    # ---- Override remaining (seconds) ----
    EconiqSensorDescription(
        key="override_remaining",
        translation_key="override_remaining",
        topic_suffix="vent/cor",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_override_remaining_seconds,
    ),
    # ---- Air quality (vent/saq, bare enum) ----
    EconiqSensorDescription(
        key="air_quality",
        translation_key="air_quality",
        topic_suffix=TOPIC_AIR_QUALITY,
        device_class=SensorDeviceClass.ENUM,
        options=list(AIR_QUALITY_FROM_INT.values()),
        value_fn=_enum_from(AIR_QUALITY_FROM_INT),
    ),
    # ---- Antifrost status (vent/afstat.sta; usa/pwr as attrs) ----
    EconiqSensorDescription(
        key="antifrost_status",
        translation_key="antifrost_status",
        topic_suffix=TOPIC_ANTIFROST_STATUS,
        device_class=SensorDeviceClass.ENUM,
        options=list(ANTIFROST_STATUS_FROM_INT.values()),
        value_fn=_antifrost_status,
        attr_fn=_attr_passthrough,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ---- Filters ----
    EconiqSensorDescription(
        key="filter_remaining",
        translation_key="filter_remaining",
        topic_suffix=TOPIC_FILTER_REMAINING,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_coerce_float,
        suggested_display_precision=0,
    ),
    EconiqSensorDescription(
        key="filter_last_changed",
        translation_key="filter_last_changed",
        topic_suffix=TOPIC_FILTER_LAST,
        value_fn=_filter_last,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ---- Diagnostics ----
    EconiqSensorDescription(
        key="runtime",
        translation_key="runtime",
        topic_suffix=TOPIC_RUNTIME,
        # Unit (hours vs seconds) unconfirmed in the decompile — report raw,
        # monotonic. Add a device_class/unit once verified on the unit.
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_int_or_none,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EconiqSensorDescription(
        key="notifications",
        translation_key="notifications",
        topic_suffix=TOPIC_NOTIFICATIONS,
        value_fn=_int_or_none,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VentAxiaEconiqCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        EconiqSensor(coordinator, desc) for desc in SENSORS
    )

    # Computed: heat-recovery efficiency (supply temp gain / total available)
    async_add_entities([HeatRecoveryEfficiencySensor(coordinator)])


class EconiqSensor(SensorEntity):
    """Generic sensor for one MQTT topic suffix."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    entity_description: EconiqSensorDescription

    def __init__(
        self,
        coordinator: VentAxiaEconiqCoordinator,
        description: EconiqSensorDescription,
    ) -> None:
        self.entity_description = description
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.device_id}_{description.key}"
        self._raw_value: Any = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._coordinator.device_id)},
            name=f"Vent-Axia Econiq {self._coordinator.device_id}",
            manufacturer="Vent-Axia",
            model="Econiq 600",
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._raw_value)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.entity_description.attr_fn(self._raw_value)

    @property
    def available(self) -> bool:
        return self._coordinator.available and self._raw_value is not None

    async def async_added_to_hass(self) -> None:
        @callback
        def _update(value: Any) -> None:
            self._raw_value = value
            self.async_write_ha_state()

        @callback
        def _on_conn(_avail: bool) -> None:
            self.async_write_ha_state()

        # Replay last known value via the coordinator
        unsub_topic = self._coordinator.subscribe_topic(
            self.entity_description.topic_suffix, _update
        )
        unsub_conn = self._coordinator.subscribe_connection(_on_conn)
        self.async_on_remove(unsub_topic)
        self.async_on_remove(unsub_conn)


class HeatRecoveryEfficiencySensor(SensorEntity):
    """Computed: supply-temperature gain divided by available temp gradient.

    Formula: (T2 - T1) / (T3 - T1)  ×100  → %
    Where T1=outdoor intake, T2=supply (post heat exchanger), T3=extract from home.

    Returns None if T3 ≤ T1 (no useful gradient — e.g., summer bypass active).
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "heat_recovery_efficiency"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: VentAxiaEconiqCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.device_id}_heat_recovery_efficiency"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._coordinator.device_id)},
            name=f"Vent-Axia Econiq {self._coordinator.device_id}",
            manufacturer="Vent-Axia",
            model="Econiq 600",
        )

    @property
    def native_value(self) -> float | None:
        t1 = _coerce_float(self._coordinator.latest("io/t1"))
        t2 = _coerce_float(self._coordinator.latest("io/t2"))
        t3 = _coerce_float(self._coordinator.latest("io/t3"))
        if t1 is None or t2 is None or t3 is None:
            return None
        gradient = t3 - t1
        if gradient <= 0.5:  # avoid noise / division-by-near-zero in summer
            return None
        return round((t2 - t1) / gradient * 100, 1)

    @property
    def available(self) -> bool:
        return self._coordinator.available and self.native_value is not None

    async def async_added_to_hass(self) -> None:
        @callback
        def _update(_value: Any) -> None:
            self.async_write_ha_state()

        for topic in ("io/t1", "io/t2", "io/t3"):
            self.async_on_remove(
                self._coordinator.subscribe_topic(topic, _update)
            )
        self.async_on_remove(
            self._coordinator.subscribe_connection(lambda _a: self.async_write_ha_state())
        )
