"""Smoke test: confirms the test harness imports our integration."""
from custom_components.ventaxia_econiq.const import DOMAIN


async def test_domain_constant() -> None:
    assert DOMAIN == "ventaxia_econiq"
