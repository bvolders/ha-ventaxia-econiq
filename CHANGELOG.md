# Changelog

## v0.2.3 — 2026-06-22

### Fixed

- **Airflow was reported in the wrong unit.** The `vent/afs/fm` and `vent/afe/fm` flow-measurement topics report in **litres/second** (Vent-Axia commissioning convention), but were labeled and stored as m³/h directly. On a 600 m³/h unit this made airflow read implausibly low (~36 "m³/h" at 27% fan PWM). Evidence: over 10 days the raw value never exceeded ~80 — that is 13% of rating as m³/h (impossible) but 288 m³/h ≈ 48% as L/s, matching the ~50% max fan RPM observed. The integration now multiplies the raw L/s value by 3.6 and continues to present m³/h.
  - `sensor.<unit>_supply_airflow` / `_extract_airflow` now read ~3.6× higher (true m³/h).
  - History before this release is in the old (×3.6-too-low) scale; the graph will show a one-time step.

## v0.2.2 — 2026-05-12

### Fixed

- **Humidity labels were inverted.** The firmware's `io/irh/val` is the *intake* (outdoor) RH — air being drawn into the unit — not "Indoor humidity" as it was previously labeled. `io/erh/val` is the extract duct, which carries air pulled from the rooms, and is the actual indoor RH. (The neighbouring `eco2` = extract CO₂ sensor was already labeled correctly as indoor CO₂.)
  - `sensor.<unit>_indoor_humidity` now correctly reports indoor RH.
  - The intake/outdoor RH is now exposed as `sensor.<unit>_outdoor_humidity` (was misnamed `_extract_humidity`).
- **Includes a config-entry migration (v1 → v2).** Existing entity unique_ids and entity_id slugs are renamed in place — history is preserved, and any automation referencing `sensor.<unit>_indoor_humidity` keeps working and now reads correct data. **Breaking:** any automation that explicitly referenced `sensor.<unit>_extract_humidity` will need updating — that slug becomes `sensor.<unit>_indoor_humidity` after migration.

## v0.2.1 — 2026-05-07

### Added

- **`climate.<unit>_mvhr`** — exposes the unit as a `climate` entity so HA categorises the device under Climate. Modes: `OFF` and `FAN_ONLY`. Fan modes mirror the select (`off`/`low`/`normal`). `current_temperature` from the extract air sensor (`io/t3`). No `target_temperature` — the MVHR doesn't aim for a setpoint, it just moves air.

## v0.2.0 — 2026-05-07

### Added — write capability

- **`select.<unit>_fan_mode`** — 3-mode airflow override (Off / Low / Normal). State reflects the last successful write. Boost/Purge/Max are intentionally omitted from this release — see the "Verified mode map" section of the README for the firmware behavior we observed.
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
