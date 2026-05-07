# Changelog

## v0.2.0 — 2026-05-07

### Added — write capability

- **`select.<unit>_fan_mode`** — 7-mode airflow override (Off / Low / Normal / Boost / Purge / None / Max). State reflects the last successful write.
- **`number.<unit>_override_duration`** — how long the next override should run (15-480 min, 15-min step). Persists across HA restarts.
- **`button.<unit>_bbq_bypass`** — one-tap 2 h of total intake silence (`gtm=0`).
- **`binary_sensor.<unit>_override_active`** — True while the unit is running a user override (any non-idle `vent/cor.ot`).
- **`sensor.<unit>_override_remaining`** — countdown in seconds until the active override expires.
- **`ventaxia_econiq.set_user_override(mode, duration, [device_id])`** service.
- **`ventaxia_econiq.cancel_user_override([device_id])`** service.

### Verified on a live unit (2026-05-07)

The mode integers and cancel mechanism were validated by active wire probing — see `tools/trace_unit.results.md` for the captured data. Notable findings:

- `gtm=254` is the canonical cancel sentinel (silent on `vent/cor`; visible only via RPM resumption).
- `vent/cor`'s `(ot, os)` tuple does NOT uniquely identify the user-visible mode. The select therefore reflects the last successful write, not a derived state. **Known limitation: mode changes from the unit's physical keypad will not update the HA select.**

## v0.1.0 — 2026-05-06

Initial read-only release. 17 telemetry sensors via TLS-PSK MQTT (TLS 1.2, `PSK-AES128-CBC-SHA`).
