"""Base entity for Grok Bot Usage sensors."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONFIGURATION_URL, DOMAIN, MANUFACTURER, MODEL
from .coordinator import GrokBotUsageCoordinator


class GrokBotUsageEntity(CoordinatorEntity[GrokBotUsageCoordinator]):
    """Entity shared by the usage device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GrokBotUsageCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for the usage account."""
        entry = self.coordinator.config_entry
        assert entry is not None
        return DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=entry.title,
            configuration_url=CONFIGURATION_URL,
        )
