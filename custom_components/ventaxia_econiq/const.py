"""Constants for the Vent-Axia Econiq integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "ventaxia_econiq"

CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_IDENTITY: Final = "identity"
CONF_PSK_KEY: Final = "psk_key"
CONF_TOPIC_PREFIX: Final = "topic_prefix"

DEFAULT_PORT: Final = 8883

# Subscribe-discovery: how long to listen for a publish to learn the topic prefix
DISCOVERY_TIMEOUT_SECONDS: Final = 8

# How long to keep a connection-lost state before firing entity unavailable
RECONNECT_BACKOFF_INITIAL_SECONDS: Final = 5
RECONNECT_BACKOFF_MAX_SECONDS: Final = 300
