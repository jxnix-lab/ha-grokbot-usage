"""Pytest configuration for the Grok Bot Usage integration."""

from __future__ import annotations

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the repo's custom component in every Home Assistant test."""


@pytest.fixture(autouse=True)
def mock_key_exchange(aioclient_mock):
    """Use a synthetic access token; no test calls Cursor."""
    from custom_components.grokbot_usage.const import TOKEN_EXCHANGE_URL

    aioclient_mock.post(TOKEN_EXCHANGE_URL, json={"accessToken": "test-access-token"})
