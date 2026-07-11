"""Binary sensor platform for the Roulez Électrique integration.

Up to three binary sensors per charger (see BINARY_SENSOR_DESCRIPTIONS below
for the exact per-vendor gating):
  - Online (connectivity) — every vendor; the server only populates a
    meaningful value for OCPP, Wallbox, AVE, Tesla and Sigenergy AC/DC.
  - Charging — all chargers.
  - Plugged in — Wallbox, AVE and Tesla only.
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
    """Description with value_fn and optional vendor constraint."""

    value_fn: Any = field(default=None)
    ocpp_only: bool = False
    # Non-empty tuple restricts entity creation to these vendors (server
    # `vendor` string). Empty tuple = created for every vendor.
    vendors: tuple[str, ...] = ()


BINARY_SENSOR_DESCRIPTIONS: tuple[RoulezElectriqueBinarySensorDescription, ...] = (
    RoulezElectriqueBinarySensorDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda c: bool(c.get("online")),
        # OCPP, Wallbox, AVE, Tesla and Sigenergy AC/DC all report real-time
        # connectivity. The ocpp_only flag is kept False so all vendors that
        # expose `online` benefit from this sensor — the server only
        # populates `online` with a meaningful value for vendors that have it.
        ocpp_only=False,
    ),
    RoulezElectriqueBinarySensorDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda c: bool(c.get("charging")),
        ocpp_only=False,
    ),
    RoulezElectriqueBinarySensorDescription(
        key="plugged_in",
        translation_key="plugged_in",
        device_class=BinarySensorDeviceClass.PLUG,
        # plugged_in is populated by the server for Wallbox, AVE and Tesla
        # only — the entity is skipped for all other vendors (OCPP has no
        # plug-detection concept here; Sigenergy AC/DC don't report it either).
        value_fn=lambda c: bool(c.get("plugged_in")) if c.get("plugged_in") is not None else None,
        vendors=("wallbox", "ave", "tesla"),
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
    charger_map = coordinator.data.chargers if coordinator.data else {}
    for charger_id, charger_data in charger_map.items():
        is_ocpp = bool(charger_data.get("is_ocpp"))
        vendor = charger_data.get("vendor")
        for description in BINARY_SENSOR_DESCRIPTIONS:
            if description.ocpp_only and not is_ocpp:
                continue  # Skip OCPP-only sensors for non-OCPP chargers
            if description.vendors and vendor not in description.vendors:
                continue  # Skip vendor-restricted sensors for other vendors
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
