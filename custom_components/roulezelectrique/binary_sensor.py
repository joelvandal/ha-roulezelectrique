"""Binary sensor platform for the Roulez Électrique (BETA) integration.

Two binary sensors per charger:
  - Online (connectivity) — OCPP chargers only (non-OCPP chargers have no
    real-time connection state tracked by the platform)
  - Charging — all chargers
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import RoulezElectriqueCoordinator
from .entity import RoulezElectriqueEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoulezElectriqueBinarySensorDescription(BinarySensorEntityDescription):
    """Description with value_fn and optional ocpp_only constraint."""

    value_fn: Any = field(default=None)
    ocpp_only: bool = False


BINARY_SENSOR_DESCRIPTIONS: tuple[RoulezElectriqueBinarySensorDescription, ...] = (
    RoulezElectriqueBinarySensorDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda c: bool(c.get("online")),
        ocpp_only=True,  # Only OCPP chargers have real-time connectivity
    ),
    RoulezElectriqueBinarySensorDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda c: bool(c.get("charging")),
        ocpp_only=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities from a config entry."""
    coordinator: RoulezElectriqueCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[RoulezElectriqueBinarySensor] = []
    for charger_id, charger_data in (coordinator.data or {}).items():
        is_ocpp = bool(charger_data.get("is_ocpp"))
        for description in BINARY_SENSOR_DESCRIPTIONS:
            if description.ocpp_only and not is_ocpp:
                continue  # Skip OCPP-only sensors for non-OCPP chargers
            entities.append(
                RoulezElectriqueBinarySensor(coordinator, charger_id, description)
            )

    async_add_entities(entities)


class RoulezElectriqueBinarySensor(RoulezElectriqueEntity, BinarySensorEntity):
    """A binary sensor entity for one boolean state on one charger."""

    entity_description: RoulezElectriqueBinarySensorDescription

    def __init__(
        self,
        coordinator: RoulezElectriqueCoordinator,
        charger_id: int,
        description: RoulezElectriqueBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, charger_id)
        self.entity_description = description
        self._attr_unique_id = f"{charger_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the boolean value of this sensor."""
        charger = self._charger_data
        if not charger:
            return None
        return self.entity_description.value_fn(charger)
