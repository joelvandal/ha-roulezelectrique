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
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import CoordinatorData, RoulezElectriqueCoordinator
from .entity import RoulezElectriqueEntity

_LOGGER = logging.getLogger(__name__)

# Raw OCPP/charger status string (as reported by the platform) → HA enum slug.
# For an HA ENUM sensor the emitted state MUST equal a translation key, and
# translation state keys must match [a-z0-9-_]+ — so we slugify both here and
# in the translation files. Lookup is case-tolerant (keyed on the lowercased
# raw value).
STATUS_SLUGS = {
    "available": "available",
    "preparing": "preparing",
    "charging": "charging",
    "suspendedevse": "suspended_evse",
    "suspendedev": "suspended_ev",
    "finishing": "finishing",
    "reserved": "reserved",
    "unavailable": "unavailable",
    "faulted": "faulted",
}

# Enum options the status sensor can report — exactly the set of slug values.
VALID_STATUSES = list(STATUS_SLUGS.values())


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
    # Map the raw OCPP status string to its enum slug (case-tolerant). The
    # emitted slug must be one of VALID_STATUSES so the ENUM sensor stays valid;
    # unknown/None values report as unknown (None).
    raw = c.get("status")
    if not raw:
        return None
    return STATUS_SLUGS.get(str(raw).lower())


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

    entities: list[RoulezElectriqueSensor | RoulezElectriqueAccountSensor] = []

    # Per-charger sensors
    charger_map = coordinator.data.chargers if coordinator.data else {}
    for charger_id in charger_map:
        for description in SENSOR_DESCRIPTIONS:
            entities.append(
                RoulezElectriqueSensor(coordinator, charger_id, description)
            )

    # Account-level sensors (one "Account" device) — only when the server
    # returns the account block. Tolerates an older server that omits it.
    if coordinator.data and coordinator.data.account is not None:
        for description in ACCOUNT_SENSOR_DESCRIPTIONS:
            entities.append(RoulezElectriqueAccountSensor(coordinator, description))

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


# ---------------------------------------------------------------------------
# Account-level sensors
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RoulezElectriqueAccountSensorDescription(SensorEntityDescription):
    """Description for an account-level sensor with a value extractor."""

    value_fn: Any = field(default=None)


def _account_rewards_total(a: dict) -> float | None:
    v = a.get("rewards", {}).get("total")
    return round(float(v), 2) if v is not None else None


def _account_rewards_client(a: dict) -> float | None:
    v = a.get("rewards", {}).get("client")
    return round(float(v), 2) if v is not None else None


def _account_rewards_installer(a: dict) -> float | None:
    v = a.get("rewards", {}).get("installer")
    return round(float(v), 2) if v is not None else None


def _account_rewards_referee(a: dict) -> float | None:
    v = a.get("rewards", {}).get("referee")
    return round(float(v), 2) if v is not None else None


def _account_rewards_referrer(a: dict) -> float | None:
    v = a.get("rewards", {}).get("referrer")
    return round(float(v), 2) if v is not None else None


def _account_invitations_pending(a: dict) -> int | None:
    v = a.get("invitations", {}).get("pending")
    return int(v) if v is not None else None


def _account_invitations_accepted(a: dict) -> int | None:
    v = a.get("invitations", {}).get("accepted")
    return int(v) if v is not None else None


def _account_invitations_referred(a: dict) -> int | None:
    v = a.get("invitations", {}).get("referred")
    return int(v) if v is not None else None


def _account_energy_kwh_lifetime(a: dict) -> float | None:
    v = a.get("energy_kwh_lifetime")
    return round(float(v), 3) if v is not None else None


def _account_charger_count(a: dict) -> int | None:
    v = a.get("charger_count")
    return int(v) if v is not None else None


ACCOUNT_SENSOR_DESCRIPTIONS: tuple[RoulezElectriqueAccountSensorDescription, ...] = (
    RoulezElectriqueAccountSensorDescription(
        key="account_rewards_total",
        translation_key="account_rewards_total",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CAD",
        value_fn=_account_rewards_total,
    ),
    RoulezElectriqueAccountSensorDescription(
        key="account_rewards_client",
        translation_key="account_rewards_client",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CAD",
        value_fn=_account_rewards_client,
    ),
    RoulezElectriqueAccountSensorDescription(
        key="account_rewards_installer",
        translation_key="account_rewards_installer",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CAD",
        value_fn=_account_rewards_installer,
    ),
    RoulezElectriqueAccountSensorDescription(
        key="account_rewards_referee",
        translation_key="account_rewards_referee",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CAD",
        value_fn=_account_rewards_referee,
    ),
    RoulezElectriqueAccountSensorDescription(
        key="account_rewards_referrer",
        translation_key="account_rewards_referrer",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="CAD",
        value_fn=_account_rewards_referrer,
    ),
    RoulezElectriqueAccountSensorDescription(
        key="account_invitations_pending",
        translation_key="account_invitations_pending",
        state_class=SensorStateClass.TOTAL,
        value_fn=_account_invitations_pending,
    ),
    RoulezElectriqueAccountSensorDescription(
        key="account_invitations_accepted",
        translation_key="account_invitations_accepted",
        state_class=SensorStateClass.TOTAL,
        value_fn=_account_invitations_accepted,
    ),
    RoulezElectriqueAccountSensorDescription(
        key="account_invitations_referred",
        translation_key="account_invitations_referred",
        state_class=SensorStateClass.TOTAL,
        value_fn=_account_invitations_referred,
    ),
    RoulezElectriqueAccountSensorDescription(
        key="account_energy_kwh_lifetime",
        translation_key="account_energy_kwh_lifetime",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=_account_energy_kwh_lifetime,
    ),
    RoulezElectriqueAccountSensorDescription(
        key="account_charger_count",
        translation_key="account_charger_count",
        state_class=SensorStateClass.TOTAL,
        value_fn=_account_charger_count,
    ),
)


class RoulezElectriqueAccountSensor(
    CoordinatorEntity[RoulezElectriqueCoordinator], SensorEntity
):
    """A sensor entity for one account-level metric (one device for the account)."""

    _attr_has_entity_name = True

    _ACCOUNT_DEVICE_INFO = None  # class-level cache; populated on first instantiation

    entity_description: RoulezElectriqueAccountSensorDescription

    def __init__(
        self,
        coordinator: RoulezElectriqueCoordinator,
        description: RoulezElectriqueAccountSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        # Stable unique_id: use the key directly — it already carries the
        # "account_" prefix (e.g. "account_rewards_total"), so prefixing it
        # again would produce "account_account_rewards_total" and cause HA to
        # discard every duplicate as "ID already exists".
        self._attr_unique_id = description.key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "account")},
            name="Roulez Électrique",
            model="Account",
        )

    @property
    def _account_data(self) -> dict[str, Any] | None:
        """Return the account block from coordinator data, or None."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.account

    @property
    def native_value(self) -> Any:
        """Return the sensor value extracted from the account block."""
        acct = self._account_data
        if acct is None:
            return None
        return self.entity_description.value_fn(acct)

    @property
    def available(self) -> bool:
        """Unavailable when coordinator failed or server omits the account block."""
        return (
            super().available
            and self.coordinator.last_update_success
            and self._account_data is not None
        )
