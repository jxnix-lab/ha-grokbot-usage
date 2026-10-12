"""Binary sensor for whether Grok Bot usage is still available."""

from __future__ import annotations

from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GrokBotConfigEntry
from .coordinator import GrokBotUsageCoordinator
from .entity import GrokBotUsageEntity

PARALLEL_UPDATES = 0

_DESCRIPTION = BinarySensorEntityDescription(
    key="has_available_usage",
    translation_key="has_available_usage",
    icon="mdi:check-circle-outline",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrokBotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the available-usage binary sensor."""
    async_add_entities([GrokBotAvailableUsageBinarySensor(entry.runtime_data)])


class GrokBotAvailableUsageBinarySensor(GrokBotUsageEntity, BinarySensorEntity):
    """Binary sensor that is on when the account still has included usage."""

    entity_description = _DESCRIPTION

    def __init__(self, coordinator: GrokBotUsageCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, _DESCRIPTION.key)

    @property
    @override
    def is_on(self) -> bool | None:
        """Return True when the endpoint reports available usage."""
        data = self.coordinator.data
        if data is None:
            return None
        return data.has_available_usage
