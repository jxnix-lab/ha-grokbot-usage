"""Sensors for Grok Bot weekly usage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GrokBotConfigEntry
from .api import UsageStatus
from .const import ERROR_OK
from .coordinator import GrokBotUsageCoordinator
from .entity import GrokBotUsageEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GrokBotSensorDescription(SensorEntityDescription):
    """Sensor description with a value reader."""

    value_fn: Callable[[UsageStatus], datetime | float | None]


def _usage_percent(data: UsageStatus) -> float | None:
    return data.usage_percent


def _period_start(data: UsageStatus) -> datetime | None:
    return data.current_period_start


def _next_reset(data: UsageStatus) -> datetime | None:
    return data.next_reset


SENSORS: tuple[GrokBotSensorDescription, ...] = (
    GrokBotSensorDescription(
        key="usage_percent",
        translation_key="usage_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:chart-donut",
        value_fn=_usage_percent,
    ),
    GrokBotSensorDescription(
        key="period_start",
        translation_key="period_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:calendar-start",
        value_fn=_period_start,
    ),
    GrokBotSensorDescription(
        key="next_reset",
        translation_key="next_reset",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:calendar-refresh",
        value_fn=_next_reset,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrokBotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Grok Bot usage sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(GrokBotUsageSensor(coordinator, description) for description in SENSORS),
            GrokBotApiErrorSensor(coordinator),
            GrokBotLastSuccessSensor(coordinator),
        ]
    )


class GrokBotUsageSensor(GrokBotUsageEntity, SensorEntity):
    """A sensor backed by the latest usage snapshot."""

    entity_description: GrokBotSensorDescription

    def __init__(
        self,
        coordinator: GrokBotUsageCoordinator,
        description: GrokBotSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    @override
    def native_value(self) -> datetime | float | None:
        """Return the sensor value from the latest snapshot."""
        data = self.coordinator.data
        if data is None:
            return None
        return self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, bool | None] | None:
        """Expose the remaining known response flags on the usage sensor."""
        if self.entity_description.key != "usage_percent":
            return None
        data = self.coordinator.data
        if data is None:
            return None
        return {
            "has_non_zero_included_limit": data.has_non_zero_included_limit,
            "uses_pooled_enterprise_allowance": data.uses_pooled_enterprise_allowance,
        }


class GrokBotApiErrorSensor(GrokBotUsageEntity, SensorEntity):
    """Diagnostic text sensor for the last API error."""

    _attr_translation_key = "api_error"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud-alert"

    def __init__(self, coordinator: GrokBotUsageCoordinator) -> None:
        """Initialize the diagnostic sensor."""
        super().__init__(coordinator, "api_error")

    @property
    @override
    def available(self) -> bool:
        """Stay available while the API is failing so the error remains visible."""
        return True

    @property
    @override
    def native_value(self) -> str:
        """Return ok, or a short error message."""
        return self.coordinator.last_error or ERROR_OK

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return a stable error code for automations."""
        return {"code": self.coordinator.last_error_code or ERROR_OK}


class GrokBotLastSuccessSensor(GrokBotUsageEntity, SensorEntity):
    """Diagnostic timestamp of the last successful usage response."""

    _attr_translation_key = "last_successful_update"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:update"

    def __init__(self, coordinator: GrokBotUsageCoordinator) -> None:
        """Initialize the diagnostic sensor."""
        super().__init__(coordinator, "last_successful_update")

    @property
    @override
    def available(self) -> bool:
        """Remain available after a later poll fails."""
        return self.coordinator.last_successful_update is not None

    @property
    @override
    def native_value(self) -> datetime | None:
        """Return the last successful poll time."""
        return self.coordinator.last_successful_update
