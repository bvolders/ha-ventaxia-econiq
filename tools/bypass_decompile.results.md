# Phase B — Summer-bypass wire protocol (from app decompilation)

**Source:** Vent-Axia Connect Android app **v7.2.2** (`uk.ventaxia.connect`),
`assets/index.android.bundle` (Hermes bytecode version 96), disassembled and
decompiled with [`hermes-dec`](https://github.com/P1sec/hermes-dec).
**Method:** static analysis only — no live unit was touched for this phase.
**Date:** 2026-06-23.

> This documents the **summer bypass** (the heat-exchanger damper), which is a
> separate control path from the airflow-mode override on `vent/uo` documented
> in `trace_unit.results.md`. The hypothesis in `const.py` that bypass used a
> `vent/caf/wr` or `vent/cm/wr` path was **wrong** — it has its own `vent/sbc`
> family.

## Topics

| Purpose | Topic (`<prefix>/…`) | Direction |
|---------|----------------------|-----------|
| Summer-bypass **config** (read / echo) | `vent/sbc`     | unit → app |
| Summer-bypass **config write**         | `vent/sbc/wr`  | app → unit |
| Summer-bypass **status** (damper)      | `vent/sbs`     | unit → app |

Publish call (Hermes fn #25325):
`connection.publish('vent/sbc/wr', Buffer.from(JSON.stringify(config), 'utf-8'))`.
The `serializeJson` method copies the four config fields through **verbatim**
(no string⇄number coercion), so the wire values equal the model values.

## Config payload — `vent/sbc` and `vent/sbc/wr`

`summerBypassConfigurationSchema = z.object({ mod, gtm, ect, ict })`:

```json
{ "mod": <int>, "gtm": <int>, "ect": <number °C>, "ict": <number °C> }
```

- **`mod`** — `SummerBypassModes` (numeric):
  `0 Off, 1 Normal, 2 EveningFresh, 3 NightFresh, 4 NormalModulation,`
  `5 EveningFreshModulation, 6 NightFreshModulation`
- **`gtm`** — `AirflowPreset` = the fan speed to run while bypassing.
  **Identical enum to `vent/uo` `gtm`**, cross-validated against the live
  capture in `trace_unit.results.md`:
  `0 off, 1 low, 2 normal, 3 boost, 4 purge, 254 none, 255 max`.
- **`ect`** — `ExternalComfortTemperature` (°C). Outdoor threshold. **The app's
  UI caps this at 20 °C** — this is the limit the free-cooling automation is
  built to exceed.
- **`ict`** — `RoomComfortTemperature` (°C). Indoor comfort target.

All four are numeric on the wire (the enums are bidirectional `name↔int` maps;
the firmware uses the int, the app maps to a label for display).

## Status payload — `vent/sbs` (the real damper state)

`summerBypassStatusSchema = z.object({ op, pos, am })`:

```json
{ "op": <number>, "pos": <int>, "am": <int> }
```

- **`op`** — `z.number()`. Semantics unconfirmed by static analysis; most
  likely the damper open level / percentage. Verify against a live unit before
  relying on it.
- **`pos`** — `SummerBypassPosition` (**the damper-state field** that replaces
  the provisional `binary_sensor.vent_axia_bypass_open` heuristic):
  `0 Unknown, 1 Closing, 2 Closed, 3 Opening, 4 Open, 5 Modulated`
- **`am`** — `SummerBypassStatusMode` (which bypass mode is actually running):
  `0 Inactive, 1 Normal, 2 EveningFresh, 3 NightFresh, 4 AntiFrost,`
  `5 DiagnosticOpen, 6 ServiceMode, 7 BMSOverride`

### Derived signals for HA

- **Bypass damper open** ≈ `pos ∈ {3 Opening, 4 Open, 5 Modulated}`
  (fully open = `pos == 4`).
- **Bypass actively engaged** = `am != 0` (not Inactive).

## Hermes references (for re-verification)

- publish to `vent/sbc/wr`: fn **#25325** (`?anon_0_`, offset 0x0081e905)
- subscribe `vent/sbc` → `summerBypassConfigurationSchema`: fn **#25319**
- subscribe `vent/sbs` → `summerBypassStatusSchema`: fn **#25326**
- `summerBypassConfigurationSchema` definition: module fn **#31094** region
  (`mod/gtm/ect/ict` z.object, ~disasm line 1100195)
- `summerBypassStatusSchema` definition: ~disasm line 1103336
- `SummerBypassModes` enum: ~disasm line 1097740 (decomp `r5..r7` = ints `0..6`)
- `SummerBypassPosition` enum: ~disasm line 1103393
- `SummerBypassStatusMode` enum: ~disasm line 1103477
- `AirflowPreset` enum (gtm): ~decomp line 959727
