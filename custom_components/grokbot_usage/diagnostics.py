"""Diagnostics for Grok Bot Usage."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import GrokBotConfigEntry
from .const import CONF_API_KEY

TO_REDACT = {CONF_API_KEY, "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GrokBotConfigEntry
) -> dict[str, Any]:
    """Return diagnostics with the API key removed."""
    coordinator = entry.runtime_data
    data = coordinator.data
    usage: dict[str, Any] | None = None
    if data is not None:
        usage = {
            "usage_percent": data.usage_percent,
            "current_period_start": _iso(data.current_period_start),
            "next_reset": _iso(data.next_reset),
            "has_available_usage": data.has_available_usage,
            "has_non_zero_included_limit": data.has_non_zero_included_limit,
            "uses_pooled_enterprise_allowance": data.uses_pooled_enterprise_allowance,
            "received_keys": list(data.received_keys),
        }
    return {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "usage": usage,
        "last_error": coordinator.last_error,
        "last_error_code": coordinator.last_error_code,
        "last_successful_update": _iso(coordinator.last_successful_update),
    }


def _iso(value: Any) -> str | None:
    """Return an ISO timestamp, or None."""
    if value is None:
        return None
    return value.isoformat()
