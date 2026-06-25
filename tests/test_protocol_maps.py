"""Pure-logic tests for the v0.4 protocol enum maps (no HA needed)."""
from __future__ import annotations

from custom_components.ventaxia_econiq.const import (
    AIRFLOW_PRESET_FROM_INT,
    AIR_QUALITY_FROM_INT,
    ANTIFROST_STATUS_FROM_INT,
    CONTROL_MODE_FROM_INT,
    CONTROL_MODE_TO_INT,
    FAN_PRESET_MODES,
    MODE_TO_GTM,
)


def test_airflow_preset_roundtrips_for_every_fan_mode() -> None:
    for name in FAN_PRESET_MODES:
        assert AIRFLOW_PRESET_FROM_INT[MODE_TO_GTM[name]] == name


def test_fan_presets_exclude_off_and_cancel() -> None:
    assert "off" not in FAN_PRESET_MODES
    assert "none" not in FAN_PRESET_MODES  # 254 cancel sentinel


def test_control_mode_roundtrips() -> None:
    for name, value in CONTROL_MODE_TO_INT.items():
        assert CONTROL_MODE_FROM_INT[value] == name
    assert set(CONTROL_MODE_TO_INT) == {"fixed", "cv", "cp"}


def test_air_quality_labels() -> None:
    assert AIR_QUALITY_FROM_INT == {0: "disabled", 1: "good", 2: "neutral", 3: "bad"}


def test_antifrost_status_has_inactive_zero() -> None:
    assert ANTIFROST_STATUS_FROM_INT[0] == "inactive"
