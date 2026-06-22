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


# ----------------------------------------------------------------------
# v0.3 summer-bypass control — write/read side
#
# Source of truth: PROTOCOL.md + tools/bypass_decompile.results.md (Phase B,
# Connect app v7.2.2 decompile). The bypass has its own topic family — NOT the
# vent/caf|cm/wr path that was previously guessed.

# Config (read echo) and its write topic; status (damper) topic.
TOPIC_BYPASS_CONFIG: Final = "vent/sbc"
TOPIC_BYPASS_CONFIG_WRITE: Final = "vent/sbc/wr"
TOPIC_BYPASS_STATUS: Final = "vent/sbs"

# vent/sbc / vent/sbc/wr payload: {"mod": int, "gtm": int, "ect": °C, "ict": °C}
#   mod = SummerBypassModes, gtm = AirflowPreset (fan speed while bypassing),
#   ect = ExternalComfortTemperature (outdoor threshold), ict = RoomComfortTemperature.

# SummerBypassModes (mod). Numeric on the wire.
BYPASS_MODE_TO_INT: Final[dict[str, int]] = {
    "off": 0,
    "normal": 1,
    "evening_fresh": 2,
    "night_fresh": 3,
    "normal_modulation": 4,
    "evening_fresh_modulation": 5,
    "night_fresh_modulation": 6,
}
BYPASS_MODE_FROM_INT: Final[dict[int, str]] = {
    v: k for k, v in BYPASS_MODE_TO_INT.items()
}
BYPASS_SELECT_MODES: Final[tuple[str, ...]] = tuple(BYPASS_MODE_TO_INT)

# The mode the convenience switch enables / disables.
BYPASS_SWITCH_ON_MODE: Final[str] = "normal"
BYPASS_SWITCH_OFF_MODE: Final[str] = "off"

# Fan speed (gtm) offered for the bypass — reuses AirflowPreset / MODE_TO_GTM,
# minus the "none" cancel sentinel.
BYPASS_FAN_MODES: Final[tuple[str, ...]] = (
    "off",
    "low",
    "normal",
    "boost",
    "purge",
    "max",
)

# SummerBypassPosition (vent/sbs.pos) — the real damper-state field.
BYPASS_POSITION_FROM_INT: Final[dict[int, str]] = {
    0: "unknown",
    1: "closing",
    2: "closed",
    3: "opening",
    4: "open",
    5: "modulated",
}
# Damper counts as "open" for the binary_sensor when opening/open/modulated.
BYPASS_OPEN_POSITIONS: Final[frozenset[int]] = frozenset({3, 4, 5})

# SummerBypassStatusMode (vent/sbs.am).
BYPASS_STATUS_MODE_FROM_INT: Final[dict[int, str]] = {
    0: "inactive",
    1: "normal",
    2: "evening_fresh",
    3: "night_fresh",
    4: "antifrost",
    5: "diagnostic_open",
    6: "service_mode",
    7: "bms_override",
}

# Comfort-temperature bounds for the HA number entities. The Connect app caps
# the outdoor threshold (ect) at 20 °C; we deliberately allow higher so HA can
# drive free-cooling in conditions the app forbids.
BYPASS_TEMP_MIN: Final[float] = 5.0
BYPASS_TEMP_MAX: Final[float] = 30.0
BYPASS_TEMP_STEP: Final[float] = 0.5
BYPASS_ECT_DEFAULT: Final[float] = 20.0
BYPASS_ICT_DEFAULT: Final[float] = 22.0
BYPASS_FAN_DEFAULT: Final[str] = "normal"
