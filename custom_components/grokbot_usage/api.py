"""Client for the private Cursor Grok Bot usage endpoint.

The endpoint is undocumented. Parsing accepts the known response shape and a
few likely variants, and it fails closed on authentication errors.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import (
    API_URL,
    REQUEST_TIMEOUT_SECONDS,
    TOKEN_EXCHANGE_URL,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
_NUMERIC_TEXT = re.compile(r"-?\d+(?:\.\d+)?")
_MIN_EPOCH_SECONDS = 1_000_000_000
_MILLISECOND_THRESHOLD = 100_000_000_000

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "usage_percent": ("usagePercent", "usage_percent", "usage_percentage"),
    "current_period_start": (
        "currentPeriodStart",
        "current_period_start",
        "periodStart",
    ),
    "next_reset": (
        "nextResetTimestampUtc",
        "next_reset_timestamp_utc",
        "nextReset",
        "next_reset",
    ),
    "has_available_usage": ("hasAvailableUsage", "has_available_usage"),
    "has_non_zero_included_limit": (
        "hasNonZeroIncludedLimit",
        "has_non_zero_included_limit",
    ),
    "uses_pooled_enterprise_allowance": (
        "usesPooledEnterpriseAllowance",
        "uses_pooled_enterprise_allowance",
    ),
}
_KNOWN_NAMES = {
    alias.lower() for aliases in _FIELD_ALIASES.values() for alias in aliases
}
_ERROR_CODES = {
    "unauthenticated",
    "permission_denied",
    "unauthorized",
    "forbidden",
    "invalid_argument",
    "not_found",
    "internal",
    "resource_exhausted",
}


class GrokBotUsageError(Exception):
    """The usage endpoint could not be queried."""


class GrokBotUsageAuthError(GrokBotUsageError):
    """The API key was rejected with HTTP 401."""


class GrokBotUsageForbiddenError(GrokBotUsageError):
    """The API key is not allowed to read usage (HTTP 403)."""


class GrokBotUsageRateLimitError(GrokBotUsageError):
    """The usage endpoint rate limited the request."""


class GrokBotUsageResponseError(GrokBotUsageError):
    """The usage endpoint returned a response that could not be used."""


@dataclass(frozen=True, slots=True)
class UsageStatus:
    """Parsed weekly usage snapshot."""

    usage_percent: float | None
    current_period_start: datetime | None
    next_reset: datetime | None
    has_available_usage: bool | None
    has_non_zero_included_limit: bool | None
    uses_pooled_enterprise_allowance: bool | None
    received_keys: tuple[str, ...]


def normalize_api_key(value: str) -> str:
    """Return a user API key with surrounding whitespace and a Bearer prefix removed."""
    key = value.strip()
    if key.lower().startswith("bearer "):
        return key[7:].strip()
    return key


def looks_like_session_cookie(value: str) -> bool:
    """Return True when the value looks like a browser session cookie.

    This integration only accepts a Cursor user API key. It never reads or
    forwards session cookies.
    """
    lowered = value.lower()
    compact = lowered.replace(" ", "")
    if lowered.startswith("cookie:"):
        return True
    if "workoscursorsessiontoken" in compact:
        return True
    return "sessiontoken=" in compact


class GrokBotUsageClient:
    """HTTP client for GetSandUsageStatus."""

    def __init__(self, session: ClientSession, api_key: str) -> None:
        """Initialize the client with a shared session and user API key."""
        self._session = session
        self._api_key = api_key

    async def async_get_usage(self) -> UsageStatus:
        """Exchange the user key, then request usage with the short-lived token.

        Exchange on each poll so expired tokens cannot trigger reauthentication.
        Access and refresh tokens are never persisted or logged.
        """
        payload = await self._async_post(TOKEN_EXCHANGE_URL, self._api_key)
        token = payload.get("accessToken")
        if not isinstance(token, str) or not token.strip():
            raise GrokBotUsageResponseError(
                "Cursor key exchange returned no access token"
            )
        return parse_usage_status(await self._async_post(API_URL, token))

    async def _async_post(self, url: str, credential: str) -> dict[str, Any]:
        """POST to a fixed Cursor endpoint without exposing response bodies."""
        headers = {
            "Authorization": f"Bearer {credential}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                async with self._session.post(
                    url,
                    json={},
                    headers=headers,
                    timeout=_TIMEOUT,
                    allow_redirects=False,
                ) as response:
                    status = response.status
                    body = await response.text()
        except TimeoutError:
            raise GrokBotUsageError(
                "Timed out contacting the Cursor endpoint"
            ) from None
        except ClientError:
            raise GrokBotUsageError(
                "Could not connect to the Cursor endpoint"
            ) from None

        return _parse_json_response(status, body)


def _parse_json_response(status: int, body: str) -> dict[str, Any]:
    """Turn an HTTP response into JSON or a typed error."""
    if status == 401:
        raise GrokBotUsageAuthError("Cursor endpoint rejected the API key (HTTP 401)")
    if status == 403:
        raise GrokBotUsageForbiddenError(
            "Cursor endpoint refused the API key (HTTP 403)"
        )
    if status == 429:
        raise GrokBotUsageRateLimitError(
            "Cursor endpoint rate limited the request (HTTP 429)"
        )
    if status < 200 or status >= 300:
        raise GrokBotUsageError(f"Cursor endpoint returned HTTP {status}")

    text = body.strip()
    if not text:
        raise GrokBotUsageResponseError("Cursor endpoint returned an empty response")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        raise GrokBotUsageResponseError(
            "Cursor endpoint returned a response that was not JSON"
        ) from None
    if not isinstance(payload, dict):
        raise GrokBotUsageResponseError(
            "Cursor endpoint returned JSON that was not an object"
        )
    _raise_payload_error(payload)
    return payload


def _raise_payload_error(payload: dict[str, Any]) -> None:
    """Classify known API error codes without displaying upstream messages."""
    error = payload.get("error")
    source = error if isinstance(error, dict) else payload
    code = source.get("code")
    if isinstance(code, str):
        code = code.lower()
    if isinstance(code, str) and code in ("unauthenticated", "unauthorized"):
        raise GrokBotUsageAuthError("Cursor rejected the credential")
    if isinstance(code, str) and code in ("permission_denied", "forbidden"):
        raise GrokBotUsageForbiddenError("Cursor denied access to usage")
    if code == "resource_exhausted":
        raise GrokBotUsageRateLimitError("Cursor rate limited the request")
    if _looks_like_error(payload):
        raise GrokBotUsageResponseError("Cursor returned an error payload")


def parse_usage_status(payload: dict[str, Any]) -> UsageStatus:
    """Parse a JSON object into a usage snapshot.

    Known fields are read from the top-level object. If they are missing, a
    single nested object that contains them is used instead. A 200 response
    that only carries an error object is rejected.
    """
    _raise_payload_error(payload)
    data = _unwrap_payload(payload)
    if not _has_known_fields(data):
        if _looks_like_error(payload) or _looks_like_error(data):
            raise GrokBotUsageResponseError("Cursor endpoint returned an error payload")
        _LOGGER.warning(
            "Cursor usage response did not include known usage fields; keys=%s",
            sorted(str(key) for key in data),
        )

    return UsageStatus(
        usage_percent=parse_percent(_lookup(data, _FIELD_ALIASES["usage_percent"])),
        current_period_start=parse_timestamp(
            _lookup(data, _FIELD_ALIASES["current_period_start"])
        ),
        next_reset=parse_timestamp(_lookup(data, _FIELD_ALIASES["next_reset"])),
        has_available_usage=parse_bool(
            _lookup(data, _FIELD_ALIASES["has_available_usage"])
        ),
        has_non_zero_included_limit=parse_bool(
            _lookup(data, _FIELD_ALIASES["has_non_zero_included_limit"])
        ),
        uses_pooled_enterprise_allowance=parse_bool(
            _lookup(data, _FIELD_ALIASES["uses_pooled_enterprise_allowance"])
        ),
        received_keys=tuple(str(key) for key in data),
    )


def parse_percent(value: Any) -> float | None:
    """Return a finite usage percentage, or None when the value is unusable."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip().rstrip("%").strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(number):
        return None
    return number


def parse_bool(value: Any) -> bool | None:
    """Return a boolean flag, or None when the value is missing or unrecognized."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return None


def parse_timestamp(value: Any) -> datetime | None:
    """Return an aware UTC datetime from an ISO string or epoch seconds/milliseconds."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _from_epoch(float(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if _NUMERIC_TEXT.fullmatch(text):
            return _from_epoch(float(text))
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None


def _from_epoch(value: float) -> datetime | None:
    """Convert epoch seconds or milliseconds to UTC, rejecting implausible values."""
    if not math.isfinite(value):
        return None
    if abs(value) >= _MILLISECOND_THRESHOLD:
        value /= 1000.0
    if value < _MIN_EPOCH_SECONDS:
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except OverflowError, OSError, ValueError:
        return None


def _lookup(data: dict[str, Any], names: tuple[str, ...]) -> Any:
    """Return the first present alias, with a case-insensitive fallback."""
    for name in names:
        if name in data:
            return data[name]
    lowered = {str(key).lower(): item for key, item in data.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _has_known_fields(data: dict[str, Any]) -> bool:
    """Return True when the object contains at least one known usage field."""
    return any(str(key).lower() in _KNOWN_NAMES for key in data)


def _unwrap_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the object that holds the usage fields."""
    if _has_known_fields(payload):
        return payload
    candidates = [
        value
        for value in payload.values()
        if isinstance(value, dict) and _has_known_fields(value)
    ]
    if len(candidates) == 1:
        return candidates[0]
    return payload


def _looks_like_error(payload: dict[str, Any]) -> bool:
    """Return True when the object looks like an API error rather than usage."""
    if "error" in payload or "errors" in payload:
        return True
    code = payload.get("code")
    return isinstance(code, str) and code.lower() in _ERROR_CODES
