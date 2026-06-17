"""Sensor platform for the Roulez Électrique (BETA) integration.

One device per charger; sensors per charger:
  - Power (kW)                device_class=power,      state_class=measurement
  - Session energy (kWh)      device_class=energy,     state_class=total_increasing
  - Status (enum)             device_class=enum
  - Current (A)               device_class=current,    state_class=measurement
  - Voltage (V)               device_class=voltage,    state_class=measurement
  - Last seen (timestamp)     device_class=timestamp

All sensors inherit availability from the base entity + coordinator success.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import RoulezElectriqueCoordinator
from .entity import RoulezElectriqueEntity

_LOGGER = logging.getLogger(__name__)

# Known OCPP/charger status values reported by the platform
VALID_STATUSES = [
    "Available",
    "Preparing",
    "Charging",
    "SuspendedEVSE",
    "SuspendedEV",
    "Finishing",
    "Reserved",
    "Unavailable",
    "Faulted",
]


@dataclass(frozen=True)
class RoulezElectriqueSensorDescription(SensorEntityDescription):
    """Typed description with a value_fn to extract from the charger dict."""

    value_fn: Any = field(default=None)


def _kw(c: dict) -> float | None:
    v = c.get("power_kw")
    return round(float(v), 3) if v is not None else None


def _kwh(c: dict) -> float | None:
    v = c.get("energy_kwh")
    return round(float(v), 3) if v is not None else None


def _current(c: dict) -> float | None:
    v = c.get("current_a")
    return round(float(v), 2) if v is not None else None


def _voltage(c: dict) -> float | None:
    v = c.get("voltage_v")
    return round(float(v), 1) if v is not None else None


def _status(c: dict) -> str | None:
    return c.get("status")


def _last_seen(c: dict) -> datetime | None:
    # Use last_session.occurred_at if available, otherwise None
    ls = c.get("last_session")
    if ls and ls.get("occurred_at"):
        try:
            return dt_util.parse_datetime(ls["occurred_at"])
        except (ValueError, TypeError):
            return None
    return None


SENSOR_DESCRIPTIONS: tuple[RoulezElectriqueSensorDescription, ...] = (
    RoulezElectriqueSensorDescription(
        key="power_kw",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        value_fn=_kw,
    ),
    RoulezElectriqueSensorDescription(
        key="energy_kwh",
        translation_key="energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=_kwh,
    ),
    RoulezElectriqueSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=VALID_STATUSES,
        value_fn=_status,
    ),
    RoulezElectriqueSensorDescription(
        key="current_a",
        translation_key="current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        value_fn=_current,
    ),
    RoulezElectriqueSensorDescription(
        key="voltage_v",
        translation_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        value_fn=_voltage,
    ),
    RoulezElectriqueSensorDescription(
        key="last_session",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last_seen,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from a config entry."""
    coordinator: RoulezElectriqueCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[RoulezElectriqueSensor] = []
    for charger_id in coordinator.data or {}:
        for description in SENSOR_DESCRIPTIONS:
            entities.append(
                RoulezElectriqueSensor(coordinator, charger_id, description)
            )

    async_add_entities(entities)


class RoulezElectriqueSensor(RoulezElectriqueEntity, SensorEntity):
    """A sensor entity for one metric on one charger."""

    entity_description: RoulezElectriqueSensorDescription

    def __init__(
        self,
        coordinator: RoulezElectriqueCoordinator,
        charger_id: int,
        description: RoulezElectriqueSensorDescription,
    ) -> None:
        super().__init__(coordinator, charger_id)
        self.entity_description = description
        self._attr_unique_id = f"{charger_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        """Return the sensor value extracted from coordinator data."""
        charger = self._charger_data
        if not charger:
            return None
        return self.entity_description.value_fn(charger)

    @property
    def available(self) -> bool:
        """Sensors become unavailable when the coordinator fails or charger is stale."""
        if not super().available:
            return False
        charger = self._charger_data
        # Stale live data: sensors that rely on OCPP telemetry are unavailable
        # when the charger hasn't sent data recently (stale=True). The status
        # and last_seen sensors remain available even when stale.
        if self.entity_description.key in ("power_kw", "energy_kwh", "current_a", "voltage_v"):
            if charger.get("stale") or not charger.get("online"):
                return False
        return True
