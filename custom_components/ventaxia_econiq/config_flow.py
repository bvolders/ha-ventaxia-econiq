"""Config flow for Vent-Axia Econiq."""
from __future__ import annotations

import asyncio
import logging
import socket
import ssl
from typing import Any

import paho.mqtt.client as mqtt
import voluptuous as vol
from paho.mqtt.enums import CallbackAPIVersion

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.exceptions import HomeAssistantError

from . import build_psk_context
from .const import (
    CONF_HOST,
    CONF_IDENTITY,
    CONF_PORT,
    CONF_PSK_KEY,
    CONF_TOPIC_PREFIX,
    DEFAULT_PORT,
    DISCOVERY_TIMEOUT_SECONDS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_IDENTITY): str,
        vol.Required(CONF_PSK_KEY): str,
    }
)


async def _discover_topic_prefix(
    host: str, port: int, identity: str, psk_hex: str
) -> str:
    """Connect, listen briefly, return the device's topic prefix.

    Econiq publishes everything under a single root segment such as
    ``BZPKB-7588F``. We subscribe to ``#`` and take the first segment of
    whatever publish lands first.
    """
    loop = asyncio.get_running_loop()
    prefix_future: asyncio.Future[str] = loop.create_future()
    error_future: asyncio.Future[Exception] = loop.create_future()

    def _on_connect(client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            loop.call_soon_threadsafe(
                error_future.set_result, InvalidAuth(f"CONNACK rc={reason_code}")
            )
            return
        client.subscribe("#", qos=0)

    def _on_message(client, userdata, msg):
        if prefix_future.done():
            return
        # First segment of topic is the device id
        seg = msg.topic.split("/", 1)[0]
        loop.call_soon_threadsafe(prefix_future.set_result, seg)

    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id="ha-econiq-discover",
    )
    client.on_connect = _on_connect
    client.on_message = _on_message

    try:
        ctx = build_psk_context(identity, psk_hex)
    except ValueError as err:
        raise InvalidAuth(f"PSK key is not valid hex: {err}") from err
    client.tls_set_context(ctx)
    client.tls_insecure_set(True)

    try:
        await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(
                None, client.connect, host, port, 60
            ),
            timeout=10,
        )
    except (OSError, socket.gaierror, asyncio.TimeoutError) as err:
        raise CannotConnect(f"Cannot reach {host}:{port}: {err}") from err
    except ssl.SSLError as err:
        raise InvalidAuth(f"TLS-PSK rejected: {err}") from err

    client.loop_start()
    try:
        done, pending = await asyncio.wait(
            [prefix_future, error_future],
            timeout=DISCOVERY_TIMEOUT_SECONDS,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for fut in pending:
            fut.cancel()
        if error_future in done:
            raise error_future.result()
        if prefix_future in done:
            return prefix_future.result()
        raise CannotConnect(
            "Connected but no publishes received during "
            f"{DISCOVERY_TIMEOUT_SECONDS}s discovery window. "
            "Check the unit is awake and on the network."
        )
    finally:
        client.disconnect()
        client.loop_stop()


class VentAxiaEconiqConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Vent-Axia Econiq."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                topic_prefix = await _discover_topic_prefix(
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    user_input[CONF_IDENTITY],
                    user_input[CONF_PSK_KEY],
                )
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pragma: no cover
                _LOGGER.exception("unexpected error during discovery")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(topic_prefix)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Vent-Axia Econiq ({topic_prefix})",
                    data={**user_input, CONF_TOPIC_PREFIX: topic_prefix},
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """TCP/MQTT couldn't reach the unit."""


class InvalidAuth(HomeAssistantError):
    """TLS-PSK or MQTT-CONNECT rejected."""
