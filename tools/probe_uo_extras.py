#!/usr/bin/env python3
"""Probe the gtm values that didn't echo in the first sweep: 4, 254, 255.

Also probes 0 again as a sanity check (we got ot=16, os=129 before).
Each probe gets a longer 15s window and listens to vent/# (broader scope)
to catch any non-vent/cor responses.
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


GTM_TARGETS = [0, 4, 254, 255]
WAIT_SECONDS = 15
GTM_NAMES = {0: "off", 4: "purge", 254: "none", 255: "max"}


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

    uo_topic = f"{prefix}/vent/uo"
    sub_topic = f"{prefix}/vent/#"  # broader: not just /cor
    connected = threading.Event()

    def ts() -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def on_connect(client, userdata, flags, reason_code, properties=None):
        print(f"{ts()} CONNECTED rc={reason_code}", flush=True)
        client.subscribe(sub_topic, qos=0)
        connected.set()

    def on_message(client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8")
        except UnicodeDecodeError:
            payload = msg.payload.hex()
        suffix = msg.topic[len(prefix) + 1:] if msg.topic.startswith(prefix + "/") else msg.topic
        # Only print interesting (non-frequent telemetry) messages
        if suffix in ("vent/afs/fm", "vent/afe/fm"):
            return  # too chatty
        print(f"{ts()} {suffix:<24} {payload}", flush=True)

    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=f"probe-extras-{int(time.time())}",
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

    print(f"# subscribed to {sub_topic}\n# probing gtm={GTM_TARGETS}, {WAIT_SECONDS}s each\n")

    # Settle: wait 5s to capture the current state
    print(f"\n{ts()} === settle (5s) — observing current state ===")
    time.sleep(5)

    for gtm in GTM_TARGETS:
        payload = json.dumps({"gtm": gtm, "treq": "00:01:00"})
        print(f"\n{ts()} === gtm={gtm} ({GTM_NAMES.get(gtm, '?')}) — publishing {payload} ===", flush=True)
        info = client.publish(uo_topic, payload, qos=0)
        info.wait_for_publish(timeout=5)
        time.sleep(WAIT_SECONDS)

    print(f"\n{ts()} === done ===")
    client.loop_stop()
    client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
