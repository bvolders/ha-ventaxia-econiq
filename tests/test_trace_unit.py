"""Smoke test for tools/trace_unit.py helpers (no MQTT)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "trace_unit", REPO_ROOT / "tools" / "trace_unit.py"
)
trace_unit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace_unit)


def test_format_payload_json_object() -> None:
    assert trace_unit._format_payload(b'{"gtm": 3, "treq": "01:00:00"}') == '{"gtm":3,"treq":"01:00:00"}'


def test_format_payload_plain_text() -> None:
    assert trace_unit._format_payload(b"hello") == "hello"


def test_format_payload_binary_falls_back_to_hex() -> None:
    assert trace_unit._format_payload(b"\xff\xfe").startswith("<bin ")


def test_color_for_known_topics() -> None:
    assert trace_unit._color_for("vent/uo") != ""
    assert trace_unit._color_for("vent/cor") != ""
    assert trace_unit._color_for("io/t1") == ""
