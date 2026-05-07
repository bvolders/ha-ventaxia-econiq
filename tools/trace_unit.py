#!/usr/bin/env python3
"""Passive MQTT trace for a Vent-Axia Econiq unit.

Subscribes to '<prefix>/#' and pretty-prints every received message with a
timestamp. NEVER publishes. Intended to be run while the user drives the
official Vent-Axia Connect app from their phone — every action the app
takes shows up on the wire here, including the exact cancel mechanism
that we'd otherwise have to guess.

Usage:
    export VAE_HOST=10.1.5.33
    export VAE_PORT=8883
    export VAE_IDENTITY=<32-char-hex>
    export VAE_PSK=<16-char-hex>
    export VAE_PREFIX=BZPKB-XXXXX
    python3 tools/trace_unit.py | tee tools/trace_unit.$(date +%Y%m%d-%H%M%S).log
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import time
from datetime import datetime

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion


# ANSI color codes — highlights writes (vent/uo) in yellow, echoes (vent/cor)
# in cyan so the cause/effect pairs are easy to spot in the scrollback.
RESET = "\033[0m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
DIM = "\033[2m"


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


def _format_payload(raw: bytes) -> str:
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return f"<bin {raw.hex()}>"
    try:
        return json.dumps(json.loads(decoded), separators=(",", ":"))
    except json.JSONDecodeError:
        return decoded


def _color_for(suffix: str) -> str:
    if suffix == "vent/uo":
        return YELLOW
    if suffix == "vent/cor":
        return CYAN
    return ""


def main() -> int:
    host = os.environ["VAE_HOST"]
    port = int(os.environ.get("VAE_PORT", "8883"))
    identity = os.environ["VAE_IDENTITY"]
    psk = os.environ["VAE_PSK"]
    prefix = os.environ["VAE_PREFIX"]

    sub_topic = f"{prefix}/#"

    def on_connect(client, userdata, flags, reason_code, properties=None):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"{DIM}{ts}{RESET} CONNECTED rc={reason_code}, subscribing to {sub_topic}")
        client.subscribe(sub_topic, qos=0)

    def on_message(client, userdata, msg):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        suffix = msg.topic[len(prefix) + 1:] if msg.topic.startswith(prefix + "/") else msg.topic
        color = _color_for(suffix)
        payload = _format_payload(msg.payload)
        print(f"{DIM}{ts}{RESET} {color}{suffix:<30}{RESET} {payload}", flush=True)

    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=f"trace-{int(time.time())}",
    )
    client.on_connect = on_connect
    client.on_message = on_message
    client.tls_set_context(_build_psk_context(identity, psk))
    client.tls_insecure_set(True)
    client.connect(host, port, 60)

    print(f"{DIM}# trace_unit.py — passive only, will never publish{RESET}")
    print(f"{DIM}# legend: {YELLOW}vent/uo (writes from app){RESET}{DIM}, {CYAN}vent/cor (echoes from unit){RESET}")
    print(f"{DIM}# drive the Connect app on your phone; Ctrl-C to stop{RESET}")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print(f"\n{DIM}# stopped{RESET}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
