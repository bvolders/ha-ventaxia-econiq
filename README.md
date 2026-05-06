# Vent-Axia Econiq — Home Assistant integration

A local-push Home Assistant integration for the **Vent-Axia Sentinel Econiq 600** MVHR ventilation unit, talking directly to the unit's built-in MQTT broker over TLS-PSK. No cloud, no broker, no polling — when the unit publishes a value, HA gets it within milliseconds.

> **Status: v0.1.0 — read-only.** All 17 telemetry sensors live and updating. Control entities (fan-mode select, summer bypass, BBQ-bypass timer) are next-up for v0.2 — see [Roadmap](#roadmap).

[![hassfest validation](https://github.com/bvolders/ha-ventaxia-econiq/actions/workflows/validate.yml/badge.svg)](https://github.com/bvolders/ha-ventaxia-econiq/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## Why this exists

The [JosyBan/ventaxia_ha](https://github.com/JosyBan/ventaxia_ha) integration was built for the **Sentinel Kinetic Advance S**, which uses a custom JSON-line protocol over a Vent-Axia-proprietary TLS-PSK port (47811). The Econiq family looks like the same product line on the surface but actually speaks **standard MQTT 3.1.1 over TLS-PSK on port 8883** with a completely different topic tree (`BZPKB-XXXXX/vent/...`, `BZPKB-XXXXX/io/t1..t4`, etc.). The two integrations cannot share code.

This integration:
- Connects to the unit's MQTT broker via plain `paho-mqtt` with a TLS-PSK SSL context (TLS 1.2 only, `PSK-AES128-CBC-SHA`)
- Auto-discovers the device's serial-style topic prefix on first connect
- Subscribes to `<prefix>/#` and maps every published topic to the appropriate HA entity

## Sensors

| Entity | Topic | Unit / Class |
|---|---|---|
| Outdoor intake temperature | `io/t1` | °C — temperature |
| Supply air temperature     | `io/t2` | °C — temperature |
| Extract air temperature    | `io/t3` | °C — temperature |
| Exhaust air temperature    | `io/t4` | °C — temperature |
| Indoor humidity            | `io/irh/val` | % — humidity |
| Extract humidity           | `io/erh/val` | % — humidity |
| Indoor CO₂ (if installed)  | `io/eco2/val` | ppm — CO₂ |
| Supply airflow             | `vent/afs/fm` | m³/h — volume_flow_rate |
| Extract airflow            | `vent/afe/fm` | m³/h |
| Supply / extract fan RPM   | `vent/{afs,afe}/rpm` | rpm |
| Supply / extract fan PWM   | `vent/{afs,afe}/pwm` | % |
| Supply / extract fan power | `vent/{afs,afe}/pwr` | W — power |
| Total power                | `mdet/pwr` | W |
| Faults / Warnings counts   | `mdet/{faults,warns}` | int |
| WiFi signal                | `mdet/wifi/sta` | dBm |
| Operating override         | `vent/cor` | (state-attrs JSON) |
| Current airflow program    | `vent/caf` | (state-attrs JSON) |
| **Heat recovery efficiency** | computed: (T2−T1)/(T3−T1)×100 | % |

## Installation

### HACS (recommended)

1. In HACS → ⋮ → **Custom repositories**
2. Add `https://github.com/bvolders/ha-ventaxia-econiq` as an *Integration*
3. Install **Vent-Axia Econiq**, restart Home Assistant
4. **Settings → Devices & Services → + Add Integration → "Vent-Axia Econiq"**
5. Fill in the four fields (see *Getting credentials* below)

### Manual

Drop `custom_components/ventaxia_econiq/` into your HA `config/custom_components/` and restart.

## Getting credentials

The integration needs four values:

| Field | Where to get it |
|---|---|
| Host | The unit's LAN IP (find it in your router's DHCP table or your DNS) |
| Port | **`8883`** (override the default `47811` shown in the form) |
| TLS-PSK identity | 32-char hex string from the Vent-Axia Connect app's local storage |
| TLS-PSK key | 16-char hex string from the same place |

The two TLS-PSK values are negotiated when you first pair your phone to the unit (8-second hold on the unit's MENU button → blue LED → BLE handshake) and then stored on both sides. They are **not printed on a sticker** anywhere on the unit (unlike the older Sentinel Kinetic Advance S WiFi modules).

### Recipe for iOS (encrypted Finder backup)

1. Plug iPhone into Mac. Finder → device → tick **"Encrypt local backup"**, set a password, **Back Up Now**. (Encryption is required so app data is preserved in the backup.)
2. From your Mac terminal:
   ```bash
   python3 -m venv /tmp/iosbk && source /tmp/iosbk/bin/activate
   pip install iphone_backup_decrypt
   read -rsp 'Backup password: ' BACKUP_PASSWORD; echo
   export BACKUP_PASSWORD
   python3 - <<'PY'
   import os, sqlite3, json
   from pathlib import Path
   from iphone_backup_decrypt import EncryptedBackup
   bk = next(Path("~/Library/Application Support/MobileSync/Backup").expanduser().iterdir())
   backup = EncryptedBackup(backup_directory=str(bk), passphrase=os.environ["BACKUP_PASSWORD"])
   backup.test_decryption()
   backup.extract_file(
       relative_path="Documents/SQLite/devices.db",
       domain_like="AppDomain-uk.ventaxia.connect",
       output_filename="/tmp/devices.db",
   )
   for row in sqlite3.connect("/tmp/devices.db").execute("SELECT id, options FROM devices"):
       opts = json.loads(row[1])
       print(f"wifi_device_id (used as Identity in this integration's config? NO):")
       print(f"  Device id (app-local UUID, NOT used here): {row[0]}")
       print(f"  Identity:           {opts['tcpTlsIdentity']}")
       print(f"  PSK key:            {opts['tcpTlsKey']}")
       print(f"  Installer PIN:      {opts['pinCode']}")
   PY
   unset BACKUP_PASSWORD
   ```
3. Plug those values into HA's Add Integration form.

### Recipe for Android

Easier — `adb backup -f vent.ab uk.ventaxia.connect` then unpack with `abe.jar`. The same `Documents/SQLite/devices.db` is in the resulting tarball. (Older OS versions only — newer Android may have `allowBackup=false` in the app, in which case decompile the APK with `jadx` and look for the credential read.)

## Architecture notes

- **Why TLS 1.2 only.** The unit's firmware advertises `PSK-AES128-CBC-SHA` and silently RSTs the TCP connection mid-handshake if the client sends a TLS 1.3 ClientHello. OpenSSL 3.x defaults to negotiating up to 1.3, so we explicitly pin both `minimum_version` and `maximum_version` to TLS 1.2 in the SSL context.
- **Why hex-decode the PSK.** The app stores the PSK as a hex string. The actual PSK *bytes* are the hex-decoded form, not the ASCII-encoded form of the hex string. Sending the ASCII form fails MAC verification with "bad record mac" (TLS alert 20). The integration does `bytes.fromhex(psk_hex)` before passing to `set_psk_client_callback`.
- **The MQTT topic prefix.** Each unit publishes everything under a single root segment derived from its serial (e.g., `BZPKB-7588F`). The integration auto-discovers this on first connect by subscribing to `#` and taking the first segment of any incoming publish.

## Roadmap

### v0.2 — Control entities

The write-side topic and payload schema are already mapped (Hermes bytecode disassembly of the official Android app's React-Native bundle):

- **Topic**: `<prefix>/vent/uo` (user override)
- **Payload**: `{"gtm": <int>, "treq": "HH:MM:SS"}`
- **Mode integers** (the `AirflowPreset` enum extracted from app function `31116`):
  | `gtm` | Mode |
  |---|---|
  | 0 | Off |
  | 1 | Low |
  | 2 | Normal |
  | 3 | Boost |
  | 4 | Purge |
  | 254 | None |
  | 255 | Max |

Once bench-tested on a live unit, v0.2 will ship:

- A `select` entity with the seven modes
- A `number` entity for override duration (15-minute increments matching the unit's UI)
- A **"BBQ bypass" button** that one-taps `{"gtm": 0, "treq": "01:00:00"}` for 1 hour of total intake silence (e.g., when neighbours barbecue and the F7 filter can't keep up with smoke)
- A `select` for summer-bypass mode via `vent/sbc/wr`

### v0.3 — In-HA BLE pairing (eliminates the manual credential extraction)

The credentials lookup ([below](#getting-credentials)) is the rough edge of v0.1. The Vent-Axia Connect app obtains them automatically by completing a BLE handshake when the user holds the unit's MENU button for 8 seconds. v0.3 plans to replicate that flow inside the integration:

1. User clicks "Pair new device" in HA → Add Integration
2. Integration scans BLE (via an [ESPHome `bluetooth_proxy`](https://esphome.io/components/bluetooth_proxy.html) or host-side adapter)
3. User holds MENU 8 s on the unit (just like with the official app)
4. Integration completes the handshake, captures the TLS-PSK creds, stores them in the config entry
5. Done — no terminal commands, no SQLite digging

Requires reverse-engineering the BLE GATT service the Connect app uses for pairing (different from the MQTT-over-TLS-PSK control channel). Best done with `nRF Connect for Mobile` on a phone next to the unit during a fresh re-pair.

### Future

- Sentinel Econiq 375 / 450 should work identically (same firmware family) — just need confirmation
- Modbus/RS485 backup path documented in [Architecture notes](#architecture-notes) — not implemented since MQTT covers everything, but available if the unit's WiFi ever fails

## Limitations

- **Read-only in v0.1.** Control coming in v0.2 (see Roadmap above).
- **Sentinel Econiq 600 is the only tested model.** The Sentinel Kinetic Advance S is a sibling product but uses a different protocol entirely — use [JosyBan/ventaxia_ha](https://github.com/JosyBan/ventaxia_ha) for that.
- **Some sensors stay "Unavailable" until first state change.** `Operating override`, `Faults`, `Warnings`, and `Current airflow program` only publish when their state changes (not periodically), so they appear as Unavailable on first start. They populate as soon as the unit publishes any update — usually within a minute, definitely after the first mode toggle.
- **Credential extraction is currently manual.** v0.3's BLE pairing flow eliminates this.

## Architecture notes — what we learned

These are non-obvious findings from reverse-engineering the unit's protocol that took surprising effort to nail down. Documented here so future contributors don't re-tread the path:

### TLS-PSK setup

- The unit only accepts `PSK-AES128-CBC-SHA` cipher.
- TLS 1.2 only — advertising 1.3 in the ClientHello (OpenSSL 3.x default) makes the unit **silently RST mid-handshake**. Pin both `minimum_version` and `maximum_version` to `TLSv1_2`.
- The PSK is stored as a **hex string** in the app database. The actual PSK *bytes* are the hex-decoded form, NOT the ASCII-encoded form of the hex string. ASCII-encoded yields TLS alert 20 (`bad record mac`).

### Wire protocol

- It's **standard MQTT 3.1.1**, not the custom JSON-line protocol the related [JosyBan/ventaxiaiot](https://pypi.org/project/ventaxiaiot/) library uses for the Sentinel Kinetic Advance S. Use a normal MQTT client (`paho-mqtt`).
- MQTT 5.0 is rejected with CONNACK rc=1 (unsupported protocol version).
- The unit's broker firewalls `/wr` and `/uo` topic publishes from being delivered to other subscribers — it's an "input-only" channel pattern. So you can't sniff the official app's commands by subscribing as a peer; you have to infer write payloads from the *echo* the unit publishes back to read-side topics like `vent/cor`.

### Topic prefix discovery

- Each unit publishes everything under a single root segment derived from its firmware serial — e.g. `BZPKB-7588F`. NOT the device UUID stored in the iOS app (which we initially tried; it never appears on the wire).
- The integration auto-discovers this on first connect by subscribing to `#` and taking the first segment of any incoming publish.

### Modbus alternative

The same firmware also exposes RS485 Modbus on the unit's `0V/B/A/5V` terminals (115200 8N1, slave ID 2) — see [HA forum thread](https://community.home-assistant.io/t/vent-axia-sentinel-econiq-modbus-rs485-integration/993007) for the official register map. We chose MQTT because: (a) no extra hardware (RS485 dongle) needed, (b) push semantics, (c) wider data surface than the Modbus register map exposes.

## Acknowledgements

Reverse engineering footprints we built on:
- [JosyBan/ventaxiaiot](https://pypi.org/project/ventaxiaiot/) and [JosyBan/ventaxia_ha](https://github.com/JosyBan/ventaxia_ha) — different protocol, but useful for understanding the Vent-Axia design language
- [HA forum: Sentinel Econiq Modbus/RS485 thread](https://community.home-assistant.io/t/vent-axia-sentinel-econiq-modbus-rs485-integration/993007) — official Modbus register map (alternative protocol path on the same firmware)
- [hermes-dec](https://github.com/P1sec/hermes-dec) — Hermes bytecode parser used to extract the `AirflowPreset` enum from the official app
- [iphone_backup_decrypt](https://pypi.org/project/iphone-backup-decrypt/) — encrypted iOS backup decryption library used by the credential-extraction recipe

## License

MIT — see [LICENSE](LICENSE).
