#!/usr/bin/env python3
"""Active sweep of the gtm enum.

For each gtm value in 0..4 + 254 + 255: publish {gtm, treq:"00:01:00"} to
<prefix>/vent/uo, wait 8s, capture all <prefix>/vent/cor echoes. Each write
overrides the previous; the 1-min treq timer is a safety net.

Usage:
    export VAE_HOST=...
    export VAE_PORT=8883
    export VAE_IDENTITY=...
    export VAE_PSK=...
    export VAE_PREFIX=...
    python3 tools/probe_uo_sweep.py
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion


GTM_SWEEP = [0, 1, 2, 3, 4, 254, 255]
WAIT_SECONDS = 8
GTM_NAMES = {0: "off", 1: "low", 2: "normal", 3: "boost", 4: "purge", 254: "none", 255: "max"}


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


def main() -> int:
    host = os.environ["VAE_HOST"]
    port = int(os.environ.get("VAE_PORT", "8883"))
    identity = os.environ["VAE_IDENTITY"]
    psk = os.environ["VAE_PSK"]
    prefix = os.environ["VAE_PREFIX"]

    cor_topic = f"{prefix}/vent/cor"
    uo_topic = f"{prefix}/vent/uo"
    rpm_supply_topic = f"{prefix}/vent/afs/rpm"
    rpm_extract_topic = f"{prefix}/vent/afe/rpm"

    captured: dict[int, list[str]] = defaultdict(list)
    rpm_supply: dict[int, list[float]] = defaultdict(list)
    rpm_extract: dict[int, list[float]] = defaultdict(list)
    current_gtm = {"value": -1}
    connected = threading.Event()

    def ts() -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def on_connect(client, userdata, flags, reason_code, properties=None):
        print(f"{ts()} CONNECTED rc={reason_code}", flush=True)
        client.subscribe(cor_topic, qos=0)
        client.subscribe(rpm_supply_topic, qos=0)
        client.subscribe(rpm_extract_topic, qos=0)
        connected.set()

    def on_message(client, userdata, msg):
        gtm = current_gtm["value"]
        if gtm < 0:
            return
        try:
            payload = msg.payload.decode("utf-8")
        except UnicodeDecodeError:
            return
        if msg.topic == cor_topic:
            captured[gtm].append(payload)
            print(f"{ts()} [gtm={gtm}] vent/cor → {payload}", flush=True)
        elif msg.topic == rpm_supply_topic:
            try:
                rpm_supply[gtm].append(float(payload))
            except ValueError:
                pass
        elif msg.topic == rpm_extract_topic:
            try:
                rpm_extract[gtm].append(float(payload))
            except ValueError:
                pass

    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=f"probe-{int(time.time())}",
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

    print(f"# sweeping gtm values {GTM_SWEEP}, {WAIT_SECONDS}s each, treq=01:00:00 (safety)\n")
    for gtm in GTM_SWEEP:
        current_gtm["value"] = gtm
        payload = json.dumps({"gtm": gtm, "treq": "00:01:00"})
        print(f"\n{ts()} === gtm={gtm} ({GTM_NAMES.get(gtm, '?')}) — publishing {payload} ===", flush=True)
        info = client.publish(uo_topic, payload, qos=0)
        info.wait_for_publish(timeout=5)
        time.sleep(WAIT_SECONDS)

    # Cancel any lingering override by publishing the original gtm of the schedule
    # baseline. Since we don't know what that is, just let the 1-min timers expire.
    print(f"\n{ts()} === sweep done; letting 1-min timers expire on the unit ===")

    client.loop_stop()
    client.disconnect()

    # Summary
    print("\n\n========== SWEEP SUMMARY ==========\n")
    print(f"{'gtm':<5}{'mode':<10}{'vent/cor echoes (unique)':<60}{'rpm supply':<15}{'rpm extract':<15}")
    for gtm in GTM_SWEEP:
        unique_echoes = sorted(set(captured[gtm]))
        echo_str = "; ".join(unique_echoes) if unique_echoes else "(no echo)"
        rpm_s = f"{min(rpm_supply[gtm]):.0f}-{max(rpm_supply[gtm]):.0f}" if rpm_supply[gtm] else "(none)"
        rpm_e = f"{min(rpm_extract[gtm]):.0f}-{max(rpm_extract[gtm]):.0f}" if rpm_extract[gtm] else "(none)"
        print(f"{gtm:<5}{GTM_NAMES.get(gtm, '?'):<10}{echo_str:<60}{rpm_s:<15}{rpm_e:<15}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
