"""Data update coordinator for Grok Bot weekly usage."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
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
        self.client = client
        self.last_error: str | None = None
        self.last_error_code: str | None = None
        self.last_successful_update: datetime | None = None

    @override
    async def _async_update_data(self) -> UsageStatus:
        """Fetch the latest usage snapshot."""
        try:
            status = await self.client.async_get_usage()
        except GrokBotUsageAuthError as err:
            self._record_error(ERROR_UNAUTHORIZED, err)
            raise ConfigEntryAuthFailed(self.last_error) from err
        except GrokBotUsageForbiddenError as err:
            self._record_error(ERROR_FORBIDDEN, err)
            raise ConfigEntryAuthFailed(self.last_error) from err
        except GrokBotUsageRateLimitError as err:
            self._record_error(ERROR_RATE_LIMITED, err)
            raise UpdateFailed(self.last_error) from err
        except GrokBotUsageResponseError as err:
            self._record_error(ERROR_INVALID_RESPONSE, err)
            raise UpdateFailed(self.last_error) from err
        except GrokBotUsageError as err:
            self._record_error(ERROR_CANNOT_CONNECT, err)
            raise UpdateFailed(self.last_error) from err

        self.last_error = None
        self.last_error_code = None
        self.last_successful_update = dt_util.utcnow()
        return status

    def _record_error(self, code: str, err: Exception) -> None:
        """Remember a short diagnostic message without including the API key."""
        self.last_error_code = code
        self.last_error = str(err)[:_STATE_MAX_LENGTH]
