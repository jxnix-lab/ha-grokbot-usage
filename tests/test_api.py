"""Tests for the Cursor usage API client."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from aiohttp import ClientConnectionError

from custom_components.grokbot_usage.api import (
    GrokBotUsageAuthError,
    GrokBotUsageClient,
    GrokBotUsageError,
    GrokBotUsageForbiddenError,
    GrokBotUsageRateLimitError,
    GrokBotUsageResponseError,
    looks_like_session_cookie,
    normalize_api_key,
    parse_usage_status,
)
from custom_components.grokbot_usage.const import API_URL, TOKEN_EXCHANGE_URL

# Invented account-free fixture; all usage values and dates are synthetic.
_SAMPLE = {
    "usagePercent": 25.0,
    "currentPeriodStart": "2024-01-01T00:00:00Z",
    "nextResetTimestampUtc": 1_706_745_600_000,
    "hasAvailableUsage": True,
    "hasNonZeroIncludedLimit": True,
    "usesPooledEnterpriseAllowance": False,
}


class _Response:
    """Minimal aiohttp response context manager."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _Session:
    """Records one POST and returns a canned response."""

    def __init__(
        self,
        *,
        status: int = 200,
        body: str = "{}",
        error: Exception | None = None,
        exchange_status: int = 200,
        exchange_body: str = '{"accessToken":"test-access-token"}',
    ) -> None:
        self.status = status
        self.exchange_status = exchange_status
        self.exchange_body = exchange_body
        self.body = body
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        if url == TOKEN_EXCHANGE_URL:
            return _Response(self.exchange_status, self.exchange_body)
        return _Response(self.status, self.body)


def _client(session: _Session, api_key: str = "user-key") -> GrokBotUsageClient:
    return GrokBotUsageClient(session, api_key)  # type: ignore[arg-type]


async def test_success_parses_known_fields() -> None:
    """A documented payload becomes a usage snapshot."""
    session = _Session(body=_json(_SAMPLE))

    status = await _client(session).async_get_usage()

    assert status.usage_percent == 25.0
    assert status.current_period_start == datetime(2024, 1, 1, tzinfo=UTC)
    assert status.next_reset == datetime.fromtimestamp(1_706_745_600, tz=UTC)
    assert status.has_available_usage is True
    assert status.has_non_zero_included_limit is True
    assert status.uses_pooled_enterprise_allowance is False
    exchange = session.calls[0]
    assert exchange["url"] == TOKEN_EXCHANGE_URL
    assert exchange["headers"]["Authorization"] == "Bearer user-key"
    assert exchange["json"] == {}
    assert exchange["allow_redirects"] is False
    call = session.calls[1]
    assert call["url"] == API_URL
    assert call["json"] == {}
    assert call["headers"]["Authorization"] == "Bearer test-access-token"
    assert "Cookie" not in call["headers"]
    assert call["allow_redirects"] is False


async def test_snake_case_and_nested_payload() -> None:
    """Snake case fields nested one level down are accepted."""
    status = parse_usage_status(
        {
            "result": {
                "usage_percent": "15%",
                "current_period_start": "2024-01-01",
                "next_reset_timestamp_utc": "1706745600",
                "has_available_usage": "false",
                "has_non_zero_included_limit": 1,
                "uses_pooled_enterprise_allowance": "no",
            }
        }
    )

    assert status.usage_percent == 15.0
    assert status.current_period_start == datetime(2024, 1, 1, tzinfo=UTC)
    assert status.next_reset == datetime.fromtimestamp(1_706_745_600, tz=UTC)
    assert status.has_available_usage is False
    assert status.has_non_zero_included_limit is True
    assert status.uses_pooled_enterprise_allowance is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, 0.0),
        ("0", 0.0),
        (True, None),
        ("nope", None),
        (float("nan"), None),
    ],
)
def test_usage_percent_edge_cases(value: object, expected: float | None) -> None:
    """Unusable percentage values become unknown instead of raising."""
    status = parse_usage_status({"usagePercent": value})

    assert status.usage_percent == expected


def test_implausible_timestamps_are_dropped() -> None:
    """Epoch zero and unparseable strings do not invent a period."""
    status = parse_usage_status(
        {"currentPeriodStart": 0, "nextResetTimestampUtc": "tomorrow"}
    )

    assert status.current_period_start is None
    assert status.next_reset is None


def test_unknown_success_shape_is_kept() -> None:
    """A 200 object without known fields does not raise."""
    status = parse_usage_status({"unexpected": 1})

    assert status.usage_percent is None
    assert status.received_keys == ("unexpected",)


def test_error_object_is_rejected() -> None:
    """An error object with no usage fields is an invalid response."""
    with pytest.raises(GrokBotUsageResponseError):
        parse_usage_status({"error": "unauthenticated"})


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, GrokBotUsageAuthError),
        (403, GrokBotUsageForbiddenError),
        (429, GrokBotUsageRateLimitError),
        (500, GrokBotUsageError),
        (302, GrokBotUsageError),
    ],
)
async def test_http_errors(status: int, error: type[Exception]) -> None:
    """Auth failures stay distinct from other HTTP failures."""
    session = _Session(status=status, body="nope")

    with pytest.raises(error):
        await _client(session).async_get_usage()


async def test_invalid_json() -> None:
    """Non-JSON success bodies are rejected."""
    session = _Session(body="not-json")

    with pytest.raises(GrokBotUsageResponseError):
        await _client(session).async_get_usage()


async def test_connection_error() -> None:
    """Socket failures become a connection error and do not include the key."""
    session = _Session(error=ClientConnectionError("offline"))

    with pytest.raises(GrokBotUsageError, match="Could not connect") as caught:
        await _client(session, "super-secret").async_get_usage()

    assert "super-secret" not in str(caught.value)


def test_normalize_api_key_strips_bearer_prefix() -> None:
    """An accidental Bearer prefix is removed once."""
    assert normalize_api_key("  Bearer user-key  ") == "user-key"
    assert normalize_api_key("user-key") == "user-key"


def test_session_cookie_values_are_recognized() -> None:
    """Cookie pastes are identified before they can be sent."""
    assert looks_like_session_cookie("WorkosCursorSessionToken=abc")
    assert looks_like_session_cookie("Cookie: session=abc")
    assert not looks_like_session_cookie("crsr_user_key")


def _json(payload: dict[str, object]) -> str:
    return json.dumps(payload)


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (401, '{"message":"secret-echo"}', GrokBotUsageAuthError),
        (403, "{}", GrokBotUsageForbiddenError),
        (429, "{}", GrokBotUsageRateLimitError),
        (302, "{}", GrokBotUsageError),
        (500, "{}", GrokBotUsageError),
        (200, "{}", GrokBotUsageResponseError),
        (200, '{"accessToken":123}', GrokBotUsageResponseError),
        (200, '{"accessToken":" "}', GrokBotUsageResponseError),
        (200, "not-json", GrokBotUsageResponseError),
        (
            200,
            '{"error":{"code":"unauthenticated","message":"secret-echo"}}',
            GrokBotUsageAuthError,
        ),
        (200, '{"code":"permission_denied"}', GrokBotUsageForbiddenError),
    ],
)
async def test_exchange_failures_do_not_request_usage(status, body, error):
    """Bad exchanges stop before usage and never expose response bodies."""
    session = _Session(exchange_status=status, exchange_body=body)
    with pytest.raises(error) as caught:
        await _client(session).async_get_usage()
    assert len(session.calls) == 1
    assert "secret-echo" not in str(caught.value)


async def test_each_poll_exchanges_again():
    """The client never reuses an expired access token on a later poll."""
    session = _Session(body=_json(_SAMPLE))
    client = _client(session)
    await client.async_get_usage()
    session.exchange_body = '{"accessToken":"replacement-token"}'
    await client.async_get_usage()
    assert [call["url"] for call in session.calls] == [
        TOKEN_EXCHANGE_URL,
        API_URL,
        TOKEN_EXCHANGE_URL,
        API_URL,
    ]
    assert session.calls[3]["headers"]["Authorization"] == "Bearer replacement-token"
