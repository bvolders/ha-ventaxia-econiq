"""Tests for v0.2 constants."""
from __future__ import annotations

from custom_components.ventaxia_econiq.const import (
    CANCEL_PAYLOAD,
    CANCEL_TOPIC_SUFFIX,
    IDLE_OT,
    MODE_TO_GTM,
    SELECT_MODES,
    TOPIC_USER_OVERRIDE,
)


def test_topic_user_override_is_vent_uo() -> None:
    assert TOPIC_USER_OVERRIDE == "vent/uo"


def test_mode_to_gtm_keeps_full_enum() -> None:
    """All 7 AirflowPreset values stay in the map for future RE work."""
    assert set(MODE_TO_GTM) == {"off", "low", "normal", "boost", "purge", "none", "max"}


def test_select_modes_only_exposes_validated_three() -> None:
    """v0.2: only off/low/normal produce a real timed override on vent/uo."""
    assert SELECT_MODES == ("off", "low", "normal")


def test_mode_to_gtm_canonical_mapping() -> None:
    # Per AirflowPreset enum from Hermes function 31116, confirmed in Phase A trace
    assert MODE_TO_GTM["off"] == 0
    assert MODE_TO_GTM["low"] == 1
    assert MODE_TO_GTM["normal"] == 2
    assert MODE_TO_GTM["boost"] == 3
    assert MODE_TO_GTM["purge"] == 4
    assert MODE_TO_GTM["none"] == 254
    assert MODE_TO_GTM["max"] == 255


def test_idle_ot_is_1() -> None:
    """Phase A confirmed: ot=1 means schedule-driven (no override)."""
    assert IDLE_OT == 1


def test_cancel_uses_gtm_254_to_vent_uo() -> None:
    """Phase A confirmed: cancel mechanism is gtm=254 published to vent/uo."""
    assert CANCEL_TOPIC_SUFFIX == "vent/uo"
    assert CANCEL_PAYLOAD == {"gtm": 254, "treq": "00:00:00"}
