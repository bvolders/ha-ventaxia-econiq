"""Test fixtures for ventaxia_econiq."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make our custom integration loadable in tests."""
    yield
