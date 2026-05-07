#!/usr/bin/env python3
"""One-shot probe for gtm=255 (Max), then gtm=254 (cancel)."""
import json
import os
import ssl
import threading
import time
from datetime import datetime

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ctx.minimum_version = ssl.TLSVersion.TLSv1_2
ctx.maximum_version = ssl.TLSVersion.TLSv1_2
ctx.set_ciphers("PSK-AES128-CBC-SHA")
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
ctx.set_psk_client_callback(
    lambda h: (os.environ["VAE_IDENTITY"], bytes.fromhex(os.environ["VAE_PSK"]))
)

prefix = os.environ["VAE_PREFIX"]
connected = threading.Event()


def ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def on_c(c, u, f, r, p=None):
    c.subscribe(f"{prefix}/vent/#")
    connected.set()


def on_m(c, u, msg):
    suf = msg.topic[len(prefix) + 1:]
    if suf in ("vent/afs/fm", "vent/afe/fm"):
        return
    print(f"{ts()} {suf:<22} {msg.payload.decode('utf-8', errors='replace')}", flush=True)


c = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, client_id=f"probe255-{int(time.time())}")
c.on_connect = on_c
c.on_message = on_m
c.tls_set_context(ctx)
c.tls_insecure_set(True)
c.connect(os.environ["VAE_HOST"], int(os.environ["VAE_PORT"]), 60)
c.loop_start()
connected.wait(10)

time.sleep(3)
print(f"{ts()} --- publishing gtm=255 ---", flush=True)
c.publish(f"{prefix}/vent/uo", json.dumps({"gtm": 255, "treq": "00:01:00"}), qos=0).wait_for_publish(5)
time.sleep(20)

print(f"{ts()} --- publishing gtm=254 (cancel) ---", flush=True)
c.publish(f"{prefix}/vent/uo", json.dumps({"gtm": 254, "treq": "00:01:00"}), qos=0).wait_for_publish(5)
time.sleep(8)

c.loop_stop()
c.disconnect()
