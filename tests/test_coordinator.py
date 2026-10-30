"""Regression coverage for outage-safe background authentication handling."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.grokbot_usage.api import (
    GrokBotUsageAuthError,
    GrokBotUsageError,
    GrokBotUsageForbiddenError,
    GrokBotUsageRateLimitError,
    GrokBotUsageResponseError,
    parse_usage_status,
)
from custom_components.grokbot_usage.const import DOMAIN
from custom_components.grokbot_usage.coordinator import GrokBotUsageCoordinator

from .test_api import _SAMPLE


@pytest.fixture
def coordinator(hass):
    """Use synthetic errors and a controllable monotonic clock, without I/O."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    client = AsyncMock()
    return GrokBotUsageCoordinator(hass, client, entry, 300)


async def _fail(coordinator, now, error, expected=UpdateFailed):
    coordinator.client.async_get_usage.side_effect = error
    with (
        patch(
            "custom_components.grokbot_usage.coordinator.monotonic", return_value=now
        ),
        pytest.raises(expected) as caught,
    ):
        await coordinator._async_update_data()
    assert type(caught.value) is expected


@pytest.mark.parametrize(
    "error_type", [GrokBotUsageAuthError, GrokBotUsageForbiddenError]
)
async def test_auth_requires_count_and_elapsed_time(coordinator, error_type):
    """Three fast failures cannot reauth; exactly 15 minutes can."""
    for now in (0, 1, 2, 899):
        await _fail(coordinator, now, error_type("rejected"))
    await _fail(coordinator, 900, error_type("rejected"), ConfigEntryAuthFailed)


async def test_two_widely_spaced_auth_failures_are_insufficient(coordinator):
    """Elapsed time alone does not satisfy the minimum count."""
    await _fail(coordinator, 0, GrokBotUsageAuthError("401"))
    await _fail(coordinator, 1800, GrokBotUsageForbiddenError("403"))
    await _fail(coordinator, 1801, GrokBotUsageAuthError("401"), ConfigEntryAuthFailed)


@pytest.mark.parametrize(
    "error",
    [
        GrokBotUsageError("Cursor endpoint returned HTTP 503"),
        GrokBotUsageError("Timed out contacting the Cursor endpoint"),
        GrokBotUsageError("Could not connect to the Cursor endpoint"),
        GrokBotUsageRateLimitError("rate limited"),
        GrokBotUsageResponseError("invalid response"),
    ],
)
async def test_non_auth_failure_resets_entire_streak(coordinator, error):
    """An outage, even late in an auth streak, requires a new observation period."""
    await _fail(coordinator, 0, GrokBotUsageAuthError("401"))
    await _fail(coordinator, 800, GrokBotUsageForbiddenError("403"))
    await _fail(coordinator, 900, error)
    for now in (901, 902, 903, 1800):
        await _fail(coordinator, now, GrokBotUsageAuthError("401"))
    await _fail(coordinator, 1801, GrokBotUsageAuthError("401"), ConfigEntryAuthFailed)


async def test_success_resets_auth_history_and_diagnostics(coordinator):
    """A valid key that recovers never inherits an old authentication streak."""
    await _fail(coordinator, 0, GrokBotUsageAuthError("401"))
    await _fail(coordinator, 800, GrokBotUsageAuthError("401"))
    status = parse_usage_status(_SAMPLE)
    coordinator.client.async_get_usage.side_effect = None
    coordinator.client.async_get_usage.return_value = status
    assert await coordinator._async_update_data() is status
    assert coordinator.last_error is None
    assert coordinator.last_error_code is None
    assert coordinator.last_successful_update is not None
    for now in (900, 901, 1799):
        await _fail(coordinator, now, GrokBotUsageAuthError("401"))
    await _fail(coordinator, 1800, GrokBotUsageAuthError("401"), ConfigEntryAuthFailed)


async def test_persistent_auth_failure_starts_real_ha_reauth(
    hass, coordinator, freezer
):
    """HA retries initial failures, then starts its reauth flow at the threshold."""
    with patch("custom_components.grokbot_usage.coordinator.monotonic") as clock:
        coordinator.client.async_get_usage.side_effect = GrokBotUsageAuthError("401")
        for seconds in (0, 450, 900):
            clock.return_value = seconds
            # Move HA's refresh cooldown as well, without waiting in real time.
            freezer.tick(timedelta(minutes=8))
            await coordinator.async_refresh()
            await hass.async_block_till_done()
            flows = hass.config_entries.flow.async_progress()
            assert any(f["context"]["source"] == "reauth" for f in flows) == (
                seconds == 900
            )


@pytest.mark.parametrize("endpoint", ["exchange", "usage"])
async def test_503_then_401_then_success_retries(coordinator, endpoint):
    """The incident sequence recovers through the real client's error mapping."""
    from custom_components.grokbot_usage.api import GrokBotUsageClient

    from .test_api import _json, _Session

    session = _Session(body=_json(_SAMPLE))
    coordinator.client = GrokBotUsageClient(session, "synthetic-key")
    for now, status in ((0, 503), (300, 401)):
        if endpoint == "exchange":
            session.exchange_status = status
        else:
            session.status = status
        with (
            patch(
                "custom_components.grokbot_usage.coordinator.monotonic",
                return_value=now,
            ),
            pytest.raises(UpdateFailed) as caught,
        ):
            await coordinator._async_update_data()
        assert type(caught.value) is UpdateFailed
    session.exchange_status = session.status = 200
    assert (await coordinator._async_update_data()).usage_percent == 25.0
    assert coordinator._auth_failure_count == 0
