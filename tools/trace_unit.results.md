# Phase A trace + probe — partial findings

**Status:** INCOMPLETE. Capture was interrupted when the unit's MQTT broker hung
during the session (TCP 8883 + 80 + 443 all became unreachable; HA sensors went
Unavailable). Recovery is a unit power-cycle. To resume, repeat the active
probe (`tools/probe_uo_sweep.py`) once the unit is back online.

## What we observed

### Connectivity-model finding (important)

The unit's broker enforces something close to single-session-per-identity.
When the user opened the Vent-Axia Connect app, our `trace_unit.py` session
silently stopped receiving messages even though paho still believed it was
connected. This means:

- **Passive observation while the user drives the Connect app does NOT work.**
  As soon as the app connects, our trace gets booted (or the app's writes are
  routed somewhere we don't see).
- The fix is **active probing** with the integration's own credentials, ideally
  with HA temporarily detached (or accepting that HA will briefly disconnect).
  See `tools/probe_uo_sweep.py`.

### Idle / no-override echo

```
vent/cor: {"ot":1,"os":130,"trem":"","treq":"00:00:00"}
```

Captured at session start, when the unit was running its baseline schedule.
`trem=""` (empty string, not `"00:00:00"`) seems to mean "no countdown active".
`treq="00:00:00"` matches.

**Tentatively:** `IDLE_OT_OS = (1, 130)` — but this is one observation, and the
unit also publishes (1, 130) when actively in Low mode following a schedule.
We may need more data to distinguish "idle" from "schedule-running-Low".

### Mode-to-(ot, os) map

**NOT YET CAPTURED.** The active probe sweep (`tools/probe_uo_sweep.py`) was
written but never ran successfully — TCP to 10.1.5.33:8883 timed out at the
moment we tried. Re-run the probe after the unit power-cycle.

### Cancel mechanism

**NOT YET CAPTURED.** The Hermes-bytecode evidence still says `gtm=254`
("None") is the canonical cancel value, but this is unverified on-the-wire.
The probe sweep includes 254 in its sweep list.

## Resuming Phase A

Once the unit is back on the network:

1. Confirm reachability: `ssh bert@blackbox '/var/packages/ContainerManager/target/usr/bin/docker exec homeassistant python3 -c "import socket;s=socket.socket();s.settimeout(3);s.connect((\"10.1.5.33\",8883));print(\"ok\")"'`
2. Source credentials from HA's storage (see `tools/probe_uo_sweep.py` docstring).
3. Run the sweep: `python3 /tmp/probe_uo_sweep.py` from inside the HA container with the env vars set.
4. Curate the printed `SWEEP SUMMARY` table into the "Mode → wire mapping" section below.
5. Update `custom_components/ventaxia_econiq/const.py`'s `OT_OS_TO_MODE`,
   `IDLE_OT_OS`, and `CANCEL_PAYLOAD` from these values.

## Mode → wire mapping (TO BE FILLED AFTER RESUMING)

| gtm | label | vent/cor echo (ot, os) | supply RPM range | extract RPM range | notes |
|---|---|---|---|---|---|
| 0   | off    | TBD | TBD | TBD | |
| 1   | low    | (1, 130)? | TBD | TBD | possibly same as idle |
| 2   | normal | TBD | TBD | TBD | |
| 3   | boost  | TBD | TBD | TBD | memory says (9, 129) — confirm |
| 4   | purge  | TBD | TBD | TBD | |
| 254 | none   | TBD | TBD | TBD | likely cancel |
| 255 | max    | TBD | TBD | TBD | |
