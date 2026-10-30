"""Sensor setup tests."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.grokbot_usage.const import (
    API_URL,
    CONF_API_KEY,
    CONF_SCAN_INTERVAL,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_OK,
    ERROR_UNAUTHORIZED,
)
from custom_components.grokbot_usage.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .test_api import _SAMPLE


async def _setup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> MockConfigEntry:
    aioclient_mock.post(API_URL, json=_SAMPLE)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Grok Bot Usage",
        data={CONF_API_KEY: "user-key"},
        options={CONF_SCAN_INTERVAL: 300},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entity_id(hass: HomeAssistant, entry: MockConfigEntry, unique_suffix: str) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor" if unique_suffix != "has_available_usage" else "binary_sensor",
        DOMAIN,
        f"{entry.entry_id}_{unique_suffix}",
    )
    assert entity_id is not None
    return entity_id


async def test_sensors_expose_usage_time_series(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Weekly usage is a measurement, and the period fields are timestamps."""
    entry = await _setup(hass, aioclient_mock)

    usage = hass.states.get(_entity_id(hass, entry, "usage_percent"))
    assert usage is not None
    assert float(usage.state) == 25.0
    assert usage.attributes["state_class"] == "measurement"
    assert usage.attributes["unit_of_measurement"] == PERCENTAGE
    assert usage.attributes["has_non_zero_included_limit"] is True
    assert usage.attributes["uses_pooled_enterprise_allowance"] is False

    period = hass.states.get(_entity_id(hass, entry, "period_start"))
    assert period is not None
    assert period.attributes["device_class"] == "timestamp"
    assert datetime.fromisoformat(period.state) == datetime(2024, 1, 1, tzinfo=UTC)

    reset = hass.states.get(_entity_id(hass, entry, "next_reset"))
    assert reset is not None
    assert reset.attributes["device_class"] == "timestamp"
    assert datetime.fromisoformat(reset.state) == datetime.fromtimestamp(
        1_706_745_600, tz=UTC
    )

    available = hass.states.get(_entity_id(hass, entry, "has_available_usage"))
    assert available is not None
    assert available.state == "on"

    api_error_id = _entity_id(hass, entry, "api_error")
    api_error = hass.states.get(api_error_id)
    assert api_error is not None
    assert api_error.state == ERROR_OK
    assert api_error.attributes["code"] == ERROR_OK
    registry_entry = er.async_get(hass).async_get(api_error_id)
    assert registry_entry is not None
    assert registry_entry.entity_category is EntityCategory.DIAGNOSTIC

    last_success = hass.states.get(_entity_id(hass, entry, "last_successful_update"))
    assert last_success is not None
    assert last_success.attributes["device_class"] == "timestamp"
    assert last_success.state not in {"unknown", "unavailable"}


async def test_api_error_survives_a_failed_poll(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A later HTTP failure is visible on the diagnostic sensors."""
    entry = await _setup(hass, aioclient_mock)
    last_success = hass.states.get(_entity_id(hass, entry, "last_successful_update"))
    assert last_success is not None
    previous_success = last_success.state

    aioclient_mock.clear_requests()
    from custom_components.grokbot_usage.const import TOKEN_EXCHANGE_URL

    aioclient_mock.post(TOKEN_EXCHANGE_URL, json={"accessToken": "test-access-token"})
    aioclient_mock.post(API_URL, status=500, text="unavailable")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    api_error = hass.states.get(_entity_id(hass, entry, "api_error"))
    assert api_error is not None
    assert api_error.state != "unavailable"
    assert "HTTP 500" in api_error.state
    assert api_error.attributes["code"] == ERROR_CANNOT_CONNECT

    last_success = hass.states.get(_entity_id(hass, entry, "last_successful_update"))
    assert last_success is not None
    assert last_success.state == previous_success

    usage = hass.states.get(_entity_id(hass, entry, "usage_percent"))
    assert usage is not None
    assert usage.state == "unavailable"


async def test_single_unauthorized_poll_keeps_retrying(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """One HTTP 401 exposes diagnostics without starting reauthentication."""
    entry = await _setup(hass, aioclient_mock)
    aioclient_mock.clear_requests()
    from custom_components.grokbot_usage.const import TOKEN_EXCHANGE_URL

    aioclient_mock.post(TOKEN_EXCHANGE_URL, json={"accessToken": "test-access-token"})
    aioclient_mock.post(API_URL, status=401, text="unauthorized")

    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    api_error = hass.states.get(_entity_id(hass, entry, "api_error"))
    assert api_error is not None
    assert api_error.attributes["code"] == ERROR_UNAUTHORIZED
    flows = hass.config_entries.flow.async_progress()
    assert not any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_diagnostics_redact_the_api_key(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Diagnostics include usage and omit the API key."""
    entry = await _setup(hass, aioclient_mock)

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["usage"]["usage_percent"] == 25.0
    assert result["usage"]["has_available_usage"] is True
    assert "user-key" not in str(result)
    assert result["config_entry"]["data"][CONF_API_KEY] == "**REDACTED**"
