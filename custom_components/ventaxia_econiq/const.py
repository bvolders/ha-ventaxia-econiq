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


# ----------------------------------------------------------------------
# v0.2 control — write-side constants
#
# Source of truth: tools/trace_unit.results.md (Phase A wire capture, 2026-05-07).

# Topic suffix (under <prefix>/) where airflow-mode overrides are published.
TOPIC_USER_OVERRIDE: Final = "vent/uo"

# AirflowPreset enum from Hermes bytecode function 31116. Phase A (2026-05-07)
# confirmed all 7 values are *accepted* by the firmware, BUT only off/low/normal
# produce a properly-timed override on `vent/uo`. Boost/purge/max publish cleanly
# yet the unit echoes vent/cor with empty trem and zero treq, indicating the
# unit silently rejected the timed-override aspect — the Connect app likely uses
# a different write path (vent/caf/wr or vent/cm/wr) for those.
MODE_TO_GTM: Final[dict[str, int]] = {
    "off": 0,
    "low": 1,
    "normal": 2,
    "boost": 3,
    "purge": 4,
    "none": 254,  # canonical "no override / cancel" sentinel
    "max": 255,
}

# Modes exposed in the v0.2 user-facing select + service schema. The other
# entries in MODE_TO_GTM stay reserved for future investigation but aren't
# offered to users yet.
SELECT_MODES: Final[tuple[str, ...]] = ("off", "low", "normal")

# vent/cor.ot value when no override is active (unit follows its schedule).
# Phase A: idle echoes (ot=1, os=130, trem="", treq="00:00:00").
# Override-active states observed: ot ∈ {9, 10, 16}. We compare on ot only —
# os value is unstable enough across modes that ot alone is the cleaner signal.
IDLE_OT: Final[int] = 1

# Cancel mechanism — confirmed in Phase A: publish gtm=254 to vent/uo silently
# cancels the active override and resumes the unit's schedule. No vent/cor
# echo is produced; observable only via RPMs returning to schedule baseline.
CANCEL_TOPIC_SUFFIX: Final[str] = "vent/uo"
CANCEL_PAYLOAD: Final[dict] = {"gtm": 254, "treq": "00:00:00"}
