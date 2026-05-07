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

from .const import (
    CANCEL_PAYLOAD,
    CANCEL_TOPIC_SUFFIX,
    CONF_HOST,
    CONF_IDENTITY,
    CONF_PORT,
    CONF_PSK_KEY,
    CONF_TOPIC_PREFIX,
    DOMAIN,
    MODE_TO_GTM,
    RECONNECT_BACKOFF_INITIAL_SECONDS,
    RECONNECT_BACKOFF_MAX_SECONDS,
    TOPIC_USER_OVERRIDE,
)
from .helpers import format_treq

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SELECT]


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

    # ------------------------------------------------------------------
    # Public API for entities

    @property
    def available(self) -> bool:
        return self._available

    @property
    def device_id(self) -> str:
        return self.topic_prefix

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
_SERVICES_REGISTERED = "ventaxia_econiq_services_registered"

SET_USER_OVERRIDE_SCHEMA = vol.Schema(
    {
        vol.Required("mode"): vol.In(list(MODE_TO_GTM.keys())),
        vol.Required("duration", default="01:00:00"): cv.time_period,
        vol.Optional("device_id"): cv.string,
    }
)

CANCEL_USER_OVERRIDE_SCHEMA = vol.Schema(
    {
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

    hass.services.async_register(
        DOMAIN, SERVICE_SET_USER_OVERRIDE, _set_user_override,
        schema=SET_USER_OVERRIDE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CANCEL_USER_OVERRIDE, _cancel_user_override,
        schema=CANCEL_USER_OVERRIDE_SCHEMA,
    )
    hass.data[_SERVICES_REGISTERED] = True


# ----------------------------------------------------------------------
# HA entry points


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = VentAxiaEconiqCoordinator(hass, entry)
    await coordinator.async_start()
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
