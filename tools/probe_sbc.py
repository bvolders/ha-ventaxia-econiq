#!/usr/bin/env python3
"""Read-only capture of the summer-bypass topics (Phase B validation).

PURELY PASSIVE — this never publishes. It subscribes to <prefix>/vent/sbc
(config echo) and <prefix>/vent/sbs (status / damper) and prints each payload
raw plus decoded against the schema reverse-engineered from the Connect app
(see PROTOCOL.md / tools/bypass_decompile.results.md), so we can confirm the
field names and types before any write path is trusted.

Run a single short-lived client (the unit's broker has a small connection
budget — stop HA's integration first if the broker starts hanging).

Usage:
    export VAE_HOST=...
    export VAE_PORT=8883
    export VAE_IDENTITY=...
    export VAE_PSK=...
    export VAE_PREFIX=...           # e.g. BZPKB-7588F
    python3 tools/probe_sbc.py [seconds]   # default 90s

Tip: open the Vent-Axia Connect app and toggle the bypass settings while this
runs — you'll see the vent/sbc echo change, which confirms the write payload
shape, and vent/sbs report the damper moving (pos: closing→closed / opening→open).
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import threading
import time
from datetime import datetime

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

# Decoded enums (must match const.py / PROTOCOL.md).
BYPASS_MODE = {
    0: "Off", 1: "Normal", 2: "EveningFresh", 3: "NightFresh",
    4: "NormalModulation", 5: "EveningFreshModulation", 6: "NightFreshModulation",
}
AIRFLOW_PRESET = {0: "off", 1: "low", 2: "normal", 3: "boost", 4: "purge", 254: "none", 255: "max"}
BYPASS_POSITION = {0: "Unknown", 1: "Closing", 2: "Closed", 3: "Opening", 4: "Open", 5: "Modulated"}
BYPASS_STATUS_MODE = {
    0: "Inactive", 1: "Normal", 2: "EveningFresh", 3: "NightFresh",
    4: "AntiFrost", 5: "DiagnosticOpen", 6: "ServiceMode", 7: "BMSOverride",
}


def _build_psk_context(identity: str, psk_hex: str) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers("PSK-AES128-CBC-SHA")
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    psk_bytes = bytes.fromhex(psk_hex)
    ctx.set_psk_client_callback(lambda hint: (identity, psk_bytes))
    return ctx


def _decode_config(d: dict) -> str:
    mod = d.get("mod")
    gtm = d.get("gtm")
    return (
        f"mod={mod} ({BYPASS_MODE.get(mod, '??')}), "
        f"gtm={gtm} ({AIRFLOW_PRESET.get(gtm, '??')}), "
        f"ect={d.get('ect')}°C, ict={d.get('ict')}°C"
    )


def _decode_status(d: dict) -> str:
    pos = d.get("pos")
    am = d.get("am")
    return (
        f"op={d.get('op')}, "
        f"pos={pos} ({BYPASS_POSITION.get(pos, '??')}), "
        f"am={am} ({BYPASS_STATUS_MODE.get(am, '??')})"
    )


def main() -> int:
    host = os.environ["VAE_HOST"]
    port = int(os.environ.get("VAE_PORT", "8883"))
    identity = os.environ["VAE_IDENTITY"]
    psk = os.environ["VAE_PSK"]
    prefix = os.environ["VAE_PREFIX"]
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 90

    sbc_topic = f"{prefix}/vent/sbc"
    sbs_topic = f"{prefix}/vent/sbs"
    connected = threading.Event()
    seen = {"sbc": False, "sbs": False}

    def ts() -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def on_connect(client, userdata, flags, reason_code, properties=None):
        print(f"{ts()} CONNECTED rc={reason_code}", flush=True)
        client.subscribe(sbc_topic, qos=0)
        client.subscribe(sbs_topic, qos=0)
        connected.set()

    def on_message(client, userdata, msg):
        try:
            raw = msg.payload.decode("utf-8")
        except UnicodeDecodeError:
            print(f"{ts()} {msg.topic} → <{msg.payload.hex()}> (non-utf8)", flush=True)
            return
        which = "sbc" if msg.topic == sbc_topic else "sbs" if msg.topic == sbs_topic else None
        decoded = ""
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and which == "sbc":
                decoded = "   →   " + _decode_config(obj)
            elif isinstance(obj, dict) and which == "sbs":
                decoded = "   →   " + _decode_status(obj)
        except json.JSONDecodeError:
            pass
        if which:
            seen[which] = True
        print(f"{ts()} {msg.topic} → {raw}{decoded}", flush=True)

    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=f"probe-sbc-{int(time.time())}",
    )
    client.on_connect = on_connect
    client.on_message = on_message
    client.tls_set_context(_build_psk_context(identity, psk))
    client.tls_insecure_set(True)
    client.connect(host, port, 60)
    client.loop_start()

    if not connected.wait(timeout=10):
        print("ERROR: did not connect within 10s", file=sys.stderr)
        return 1

    print(
        f"# read-only capture of {sbc_topic} and {sbs_topic} for {duration}s.\n"
        f"# Toggle bypass settings in the Connect app to provoke echoes.\n",
        flush=True,
    )
    time.sleep(duration)
    client.loop_stop()
    client.disconnect()

    print("\n========== SUMMARY ==========")
    print(f"vent/sbc (config) seen: {seen['sbc']}")
    print(f"vent/sbs (status) seen: {seen['sbs']}")
    if not (seen["sbc"] or seen["sbs"]):
        print(
            "No bypass topics observed. The unit may only publish them on change —\n"
            "re-run while changing a bypass setting in the Connect app, or extend the\n"
            "duration: python3 tools/probe_sbc.py 300"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
