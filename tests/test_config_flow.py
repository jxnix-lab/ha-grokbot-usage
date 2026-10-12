"""Config flow tests with mocked usage responses."""

from __future__ import annotations

from datetime import timedelta

import pytest
from aiohttp import ClientConnectionError
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.grokbot_usage.config_flow import unique_id_for_api_key
from custom_components.grokbot_usage.const import (
    API_URL,
    CONF_API_KEY,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from custom_components.grokbot_usage.coordinator import scan_interval_seconds

from .test_api import _SAMPLE


class _Options:
    """Stand-in for a config entry's options mapping."""

    def __init__(self, options: dict[str, object]) -> None:
        self.options = options


_API_KEY = "user-key"


def _mock_success(
    aioclient_mock: AiohttpClientMocker, payload: dict | None = None
) -> None:
    aioclient_mock.post(API_URL, json=payload if payload is not None else _SAMPLE)


async def test_user_form_shown(hass: HomeAssistant) -> None:
    """The first step asks for an API key."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_user_flow_creates_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A valid key is stored and the bearer request uses an empty JSON body."""
    _mock_success(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: f"Bearer {_API_KEY}"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Grok Bot Usage"
    assert result["data"] == {CONF_API_KEY: _API_KEY}
    assert result["options"] == {CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL}
    assert result["result"].unique_id == unique_id_for_api_key(_API_KEY)
    method, url, body, headers = aioclient_mock.mock_calls[1]
    assert method.lower() == "post"
    assert str(url) == API_URL
    assert body == {}
    assert headers["Authorization"] == "Bearer test-access-token"
    assert "Cookie" not in headers


async def test_user_flow_rejects_401(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """HTTP 401 stays on the form and does not create an entry."""
    aioclient_mock.post(API_URL, status=401, text="unauthorized")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "rejected"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_user_flow_rejects_403(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """HTTP 403 explains that the key is not permitted."""
    aioclient_mock.post(API_URL, status=403, text="forbidden")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "forbidden-key"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "forbidden"}
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Connection failures are reported without creating an entry."""
    aioclient_mock.post(API_URL, exc=ClientConnectionError("offline"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: _API_KEY}
    )

    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_invalid_response(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A non-JSON success body is an invalid response."""
    aioclient_mock.post(API_URL, text="not-json")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: _API_KEY}
    )

    assert result["errors"] == {"base": "invalid_response"}


async def test_session_cookie_is_not_sent(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A session cookie is rejected locally and never sent to Cursor."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "WorkosCursorSessionToken=abc"}
    )

    assert result["errors"] == {"base": "session_cookie"}
    assert aioclient_mock.call_count == 0


async def test_duplicate_key_aborts(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The same API key cannot be added twice."""
    _mock_success(aioclient_mock)
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id_for_api_key(_API_KEY),
        data={CONF_API_KEY: _API_KEY},
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: _API_KEY}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_replaces_key(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Reauthentication stores a newly validated key and reloads."""
    _mock_success(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id_for_api_key("old-key"),
        data={CONF_API_KEY: "old-key"},
        options={CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "new-key"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "new-key"
    assert entry.unique_id == unique_id_for_api_key("new-key")


async def test_reauth_shows_403(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Reauthentication reports HTTP 403 without replacing the stored key."""
    aioclient_mock.post(API_URL, status=403, text="forbidden")
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id_for_api_key("old-key"),
        data={CONF_API_KEY: "old-key"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
        data=entry.data,
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "still-forbidden"}
    )

    assert result["errors"] == {"base": "forbidden"}
    assert entry.data[CONF_API_KEY] == "old-key"


async def test_options_flow_updates_poll_interval(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The options flow stores a new poll interval and reloads."""
    _mock_success(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: _API_KEY},
        options={CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL},
        unique_id=unique_id_for_api_key(_API_KEY),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 600}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_SCAN_INTERVAL: 600}
    assert entry.options[CONF_SCAN_INTERVAL] == 600
    assert entry.runtime_data.update_interval == timedelta(seconds=600)


async def test_options_flow_rejects_short_interval(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Intervals below one minute are rejected."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: _API_KEY},
        options={CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SCAN_INTERVAL: 10}
        )

    assert entry.options[CONF_SCAN_INTERVAL] == DEFAULT_SCAN_INTERVAL
    assert aioclient_mock.call_count == 0


def test_scan_interval_clamps_invalid_stored_values() -> None:
    """Hand-edited intervals cannot poll faster than once a minute."""
    assert scan_interval_seconds(_Options({})) == DEFAULT_SCAN_INTERVAL
    assert scan_interval_seconds(_Options({CONF_SCAN_INTERVAL: 1})) == MIN_SCAN_INTERVAL
    assert (
        scan_interval_seconds(_Options({CONF_SCAN_INTERVAL: 999_999}))
        == MAX_SCAN_INTERVAL
    )
    assert (
        scan_interval_seconds(_Options({CONF_SCAN_INTERVAL: "nope"}))
        == DEFAULT_SCAN_INTERVAL
    )


async def test_missing_key_stays_on_form(hass, aioclient_mock):
    """Blank input has its own error and makes no network request."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "   "}
    )
    assert result["errors"] == {"base": "missing_api_key"}
    assert aioclient_mock.call_count == 0
    assert hass.config_entries.async_entries(DOMAIN) == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "invalid_auth"), (403, "forbidden"), (429, "rate_limited")],
)
async def test_exchange_error_stays_on_form(hass, aioclient_mock, status, expected):
    """Exchange auth and permission failures are distinct in the real flow."""
    from custom_components.grokbot_usage.const import TOKEN_EXCHANGE_URL

    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN_EXCHANGE_URL, status=status, text="sensitive-response")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: _API_KEY}
    )
    assert result["errors"] == {"base": expected}
    assert aioclient_mock.call_count == 1
    assert hass.config_entries.async_entries(DOMAIN) == []
