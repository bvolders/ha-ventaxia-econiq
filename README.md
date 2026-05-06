# Vent-Axia Econiq — Home Assistant integration

A local-push Home Assistant integration for the **Vent-Axia Sentinel Econiq 600** MVHR ventilation unit, talking directly to the unit's built-in MQTT broker over TLS-PSK.

> **Status: v0.1.0 — read-only.** All telemetry sensors work. Control entities (set fan mode, summer bypass, BBQ-bypass timer) are planned for v0.2 once the `vent/uo` write payload is fully nailed down.

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

## Limitations

- **Read-only in v0.1.** The write topics (`vent/uo` for fan mode, `vent/sbc/wr` for summer bypass, etc.) are mapped from app reverse engineering but the JSON payload format hasn't been bench-tested yet. Coming in v0.2.
- **Sentinel Econiq 600 is the only tested model.** The Sentinel Kinetic Advance S is a sibling product but uses a different protocol entirely — use [JosyBan/ventaxia_ha](https://github.com/JosyBan/ventaxia_ha) for that.
- **Some sensors stay "Unavailable" until first state change.** `Operating override`, `Faults`, `Warnings`, and `Current airflow program` only publish when their state changes (not periodically), so they appear as Unavailable on first start. They populate as soon as the unit publishes any update — usually within a minute, definitely after the first mode toggle.

## Acknowledgements

Reverse engineering footprints we built on:
- [JosyBan/ventaxiaiot](https://pypi.org/project/ventaxiaiot/) — different protocol, but useful for understanding the Vent-Axia design language
- [HA forum: Sentinel Econiq Modbus/RS485 thread](https://community.home-assistant.io/t/vent-axia-sentinel-econiq-modbus-rs485-integration/993007) — official Modbus register map (alternative protocol path on the same firmware)

## License

MIT — see [LICENSE](LICENSE).
