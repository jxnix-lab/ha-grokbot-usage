"""The Grok Bot Usage integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GrokBotUsageClient
from .const import CONF_API_KEY
from .const import DOMAIN as DOMAIN
from .coordinator import GrokBotUsageCoordinator, scan_interval_seconds

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

type GrokBotConfigEntry = ConfigEntry[GrokBotUsageCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: GrokBotConfigEntry) -> bool:
    """Set up Grok Bot Usage from a config entry."""
    client = GrokBotUsageClient(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    coordinator = GrokBotUsageCoordinator(
        hass,
        client,
        entry,
        update_interval_seconds=scan_interval_seconds(entry),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GrokBotConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
