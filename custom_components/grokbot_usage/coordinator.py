"""Data update coordinator for Grok Bot weekly usage."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from time import monotonic
from typing import override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    GrokBotUsageAuthError,
    GrokBotUsageClient,
    GrokBotUsageError,
    GrokBotUsageForbiddenError,
    GrokBotUsageRateLimitError,
    GrokBotUsageResponseError,
    UsageStatus,
)
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ERROR_CANNOT_CONNECT,
    ERROR_FORBIDDEN,
    ERROR_INVALID_RESPONSE,
    ERROR_RATE_LIMITED,
    ERROR_UNAUTHORIZED,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)
_STATE_MAX_LENGTH = 255
_AUTH_FAILURE_THRESHOLD = 3
_AUTH_FAILURE_MIN_SECONDS = 15 * 60


def scan_interval_seconds(entry: ConfigEntry) -> int:
    """Return a poll interval that stays inside the supported range."""
    raw = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    try:
        interval = int(raw)
    except TypeError, ValueError:
        return DEFAULT_SCAN_INTERVAL
    return min(max(interval, MIN_SCAN_INTERVAL), MAX_SCAN_INTERVAL)


class GrokBotUsageCoordinator(DataUpdateCoordinator[UsageStatus]):
    """Poll the Cursor usage endpoint on a fixed interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: GrokBotUsageClient,
        entry: ConfigEntry,
        update_interval_seconds: int,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval_seconds),
        )
        self._auth_failure_count = 0
        self._auth_failure_started: float | None = None
        self.client = client
        self.last_error: str | None = None
        self.last_error_code: str | None = None
        self.last_successful_update: datetime | None = None

    @override
    async def _async_update_data(self) -> UsageStatus:
        """Fetch the latest usage snapshot."""
        try:
            status = await self.client.async_get_usage()
        except (GrokBotUsageAuthError, GrokBotUsageForbiddenError) as err:
            code = (
                ERROR_UNAUTHORIZED
                if isinstance(err, GrokBotUsageAuthError)
                else ERROR_FORBIDDEN
            )
            self._record_error(code, err)
            now = monotonic()
            if self._auth_failure_started is None:
                self._auth_failure_started = now
            self._auth_failure_count += 1
            if (
                self._auth_failure_count >= _AUTH_FAILURE_THRESHOLD
                and now - self._auth_failure_started >= _AUTH_FAILURE_MIN_SECONDS
            ):
                raise ConfigEntryAuthFailed(self.last_error) from err
            raise UpdateFailed(self.last_error) from err
        except GrokBotUsageRateLimitError as err:
            self._record_error(ERROR_RATE_LIMITED, err)
            raise UpdateFailed(self.last_error) from err
        except GrokBotUsageResponseError as err:
            self._record_error(ERROR_INVALID_RESPONSE, err)
            raise UpdateFailed(self.last_error) from err
        except GrokBotUsageError as err:
            self._record_error(ERROR_CANNOT_CONNECT, err)
            raise UpdateFailed(self.last_error) from err

        self._reset_auth_failures()
        self.last_error = None
        self.last_error_code = None
        self.last_successful_update = dt_util.utcnow()
        return status

    def _reset_auth_failures(self) -> None:
        """Require a fresh, uninterrupted auth streak after any other result."""
        self._auth_failure_count = 0
        self._auth_failure_started = None

    def _record_error(self, code: str, err: Exception) -> None:
        """Remember a short diagnostic message without including the API key."""
        if code not in (ERROR_UNAUTHORIZED, ERROR_FORBIDDEN):
            # A 5xx/transport failure breaks the streak. The next auth error
            # starts a new 15-minute observation period, beyond the outage.
            self._reset_auth_failures()
        self.last_error_code = code
        self.last_error = str(err)[:_STATE_MAX_LENGTH]
