"""Vent-Axia Econiq integration.

Connects to the unit's built-in MQTT broker via TLS-PSK (TLS 1.2 only,
PSK-AES128-CBC-SHA) and publishes telemetry as HA sensor entities.
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import ssl
from datetime import timedelta
from typing import Any, Callable

import paho.mqtt.client as mqtt
import voluptuous as vol
from paho.mqtt.enums import CallbackAPIVersion

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    BYPASS_ECT_DEFAULT,
    BYPASS_FAN_DEFAULT,
    BYPASS_FAN_MODES,
    BYPASS_ICT_DEFAULT,
    BYPASS_MODE_TO_INT,
    BYPASS_SELECT_MODES,
    BYPASS_TEMP_MAX,
    BYPASS_TEMP_MIN,
    CANCEL_PAYLOAD,
    CANCEL_TOPIC_SUFFIX,
    CONF_HOST,
    CONF_IDENTITY,
    CONF_PORT,
    CONF_PSK_KEY,
    CONF_TOPIC_PREFIX,
    DOMAIN,
    FILTER_RESET_PAYLOAD,
    MODE_TO_GTM,
    RECONNECT_BACKOFF_INITIAL_SECONDS,
    RECONNECT_BACKOFF_MAX_SECONDS,
    SELECT_MODES,
    TOPIC_BYPASS_CONFIG,
    TOPIC_BYPASS_CONFIG_WRITE,
    TOPIC_CONTROL_MODE_WRITE,
    TOPIC_DEFAULT_AIRFLOW_WRITE,
    TOPIC_FILTER_RESET,
    TOPIC_MODEL_DETAILS,
    TOPIC_USER_OVERRIDE,
)
from .helpers import format_treq

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.FAN,
]


def build_psk_context(identity: str, psk_hex: str) -> ssl.SSLContext:
    """Build a TLS-PSK context tuned for Econiq firmware.

    The unit only accepts TLS 1.2 with cipher PSK-AES128-CBC-SHA. Advertising
    TLS 1.3 in the ClientHello causes the unit to drop the connection. The PSK
    key is stored as a hex string by the iOS/Android app and must be sent as
    raw bytes (`bytes.fromhex`), not as ASCII.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers("PSK-AES128-CBC-SHA")
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    psk_bytes = bytes.fromhex(psk_hex)
    ctx.set_psk_client_callback(lambda hint: (identity, psk_bytes))
    return ctx


class VentAxiaEconiqCoordinator:
    """Owns the MQTT client lifecycle and dispatches updates to entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.host: str = entry.data[CONF_HOST]
        self.port: int = entry.data[CONF_PORT]
        self.identity: str = entry.data[CONF_IDENTITY]
        self.psk_hex: str = entry.data[CONF_PSK_KEY]
        self.topic_prefix: str = entry.data[CONF_TOPIC_PREFIX]

        self._client: mqtt.Client | None = None
        self._connected = asyncio.Event()
        self._listeners: dict[str, list[Callable[[Any], None]]] = {}
        self._latest: dict[str, Any] = {}
        self._connection_listeners: list[Callable[[bool], None]] = []
        self._available = False
        self._reconnect_task: asyncio.Task | None = None
        self._stopping = False

        # Cached summer-bypass config {mod, gtm, ect, ict}. Seeded with sane
        # defaults, kept in sync with the unit via the vent/sbc echo, and
        # updated optimistically on each successful write. The bypass control
        # entities each edit one field and republish the merged whole.
        self.bypass_config: dict[str, Any] = {
            "mod": BYPASS_MODE_TO_INT["off"],
            "gtm": MODE_TO_GTM[BYPASS_FAN_DEFAULT],
            "ect": BYPASS_ECT_DEFAULT,
            "ict": BYPASS_ICT_DEFAULT,
        }

        # Cached mdet/moddet ({sn, mc, mn, dom, fwv}) for DeviceInfo enrichment.
        self._model_details: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public API for entities

    @property
    def available(self) -> bool:
        return self._available

    @property
    def device_id(self) -> str:
        return self.topic_prefix

    @property
    def device_info(self) -> DeviceInfo:
        """Shared DeviceInfo, enriched from mdet/moddet when available.

        HA merges DeviceInfo across a device's entities, so it's enough for the
        entities that use this property to carry fw/model/serial; older entities
        with a plainer DeviceInfo merge into the same device by identifiers.
        """
        md = self._model_details
        info = DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=f"Vent-Axia Econiq {self.device_id}",
            manufacturer="Vent-Axia",
            model=str(md.get("mn") or "Econiq 600"),
        )
        if md.get("fwv") is not None:
            info["sw_version"] = str(md["fwv"])
        if md.get("sn"):
            info["serial_number"] = str(md["sn"])
        return info

    @callback
    def _on_moddet(self, payload: Any) -> None:
        """Cache mdet/moddet so device_info can expose fw/model/serial."""
        if isinstance(payload, dict):
            self._model_details = payload

    def latest(self, topic_suffix: str) -> Any:
        return self._latest.get(topic_suffix)

    def subscribe_topic(
        self, topic_suffix: str, callback_: Callable[[Any], None]
    ) -> Callable[[], None]:
        self._listeners.setdefault(topic_suffix, []).append(callback_)
        # Replay last-known value
        if topic_suffix in self._latest:
            try:
                callback_(self._latest[topic_suffix])
            except Exception as err:  # pragma: no cover
                _LOGGER.warning("listener replay error: %s", err)

        def _unsub() -> None:
            self._listeners.get(topic_suffix, []).remove(callback_)

        return _unsub

    def subscribe_connection(
        self, callback_: Callable[[bool], None]
    ) -> Callable[[], None]:
        self._connection_listeners.append(callback_)
        try:
            callback_(self._available)
        except Exception:  # pragma: no cover
            pass

        def _unsub() -> None:
            if callback_ in self._connection_listeners:
                self._connection_listeners.remove(callback_)

        return _unsub

    # ------------------------------------------------------------------
    # Public write API

    async def publish_user_override(self, gtm: int, treq: str) -> None:
        """Publish a user-override (mode + duration) to the unit.

        Topic: ``<prefix>/vent/uo``
        Payload: ``{"gtm": <int>, "treq": "HH:MM:SS"}``

        Blocks until the broker acknowledges the publish (max 5s).
        Raises HomeAssistantError on disconnect or timeout.
        """
        await self._publish_payload(TOPIC_USER_OVERRIDE, {"gtm": gtm, "treq": treq})

    async def publish_cancel_override(self) -> None:
        """Publish the cancel sentinel (gtm=254) to vent/uo.

        Confirmed in Phase A: this resumes the unit's schedule. No vent/cor
        echo is produced; only RPM changes confirm the cancel took effect.
        """
        await self._publish_payload(CANCEL_TOPIC_SUFFIX, CANCEL_PAYLOAD)

    async def publish_bypass_config(
        self, mod: int, gtm: int, ect: float, ict: float
    ) -> None:
        """Publish a summer-bypass configuration to the unit.

        Topic: ``<prefix>/vent/sbc/wr``
        Payload: ``{"mod": <int>, "gtm": <int>, "ect": <°C>, "ict": <°C>}``

        On success the local ``bypass_config`` cache is updated optimistically
        so the control entities reflect the new value immediately (the unit
        also echoes ``vent/sbc``, which re-syncs the cache). Raises
        HomeAssistantError on disconnect or publish timeout — the cache is NOT
        updated in that case.
        """
        payload = {"mod": int(mod), "gtm": int(gtm), "ect": ect, "ict": ict}
        await self._publish_payload(TOPIC_BYPASS_CONFIG_WRITE, payload)
        self.bypass_config = dict(payload)

    async def publish_default_airflow(self, preset: int) -> None:
        """Set the PERSISTENT default/idle airflow preset (``vent/daf/wr``).

        Bare-enum payload (AirflowPreset int). Unlike publish_user_override this
        is not timed — it's the unit's baseline when no override/schedule wins.
        """
        await self._publish_raw(TOPIC_DEFAULT_AIRFLOW_WRITE, str(int(preset)))

    async def publish_control_mode(self, mode: int) -> None:
        """Set the control mode (Fixed/CV/CP) via ``vent/cm/wr`` (bare enum)."""
        await self._publish_raw(TOPIC_CONTROL_MODE_WRITE, str(int(mode)))

    async def publish_filter_reset(self) -> None:
        """Reset the filter timer — publish the bare literal ``Cleaned``."""
        await self._publish_raw(TOPIC_FILTER_RESET, FILTER_RESET_PAYLOAD)

    @callback
    def _on_bypass_echo(self, payload: Any) -> None:
        """Keep ``bypass_config`` synced with the unit's vent/sbc echo."""
        if not isinstance(payload, dict):
            return
        merged = dict(self.bypass_config)
        for key in ("mod", "gtm", "ect", "ict"):
            if key in payload:
                merged[key] = payload[key]
        self.bypass_config = merged

    async def _publish_payload(self, topic_suffix: str, payload_dict: dict) -> None:
        if self._client is None:
            raise HomeAssistantError("Vent-Axia client not connected")
        topic = f"{self.topic_prefix}/{topic_suffix}"
        payload = json.dumps(payload_dict)
        client = self._client

        def _publish_and_wait() -> None:
            info = client.publish(topic, payload, qos=0)
            info.wait_for_publish(timeout=5)
            if not info.is_published():
                raise HomeAssistantError(
                    f"publish to {topic} did not complete within 5s"
                )

        await self.hass.async_add_executor_job(_publish_and_wait)

    async def _publish_raw(self, topic_suffix: str, raw: str) -> None:
        """Publish a bare (non-JSON) payload.

        For topics taking a bare enum/number (``vent/daf``, ``vent/cm``) or a
        literal string command (``vent/filtertmr/reset`` = ``Cleaned``).
        ``_publish_payload`` JSON-encodes, which would wrongly quote these.
        """
        if self._client is None:
            raise HomeAssistantError("Vent-Axia client not connected")
        topic = f"{self.topic_prefix}/{topic_suffix}"
        client = self._client

        def _publish_and_wait() -> None:
            info = client.publish(topic, raw, qos=0)
            info.wait_for_publish(timeout=5)
            if not info.is_published():
                raise HomeAssistantError(
                    f"publish to {topic} did not complete within 5s"
                )

        await self.hass.async_add_executor_job(_publish_and_wait)

    # ------------------------------------------------------------------
    # MQTT lifecycle (paho threads → HA event loop)

    async def async_start(self) -> None:
        client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=f"ha-econiq-{self.entry.entry_id[:8]}",
        )
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect

        try:
            ctx = build_psk_context(self.identity, self.psk_hex)
        except ValueError as err:
            raise ConfigEntryNotReady(
                f"PSK key is not valid hex: {err}"
            ) from err
        client.tls_set_context(ctx)
        client.tls_insecure_set(True)

        try:
            await self.hass.async_add_executor_job(
                client.connect, self.host, self.port, 60
            )
        except (OSError, socket.gaierror) as err:
            raise ConfigEntryNotReady(
                f"Cannot reach {self.host}:{self.port}: {err}"
            ) from err

        client.loop_start()
        self._client = client

    async def async_stop(self) -> None:
        self._stopping = True
        if self._reconnect_task:
            self._reconnect_task.cancel()
        if self._client is not None:
            await self.hass.async_add_executor_job(self._client.disconnect)
            await self.hass.async_add_executor_job(self._client.loop_stop)
            self._client = None

    # ------------------------------------------------------------------
    # paho callbacks (run on paho's thread; bounce to event loop)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        _LOGGER.info(
            "Vent-Axia connected to %s:%s (rc=%s)", self.host, self.port, reason_code
        )
        client.subscribe(f"{self.topic_prefix}/#", qos=0)
        self.hass.loop.call_soon_threadsafe(self._set_available, True)

    def _on_disconnect(self, client, userdata, *args):
        _LOGGER.warning("Vent-Axia disconnected: %s", args)
        self.hass.loop.call_soon_threadsafe(self._set_available, False)

    def _on_message(self, client, userdata, msg):
        prefix = f"{self.topic_prefix}/"
        if not msg.topic.startswith(prefix):
            return
        suffix = msg.topic[len(prefix) :]
        payload = msg.payload
        # Decode: try JSON, then text, fall back to bytes
        decoded: Any
        try:
            import json

            decoded = json.loads(payload.decode("utf-8"))
        except Exception:
            try:
                decoded = payload.decode("utf-8").strip()
            except Exception:
                decoded = payload.hex()
        self.hass.loop.call_soon_threadsafe(self._dispatch, suffix, decoded)

    @callback
    def _dispatch(self, suffix: str, value: Any) -> None:
        self._latest[suffix] = value
        for cb in self._listeners.get(suffix, []):
            try:
                cb(value)
            except Exception as err:  # pragma: no cover
                _LOGGER.warning("listener %s raised: %s", suffix, err)

    @callback
    def _set_available(self, value: bool) -> None:
        if self._available == value:
            return
        self._available = value
        for cb in self._connection_listeners:
            try:
                cb(value)
            except Exception:  # pragma: no cover
                pass


# ----------------------------------------------------------------------
# Services

SERVICE_SET_USER_OVERRIDE = "set_user_override"
SERVICE_CANCEL_USER_OVERRIDE = "cancel_user_override"
SERVICE_SET_BYPASS = "set_bypass"
_SERVICES_REGISTERED = "ventaxia_econiq_services_registered"

SET_USER_OVERRIDE_SCHEMA = vol.Schema(
    {
        vol.Required("mode"): vol.In(list(SELECT_MODES)),
        vol.Required("duration", default="01:00:00"): cv.time_period,
        vol.Optional("device_id"): cv.string,
    }
)

CANCEL_USER_OVERRIDE_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
    }
)

SET_BYPASS_SCHEMA = vol.Schema(
    {
        vol.Optional("mode"): vol.In(list(BYPASS_SELECT_MODES)),
        vol.Optional("fan_mode"): vol.In(list(BYPASS_FAN_MODES)),
        vol.Optional("ect"): vol.All(
            vol.Coerce(float), vol.Range(min=BYPASS_TEMP_MIN, max=BYPASS_TEMP_MAX)
        ),
        vol.Optional("ict"): vol.All(
            vol.Coerce(float), vol.Range(min=BYPASS_TEMP_MIN, max=BYPASS_TEMP_MAX)
        ),
        vol.Optional("device_id"): cv.string,
    }
)


def _coordinator_for_call(hass: HomeAssistant, call) -> VentAxiaEconiqCoordinator:
    """Resolve which coordinator a service call targets."""
    coordinators: dict[str, VentAxiaEconiqCoordinator] = hass.data.get(DOMAIN, {})
    if not coordinators:
        raise HomeAssistantError("ventaxia_econiq is not configured")

    device_id = call.data.get("device_id")
    if device_id is None:
        if len(coordinators) > 1:
            raise HomeAssistantError(
                "Multiple Vent-Axia units configured; pass `device_id` to disambiguate"
            )
        return next(iter(coordinators.values()))

    from homeassistant.helpers import device_registry as dr
    registry = dr.async_get(hass)
    device = registry.async_get(device_id)
    if device is None:
        raise HomeAssistantError(f"unknown device_id: {device_id}")
    for entry_id in device.config_entries:
        if entry_id in coordinators:
            return coordinators[entry_id]
    raise HomeAssistantError(f"device_id {device_id} is not a Vent-Axia unit")


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register HA services. Idempotent."""
    if hass.data.get(_SERVICES_REGISTERED):
        return

    async def _set_user_override(call) -> None:
        coordinator = _coordinator_for_call(hass, call)
        mode: str = call.data["mode"]
        duration: timedelta = call.data["duration"]
        gtm = MODE_TO_GTM[mode]
        treq = format_treq(duration)
        await coordinator.publish_user_override(gtm=gtm, treq=treq)

    async def _cancel_user_override(call) -> None:
        coordinator = _coordinator_for_call(hass, call)
        await coordinator.publish_cancel_override()

    async def _set_bypass(call) -> None:
        coordinator = _coordinator_for_call(hass, call)
        cfg = dict(coordinator.bypass_config)
        if "mode" in call.data:
            cfg["mod"] = BYPASS_MODE_TO_INT[call.data["mode"]]
        if "fan_mode" in call.data:
            cfg["gtm"] = MODE_TO_GTM[call.data["fan_mode"]]
        if "ect" in call.data:
            cfg["ect"] = call.data["ect"]
        if "ict" in call.data:
            cfg["ict"] = call.data["ict"]
        await coordinator.publish_bypass_config(
            mod=cfg["mod"], gtm=cfg["gtm"], ect=cfg["ect"], ict=cfg["ict"]
        )

    hass.services.async_register(
        DOMAIN, SERVICE_SET_USER_OVERRIDE, _set_user_override,
        schema=SET_USER_OVERRIDE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CANCEL_USER_OVERRIDE, _cancel_user_override,
        schema=CANCEL_USER_OVERRIDE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_BYPASS, _set_bypass,
        schema=SET_BYPASS_SCHEMA,
    )
    hass.data[_SERVICES_REGISTERED] = True


# ----------------------------------------------------------------------
# HA entry points


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entries forward.

    v1 → v2 (0.2.2): humidity labels were inverted. The firmware's `io/irh/val`
    is the *intake* (outdoor) RH, not indoor — `erh` (extract) is the actual
    indoor RH. Rename unique_ids and entity_id slugs in place so history and
    automations referencing `sensor.<unit>_indoor_humidity` survive and now
    point at the right data.

    v2 → v3 (0.4.0): the user-override fan-mode select, the MVHR climate entity,
    and the override-duration number are removed — airflow is now a single `fan`
    entity (persistent ``vent/daf``) and the timed-override service carries its
    own duration. Drop the obsolete registry rows (unique_id suffixes
    ``_fan_mode`` / ``_climate`` / ``_override_duration``) so they don't linger
    as "unavailable". (Breaking: dashboards/automations referencing the old
    fan-mode select or the MVHR climate entity must move to ``fan.<unit>``.)
    """
    _LOGGER.info("Migrating Vent-Axia Econiq entry %s from v%s", entry.entry_id, entry.version)

    if entry.version > 3:
        return False

    from homeassistant.helpers import entity_registry as er

    if entry.version == 1:
        registry = er.async_get(hass)
        device_id = entry.data[CONF_TOPIC_PREFIX]

        # Order matters: free the `_indoor_rh` unique_id slot first by renaming
        # the misnamed old `_indoor_rh` (intake) to `_outdoor_rh`, then the old
        # `_extract_rh` (true indoor) can reuse `_indoor_rh`.
        renames = [
            (f"{device_id}_indoor_rh", f"{device_id}_outdoor_rh", "indoor_humidity", "outdoor_humidity"),
            (f"{device_id}_extract_rh", f"{device_id}_indoor_rh", "extract_humidity", "indoor_humidity"),
        ]

        for old_uid, new_uid, old_slug, new_slug in renames:
            entity_id = registry.async_get_entity_id("sensor", DOMAIN, old_uid)
            if entity_id is None:
                _LOGGER.debug("no entity with unique_id %s — skipping", old_uid)
                continue
            # Idempotency guard: if the target unique_id already exists, this
            # rename was effectively already applied (or the registry was
            # recreated in the v2 shape). Re-applying it raises ValueError and
            # would abort setup, leaving the entry stuck at v1 forever. Skip.
            if registry.async_get_entity_id("sensor", DOMAIN, new_uid) is not None:
                _LOGGER.warning(
                    "v2 migration: target unique_id %s already in use — %s "
                    "appears already migrated; skipping rename",
                    new_uid,
                    old_uid,
                )
                continue
            new_entity_id = (
                entity_id.replace(old_slug, new_slug, 1)
                if old_slug in entity_id
                else None
            )
            kwargs: dict[str, Any] = {"new_unique_id": new_uid}
            if new_entity_id and new_entity_id != entity_id:
                kwargs["new_entity_id"] = new_entity_id
            registry.async_update_entity(entity_id, **kwargs)
            _LOGGER.info(
                "renamed %s (unique_id %s → %s%s)",
                entity_id,
                old_uid,
                new_uid,
                f", entity_id → {new_entity_id}" if "new_entity_id" in kwargs else "",
            )

        hass.config_entries.async_update_entry(entry, version=2)

    if entry.version == 2:
        registry = er.async_get(hass)
        device_id = entry.data[CONF_TOPIC_PREFIX]
        # v0.4: the fan_mode select + mvhr climate are replaced by one fan
        # entity, and the override-duration number is removed (the timed-override
        # service carries its own duration now). Drop the obsolete registry rows
        # so they don't show as "unavailable". Idempotent: skip any already gone.
        for platform, uid in (
            ("select", f"{device_id}_fan_mode"),
            ("climate", f"{device_id}_climate"),
            ("number", f"{device_id}_override_duration"),
        ):
            eid = registry.async_get_entity_id(platform, DOMAIN, uid)
            if eid is not None:
                registry.async_remove(eid)
                _LOGGER.info("v3 migration: removed obsolete %s (%s)", eid, uid)
        hass.config_entries.async_update_entry(entry, version=3)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = VentAxiaEconiqCoordinator(hass, entry)
    await coordinator.async_start()
    # Keep the bypass-config cache synced with the unit's vent/sbc echo.
    coordinator.subscribe_topic(TOPIC_BYPASS_CONFIG, coordinator._on_bypass_echo)
    # Cache model details for DeviceInfo (fw/model/serial).
    coordinator.subscribe_topic(TOPIC_MODEL_DETAILS, coordinator._on_moddet)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await _async_register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: VentAxiaEconiqCoordinator = hass.data[DOMAIN].pop(
            entry.entry_id
        )
        await coordinator.async_stop()
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
