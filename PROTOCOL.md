# Vent-Axia Econiq — MQTT protocol reference

Full map of the MQTT wire protocol spoken between the **Vent-Axia Connect** app
and a Sentinel Econiq / Apex unit's built-in broker.

**Provenance:** reverse-engineered from the Connect Android app
**v7.2.2** (`uk.ventaxia.connect`), `assets/index.android.bundle` (Hermes
bytecode v96), disassembled + decompiled with
[`hermes-dec`](https://github.com/P1sec/hermes-dec). Static analysis only — no
live unit was probed for this document. Cross-checked against the live wire
capture in `tools/trace_unit.results.md` (Phase A) and the bypass decode in
`tools/bypass_decompile.results.md` (Phase B), which agree.

> ⚠️ Enum **values are numeric on the wire**; the app maps them to labels for
> display. Some payloads are a **bare scalar** (a single number/string/enum/
> bool), others are a **JSON object** with short keys — this is noted per topic.

## Conventions

- All topics are published under a per-unit root prefix, e.g.
  `<prefix>/vent/uo` (the integration discovers `<prefix>` at setup).
- **Read:** the app `subscribe`s a topic and validates the payload with a Zod
  schema (`parseSchema(payload, …Schema)` or `validateSchema`).
- **Write:** the app `publish`es `Buffer.from(JSON.stringify(value))` to the
  same topic **suffixed `/wr`** (e.g. `vent/cm` → `vent/cm/wr`). A few command
  topics publish to the bare topic (`vent/com`, `vent/pf…`) or send a literal
  string sentinel (`vent/filtertmr/reset` → `"Cleaned"`).
- Sensor value topics (`vent/afs/fm`, `io/*/val`, …) carry a **numeric string**
  validated by `floatSchema`/`intSchema`; the literals `"nan"`/`"-inf"` map to
  `null`.
- `<id>` in a topic means a runtime-built segment (filter id, sensor id, zone
  id, schedule slot) — the topic is assembled with string concat, so it does
  not appear as a literal in the bundle.

---

## `vent/*` — ventilation core

### vent/uo — user override (write)
Bare inline object (no schema). `connection.publish('vent/uo', …)`.

| key | type | values | meaning |
|----|----|----|----|
| `gtm` | enum | [AirflowPreset](#airflowpreset) | requested airflow preset |
| `treq` | string | `"HH:MM:SS"` | requested override duration |

Cancel: publish `{"gtm":254,"treq":"00:00:00"}` (254 = AirflowPreset.None). The
integration's `set_user_override` / `cancel_user_override` use this topic.

### vent/cor — current override status (read)
Schema `currentOverrideSchema`.

| key | type | values | meaning |
|----|----|----|----|
| `ot` | enum | [OverrideType](#overridetype) | **why** the unit is in its current state |
| `os` | number | L/s | override airflow setpoint ("override speed") |
| `trem` | datetime \| `""` | ISO local | timestamp; empty = none |
| `treq` | string | `"HH:MM:SS"` | requested duration |

> **Clarifies the integration:** `ot` is the full `OverrideType` enum, not a
> bucket. `ot=1` = `ZonalTimeSlot` (running a scheduled slot — what the
> integration treats as "idle/schedule-driven", `IDLE_OT`). The override-active
> values seen in Phase A — `9` = `UserOverride`, `10` = `SilentHours`, `16` =
> `Standby` — are now named. Phase A empirically found `trem` carries the
> override **start** timestamp (the app models it as time-remaining); trust the
> empirical reading.

### vent/caf — current airflow preset (read)
Schema `currentAirflowPresetSchema`.

| key | type | values | meaning |
|----|----|----|----|
| `ps` | enum | [AirflowPreset](#airflowpreset) | active airflow preset |
| `prop` | number | — | proportion / modulation of the preset |

### vent/daf (+ /wr) — default (idle) airflow preset
Schema `defaultAirflowSchema` = **bare** `z.enum(AirflowPreset)`.

### vent/cm (+ /wr) — control mode
Schema = **bare** `z.enum(`[ControlMode](#controlmode)`)` — Fixed / CV / CP.

### vent/maxaf — max settable airflow (read)
**Bare** `z.number()` — maximum settable volume in **L/s**.

### vent/com — commissioning test flow (write, bare topic)
Inline object (no `/wr`).

| key | type | values | meaning |
|----|----|----|----|
| `sup` | number | L/s | supply fan test flow |
| `ext` | number | L/s | extract fan test flow |
| `run` | number | 0 \| 1 | run / stop the test |

### vent/saq — system air quality (read)
**Bare** `z.enum(`[AirQuality](#airquality)`)` — Disabled / Good / Neutral / Bad.

### vent/pf… — preset-flow table rows (write, dynamic topic)
Topic `vent/pf`+`<id>`. Raw row value JSON; not a subscribe schema.

### vent/afc (+ /wr) — antifrost configuration
**Bare** `z.enum(`[AntifrostMode](#antifrostmode)`)`.

### vent/afstat — antifrost status (read)
Schema `antifrostStatusSchema`.

| key | type | values | meaning |
|----|----|----|----|
| `sta` | enum | [AntifrostStatusMode](#antifroststatusmode) | current antifrost state |
| `usa` | number | — | unknown (likely utilisation %) |
| `pwr` | number | — | unknown (likely preheater power W) |

### vent/afs/* and vent/afe/* — supply / extract fan sensors (read)
`afs` = **supply** fan, `afe` = **extract** fan. Each validated with
`floatSchema` (or `intSchema` for `dr`).

| suffix | type / unit | meaning |
|----|----|----|
| `fm` | float, **L/s** | measured airflow (×3.6 → m³/h; see v0.2.3) |
| `fd` | float, **L/s** | demanded / target airflow |
| `rpm` | float, rpm | motor speed |
| `pwr` | float, W | motor power |
| `dr` | int | motor run-time counter |

---

## `vent/sbc`, `vent/sbs` — summer bypass

Full detail in `tools/bypass_decompile.results.md`.

### vent/sbc (+ /wr) — summer-bypass configuration
Schema `summerBypassConfigurationSchema`.

| key | type | values | meaning |
|----|----|----|----|
| `mod` | enum | [SummerBypassModes](#summerbypassmodes) | bypass mode |
| `gtm` | enum | [AirflowPreset](#airflowpreset) | fan speed while bypassing |
| `ect` | number | °C | ExternalComfortTemperature (outdoor threshold; **app UI caps at 20 °C**) |
| `ict` | number | °C | RoomComfortTemperature (indoor target) |

### vent/sbs — summer-bypass status / damper (read)
Schema `summerBypassStatusSchema`.

| key | type | values | meaning |
|----|----|----|----|
| `op` | number | — | open level / % (unconfirmed) |
| `pos` | enum | [SummerBypassPosition](#summerbypassposition) | **damper position** (real bypass-open signal) |
| `am` | enum | [SummerBypassStatusMode](#summerbypassstatusmode) | active bypass mode |

> Replaces the provisional `binary_sensor.vent_axia_bypass_open` heuristic:
> damper open ≈ `pos ∈ {3,4,5}` (Opening/Open/Modulated); actively engaged =
> `am != 0`.

---

## `vent/filter*` — filters

| topic | dir | schema / payload | meaning |
|----|----|----|----|
| `vent/filter1/typ`, `vent/filter2/typ` (+ `/wr`) | r/w | `filterTypeSchema` = bare string (`""`→N/A) | filter type / part code |
| `vent/filtertmr/int` (+ `/wr`) | r/w | `filterChangeIntervalSchema` = bare number (days) | filter-change interval |
| `vent/filtertmr/last` | r | `lastFilterChangeSchema` = ISO datetime \| `0`→null | last filter change |
| `vent/filtertmr/remain` | r | number (also `vent/<id>/lr` float per filter) | remaining filter life |
| `vent/filtertmr/reset` | w | publishes literal `"Cleaned"` | reset filter timer |

---

## `io/*` — onboard IO sensors

| topic | dir | schema / payload | meaning |
|----|----|----|----|
| `io/eco2/val` | r | `floatSchema` | extract (indoor) CO₂ |
| `io/ico2/val` | r | `floatSchema` | intake (outdoor) CO₂ |
| `io/erh/val` | r | `floatSchema` | extract (indoor) RH % |
| `io/irh/val` | r | `floatSchema` | intake (outdoor) RH % |
| `io/eco2/conf` (+ `/wr`) | r/w | `extractCO2ConfigurationSchema` `{th_l, th_h, gtm:AirflowPreset}` | CO₂ low/high thresholds + triggered preset |
| `io/erh/conf` (+ `/wr`) | r/w | `extractHumidityConfigurationSchema` `{th, are:bool, rre:bool, rror:int 0..999, gtm:AirflowPreset}` | RH threshold + abs/rel response + preset |

> Confirms the v0.2.2 humidity-label fix (`irh`=outdoor intake, `erh`=indoor
> extract) and the v0.2.3 airflow-unit fix.

---

## Port configuration (analog / digital / 0-10 V / relay / virtual)

Per-port config objects (carried on port topics / `…/conf` writes).

| schema | fields |
|----|----|
| `analogPortConfigurationSchema` | `name:str, zone:num, typ:`[SensorType](#sensortype)`, c0:num, c10:num` (calibration low/high) |
| `analogPortValueSchema` | bare string→float (`"nan"`→null) |
| `digitalPortConfigurationSchema` | `name:str, zone:num, mod:`[InputModes](#inputmodes)`, pol:`[Polarity](#polarity)`, gtm:AirflowPreset, dly:int 0..5940, or:int 0..5940, cm:bool, se?:bool, cd?:bool` |
| `digitalPortValueSchema` | bare boolean |
| `output010VConfigurationSchema` | `name:str, zone:num, mod:`[OutputType](#outputtype) |
| `relayPortConfigurationSchema` | `name:str, zone:num, mod:`[RelayMode](#relaymode) |
| `virtualInputSchema` | `name:str, zone:num, typ:`[VirtualSensorTypes](#virtualsensortypes) — on `bms/vi/<id>/conf` (+ `/wr`) |

`se` / `cd` digital-port flags: meaning unresolved.

---

## `sn/*`, `zone/*` — paired sensors & zones

| topic | dir | schema / payload | meaning |
|----|----|----|----|
| `sn/active` | r | `activeSensorsSchema` = bare int **bitmask** | active sensor indices (bit b → sensor b+1) |
| `sn/<id>/conf` (+ `/wr`) | r/w | `sensorConfigurationSchema` `{name, zone}` | per-sensor name + zone |
| `sn/<id>/info` | r | `sensorInformationSchema` `{fwv, dt:`[DeviceType](#devicetype)`, ht:`[HardwareType](#hardwaretype)`}` | sensor firmware / device / hardware type |
| `sn/<id>/sw` | r | `sensorSwitchStateSchema` = bare bool | switch state |
| `sn/pairing` (+ `/wr`) | r/w | `sensorPairingSchema` = bare bool | pairing-mode active |
| `sn/identify` | w | `{addr, c1:"FFFF00", c2:"FF00FF", t:180, en}` | flash a sensor's LED to locate it |
| `sn/<id>/remove` | w | literal `"unpairMe"` | unpair a sensor |
| `zone/active` | r | `activeZonesSchema` = bare int **bitmask** | active zone indices |
| `zone/<id>/conf` (+ `/wr`) | r/w | `zoneConfigurationSchema` (below) | per-zone configuration |

`zoneConfigurationSchema`: `name:str, typ:`[ZoneType](#zonetype)`, icon:num(ZoneIcon),
gtm:num, t_sp:num (temp setpoint), rh_th:num, rh_are:bool, rh_rre:bool, or:num
(override run time), co2_l/co2_h:num, voc_l/voc_h:num`.

---

## `mdet/*`, `sysdet/*` — model / commissioning / system details

| topic | dir | schema / payload | meaning |
|----|----|----|----|
| `mdet/moddet` | r | `modelDetailsSchema` `{sn:str, mc:num, mn:str, dom:date, fwv:num}` | model details (serial, code, name, date-of-manufacture, fw) |
| `mdet/name` (+ `/wr`) | r/w | bare string | unit name |
| `mdet/compin` (+ `/wr`) | r/w | bare number | commissioner PIN |
| `mdet/hand` (+ `/wr`) | r/w | `handingSchema` = bare enum [Handing](#handing) | unit handing (Left/Right) |
| `mdet/rtc` (+ `/wr`) | r/w | `dateTimeSchema` = bare ISO datetime | real-time clock |
| `mdet/runt` | r | bare int | runtime |
| `mdet/faults`, `mdet/warns`, `mdet/noti` | r | bare int | fault / warning / notification code or bitfield (label map elsewhere) |
| `mdet/dlog` | r | `datalogSchema` `{tot, pf1..pf4, nrg}` | datalog counters + energy |
| `mdet/fwsta` | r | `firmwareUpdateStatusSchema` `{addr:num, sta:`[FirmwareUpdateState](#firmwareupdatestate)`}` | firmware-update progress |
| `mdet/wifi/sta` | r | `wiFiStatusSchema` `{ipaddr, rssi, mode:WifiMode, ssid≤32}` | Wi-Fi status |
| `mdet/svctmr/int` (+ `/wr`) | r/w | `intSchema` | service-timer interval |
| `mdet/svctmr/last` | r | `dateTimeSchema` | last service |
| `mdet/svctmr/reset` | w | command | reset service timer |
| `mdet/comdet/cn` (+ `/wr`) | r/w | string ≤16 | commissioning company name |
| `mdet/comdet/addr` (+ `/wr`) | r/w | string ≤100 | commissioning address |
| `mdet/comdet/pn` (+ `/wr`) | r/w | string ≤16 (digits/space/`+`/`-`) | commissioning phone |
| `mdet/comdet/email` (+ `/wr`) | r/w | email ≤100 \| `""` | commissioning email |
| `mdet/comdet/cd` (+ `/wr`) | r/w | `dateSchema` = ISO date \| `""`→null | commissioning date |
| `sysdet/name`, `sysdet/svctmr/int`, `sysdet/svctmr/remain` | r | cached JSON/CSV export (no Zod parse) | system-level name / service timer |

`WifiMode`: `1 AccessPoint, 2 Station`.

> `settings/{bms,graphs,notifications,schedules}` and `system/settings` are **app
> UI routes / export wrappers**, not wire topics. No `error/message` MQTT topic
> exists in this build (the literal is Node `assert` internals only).

---

## `bms/*` — building-management-system interface

| topic | dir | schema / payload | meaning |
|----|----|----|----|
| `bms/netc` (+ `/wr`) | r/w | `bmsNetworkConfigurationSchema` `{prot:`[BMSProtocol](#bmsprotocol)`, baud:4800..115200, par:`[BMSParity](#bmsparity)`, addr:int 0..255}` | BMS serial network config |
| `bms/nets` | r | `bmsNetworkStatusSchema` `{conn:bool, traf:bool}` | BMS connected / traffic |
| `bms/vi/<id>/conf` (+ `/wr`) | r/w | `virtualInputSchema` `{name, zone, typ:VirtualSensorTypes}` | BMS virtual input |

---

## `timw/<id>`, `timd/<id>` — ventilation schedules

| topic | dir | schema / payload | meaning |
|----|----|----|----|
| `timw/<id>` (+ `/wr`) | r/w | `timedWeeklyRecurringVentilationSchema` `{en:bool, zone:num, gtm:AirflowPreset, sh:bool, st:"HH:MM", et:"HH:MM", da:int 0..127 (day bitmask)}` | weekly recurring schedule slot (≤50) |
| `timd/<id>` (+ `/wr`) | r/w | `timedByDateVentilationSchema` `{en:bool, gtm:AirflowPreset, zone:num, sh:bool, sd:date, ed:date}` | by-date / holiday schedule slot (≤10) |

`sh` flag meaning unresolved.

---

# Enum appendix

### AirflowPreset
Used by `gtm`/`ps` everywhere. **Matches the live-captured `MODE_TO_GTM`.**
`0 Off, 1 Low, 2 Normal, 3 Boost, 4 Purge, 254 None, 255 Max`

### OverrideType
`vent/cor.ot`. `0 None, 1 ZonalTimeSlot, 2 ExtractCo2, 3 ExtractRh, 4 ZonalCo2,
5 ZonalVoc, 6 ZonalRh, 7 SummerBypass, 8 ZonalBoolean, 9 UserOverride,
10 SilentHours, 11 AntiFrostModifier, 12 DamperSpeedLimit,
13 CleanFilterCalibration, 14 Shutdown, 15 Commissioning, 16 Standby,
17 DiagnosticMode, 18 HeatingFail, 19 ControlledMode, 20 NightCool, 21 NvSmart,
22 Testing, 23 ZonalPure0_10v, 24 SystemDisabled, 25 ThermalOverride,
26 CoolerEnabled, 27 AcOverride, 28 ScienceOverride`

### ControlMode
`vent/cm`. `0 Fixed, 1 CV (constant volume), 2 CP (constant pressure)`

### AirQuality
`vent/saq`. `0 Disabled, 1 Good, 2 Neutral, 3 Bad`

### SummerBypassModes
`vent/sbc.mod`. `0 Off, 1 Normal, 2 EveningFresh, 3 NightFresh,
4 NormalModulation, 5 EveningFreshModulation, 6 NightFreshModulation`

### SummerBypassPosition
`vent/sbs.pos`. `0 Unknown, 1 Closing, 2 Closed, 3 Opening, 4 Open, 5 Modulated`

### SummerBypassStatusMode
`vent/sbs.am`. `0 Inactive, 1 Normal, 2 EveningFresh, 3 NightFresh, 4 AntiFrost,
5 DiagnosticOpen, 6 ServiceMode, 7 BMSOverride`

### AntifrostMode
`vent/afc`. `0 AirflowImbalance, 1 Bypass, 2 PreHeaterBalanced,
3 PreHeaterImbalanced` (a near-identical `AntiFrostMode` enum exists for an
unused `antifrostConfigModeSchema`; the wire one is this).

### AntifrostStatusMode
`vent/afstat.sta`. `0 Inactive, 1 AirflowImbalance, 2 Bypass,
3 PreHeaterBalanced, 4 PreHeaterImbalanced`

### SensorType
`analogPortConfigurationSchema.typ`. `0 None, 1 RH, 2 CO2, 3 TemperatureInside,
4 TemperatureOutside, 5 Pure, 6 Spare, 7 VOC, 8 TemperatureSetPoint`

### InputModes
`digitalPortConfigurationSchema.mod`. `0 None, 1 Continuous, 2 MomentaryPIR,
3 MomentarySwitch, 4 HVACInterlocks, 5 FireAlarm, 6 SystemEnable,
7 ExternalAcNvhr, 8 CoolingOverride, 9 HeatingOverride, 10 ScienceModeOn`

### Polarity
`digitalPortConfigurationSchema.pol`. `0 OC (open circuit / NO),
1 SC (short circuit / NC)`

### OutputType
`output010VConfigurationSchema.mod`. `0 Disabled, 1 ZonalDamper, 2 SummerBypass,
3 RecircDamper, 4 FreshDamper, 5 ExhaustDamper, 6 HRDamper, 7 SupplyMotor,
8 ExtractMotor, 9 HeatingCoil, 10 CoolingCoil, 11 SummerRelief, 12 AllYearFresh`

### RelayMode
`relayPortConfigurationSchema.mod`. `0 Disabled, 1 HeaterEnabled, 2 CoolerEnabled,
3 AttentionVentilation, 4 ControlledHeater, 5 ControlledCooler,
6 MechanicalVentilationActive`

### VirtualSensorTypes
`virtualInputSchema.typ`. `0 None, 1 Temperature, 2 RH, 3 CO2, 4 VOC`

### ZoneType
`zoneConfigurationSchema.typ`. `0 Supply, 1 Extract`

### Handing
`mdet/hand`. `0 Left, 1 Right`

### BMSProtocol
`bms/netc.prot`. `0 None, 1 Modbus, 2 Bacnet`

### BMSParity
`bms/netc.par`. `0 None, 1 Odd, 2 Even`

### FirmwareUpdateState
`mdet/fwsta.sta`. `0 Idle, 1 Recording, 2 Validating, 3 SendingApply,
4 ApplyValidating, 5 ReadyToApply, 6 UpdatePreparing, 7 SendingBinary,
8 Applying, 9 UpdateCompleted, 10 Fault`

### DeviceType
`sn/<id>/info.dt`. `0 NotSet, 1 MultiZoneControlUnit, 2 FanControlUnitSlaveOnly,
3 FanControlUnit, 4 InternalTemperatureHumiditySensor,
5 ExternalTemperatureHumiditySensor, 6 InternalCo2Sensor, 7 InternalEnvSensor,
8 AlarmInterfaceModule, 9 InternalPowereempHumSensor, 10 MEVControlUnit,
11 MEVControlUnitStd, 12 SSUBatteryPoweredSensor, 13 SSUMainsPoweredSensor,
14 PIR, 15 MEVControlREOnlyEC1, 16 MEVControlREOnlyEC3, 17 SentinelApex,
18 SentinelKineticAdvance, 19 MvhrHmi, 20 NvSmartHmi, 21 Esp32IvConnect,
22 Esp32Mvhr, 23 Esp32NvSmart, 24 NvSmart, 25 RfBridge, 26 DiagSoftware,
27 FanControlUnitTwinSlaveOnly, 28 FanControlUnitTwin, 29 PreheaterIO,
30 SMoveConnect, 31 CoolingUnit, 32 TSeriesRemoteSwitch, 33 TSeriesFanControlUnit`

### HardwareType
`sn/<id>/info.ht`. `0 NotSet, 1 MultiZoneControlUnit, 2 FanControlUnit,
3 Sensors, 4 MEV, 5 SentinelKinetic, 6 Esp32IvConnect, 7 SentinelKineticRA2L1,
8 SentinelApex, 9 SentinelKineticAdvanceRA2L1, 10 MvhrHmi, 11 NvhrHmi,
12 RfBridge, 13 DiagSoftware, 14 Esp32Mvhr, 15 Esp32NvSmart,
16 MultiZoneControlUnitSTM32WL, 17 FanControlUnitSTM32WL, 18 SensorsSTM32WL,
19 PreheaterIO, 20 SMoveConnect, 21 CoolingUnit, 22 TSeriesRemote,
23 TSeriesFanControlUnit`

---

*Generated 2026-06-23 from app v7.2.2. Fields marked "unknown/unconfirmed" were
not resolvable by static analysis — verify against a live unit before relying on
them.*
