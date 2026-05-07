# Phase A — wire-format findings

**Captured:** 2026-05-07, BZPKB-7588F (Vent-Axia Econiq 600).
**Method:** active probe (`tools/probe_uo_sweep.py` + `tools/probe_uo_extras.py` + `tools/probe_gtm255.py`).

> **Why active rather than passive:** the unit's MQTT broker has a small connection budget. Concurrent sessions (HA + a passive trace + the iOS Connect app) caused the broker to hang, requiring a unit power-cycle to recover. Additionally, when the iOS app connected, our passive trace stopped receiving messages. Active probing with a single short-lived client is the practical path.

## Topic & payload

- **Write topic:** `<prefix>/vent/uo`
- **Payload:** `{"gtm": <int>, "treq": "HH:MM:SS"}`
- **Echo topic:** `<prefix>/vent/cor` (operating override status — JSON `{ot, os, trem, treq}`)
- **Auxiliary state:** `<prefix>/vent/caf` publishes `{ps, prop}` after a mode change

## gtm → behavior table

| gtm | mode   | `vent/cor` echo (canonical)                                          | `vent/caf.ps` | RPM range | Notes |
|-----|--------|---------------------------------------------------------------------|---------------|-----------|-------|
| 0   | off    | `{"ot":9,"os":129,"trem":"<ts>","treq":"00:01:00"}` (also briefly `(16,129)` in transition) | 0 | supply→0, extract→0 | Halts both fans cleanly. PWM 48→0, power 31W→1W. |
| 1   | low    | `{"ot":9,"os":129,"trem":"<ts>","treq":"00:01:00"}`                  | (not captured) | 914-1376  | |
| 2   | normal | `{"ot":9,"os":129,"trem":"<ts>","treq":"00:01:00"}`                  | (not captured) | 1315-1718 | |
| 3   | boost  | `{"ot":10,"os":130,"trem":"","treq":"00:00:00"}` (transitional capture) | (not captured) | ~1686 (steady) | The empty trem/treq is the FIRST echo; a later steady echo with proper trem may follow. |
| 4   | purge  | `{"ot":10,"os":130,"trem":"","treq":"00:00:00"}`                     | 2 | extract spikes 381→1736, supply dips then climbs | |
| 254 | (cancel) | **No echo on `vent/cor`** | (not captured) | RPMs return to schedule baseline (~1690) | Confirmed cancel mechanism. |
| 255 | max    | `{"ot":10,"os":130,"trem":"","treq":"00:00:00"}`                     | (not captured) | (already high)| Confirmed supported. |

**Idle baseline** (no override active): `vent/cor: {"ot":1,"os":130,"trem":"","treq":"00:00:00"}`.

## Critical finding: `(ot, os)` does NOT uniquely identify the mode

The `(ot, os)` pair on `vent/cor` collapses modes into three buckets:

- `(ot=1, os=130)` — idle (no override running)
- `(ot=9, os=129)` — "low-class" override running (off / low / normal all map here)
- `(ot=10, os=130)` — "high-class" override running (boost / purge / max all map here)
- `(ot=16, os=129)` — brief transition state (seen during off-mode setup)

This means **we cannot derive the user-visible mode from `vent/cor`**. The integration must use **last-written mode** as the select's reported state. `vent/cor` is still useful for:

- `binary_sensor.override_active` — True iff `ot ∈ {9, 10, 16}`, False iff `ot == 1`.
- `sensor.override_remaining` — parses `trem` (a wall-clock timestamp when the override started, or `""`) and `treq` (the requested duration) to compute how much time is left.

`vent/caf.ps` MAY allow finer disambiguation (we saw ps=0 for off, ps=2 for purge), but the data is incomplete. Out of scope for v0.2.

## Cancel mechanism (confirmed)

- Publish `{"gtm": 254, "treq": "00:01:00"}` (or any treq) to `<prefix>/vent/uo`.
- The unit silently cancels the active override and resumes its schedule.
- No `vent/cor` echo is published; the absence of an echo combined with RPMs returning to baseline is the only confirmation.

The integration's `cancel_user_override` service uses this exact publish.

## Implications for v0.2 design (updates the original spec)

1. **`MODE_TO_GTM`** ships all 7 values: `off=0, low=1, normal=2, boost=3, purge=4, none=254, max=255`. (`none` may be exposed in the select as a manual cancel option, though `cancel_user_override` is the canonical cancel.)
2. **`OT_OS_TO_MODE`** is dropped — the data shows it can't reverse-map cleanly. The select uses last-written-only state. Documented as a known limitation: physical-keypad mode changes won't update the HA select.
3. **Optimistic-revert timer** is dropped from the select. Since we can't confirm which mode the unit is in via `vent/cor`, there's nothing to revert TO. Instead, we trust the broker's publish-acknowledgement: if `publish_user_override` succeeds (broker ack within 5 s), the select state stays at the chosen mode. If publish fails, we raise `HomeAssistantError` and leave the select state unchanged.
4. **`IDLE_OT_OS = (1, 130)`** powers `binary_sensor.override_active`.
5. **`CANCEL_PAYLOAD = {"gtm": 254, "treq": "00:00:00"}`**. Topic: `vent/uo` (same as set_user_override).
