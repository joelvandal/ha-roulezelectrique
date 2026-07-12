"""Sensor platform for the Roulez Électrique integration.

One device per charger; sensors per charger:
  - Power (kW)                device_class=power,      state_class=measurement
  - Session energy (kWh)      device_class=energy,     state_class=total_increasing
  - Status (enum)             device_class=enum
  - Current (A)               device_class=current,    state_class=measurement
  - Voltage (V)               device_class=voltage,    state_class=measurement
  - Last seen (timestamp)     device_class=timestamp

Plus a set of optional sensors created only for the vendors that can report
them (Lifetime energy/sessions, Temperature, Battery %, Measured current,
Last connection, Session start, Speed/Range added, Connection type, VIN — see
SENSOR_DESCRIPTIONS below). Entity creation for these is DATA-DRIVEN: it reads
the server's per-charger `capabilities` list (see async_setup_entry). The
original six sensors above are ALWAYS created for every charger — never
gated on `capabilities` — for registry compatibility with every published
<=0.3.x install (see LEGACY_SENSOR_KEYS). Older servers that don't send
`capabilities` simply never get any of the new sensors.

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
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfPower,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
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
    """Typed description with a value_fn to extract from the charger dict.

    `capability` names the server `capabilities` entry that gates this
    sensor's creation (see async_setup_entry). It is independent of `key` —
    several capability strings don't match their sensor key 1:1 (e.g. the
    session-energy sensor's key is "energy_kwh" but its capability is
    "energy_session").
    """

    value_fn: Any = field(default=None)
    capability: str | None = field(default=None)


# The six sensors that existed before per-charger `capabilities` was added to
# the server response. Every published release up to and including 0.3.x
# creates these UNCONDITIONALLY for every charger, so every installed charger
# already has registry entries (unique_id `{charger_id}_{key}`) for all six,
# regardless of vendor. `capabilities` NEVER gates these six, in either
# direction — not on an older server (no `capabilities` key at all) and not
# on a newer server whose `capabilities` list omits one of them (e.g. Tesla/
# Sigenergy AC/DC/FLO never had "energy_session"/"current"/"voltage").
# Gating them would silently drop a pre-existing registry entry on upgrade;
# Home Assistant does not auto-remove orphaned entries, so it would become a
# permanently-unavailable ghost entity breaking existing dashboards/
# automations. `capabilities` only ever gates the NEW sensor keys added
# after this set — see async_setup_entry.
LEGACY_SENSOR_KEYS = frozenset(
    {"power_kw", "energy_kwh", "status", "current_a", "voltage_v", "last_session"}
)

# The other HALF of the two-repo capability-name contract: this MUST mirror
# the CAP_* constants in HomeAssistantController::capabilitiesFor()
# (dashboard/src/app/Http/Controllers/Api/HomeAssistantController.php). Every
# `capability` value used by a RoulezElectriqueSensorDescription below must
# be a member of this set (asserted by a test) — a rename on the server side
# that isn't mirrored here would silently stop that sensor from ever being
# created.
KNOWN_CAPABILITIES = frozenset(
    {
        "energy_lifetime",
        "status",
        "last_session",
        "power",
        "energy_session",
        "current",
        "voltage",
        "last_connection",
        "session_start",
        "temperature",
        "soc",
        "draw_current",
        "connection_type",
        "charging_speed",
        "added_range",
        "vin",
    }
)

# Sensor keys backed by live/near-real-time telemetry: unavailable when the
# charger is stale or offline, same rule as the original four telemetry
# sensors. Informational/DB-backed sensors (lifetime totals, last connection,
# session start, VIN, connection type) are deliberately NOT in this set so
# they stay readable even while the charger is offline.
STALE_GATED_SENSOR_KEYS = frozenset(
    {
        "power_kw",
        "energy_kwh",
        "current_a",
        "voltage_v",
        "temperature_c",
        "soc_percent",
        "draw_current_a",
        "charging_speed_kmh",
        "added_range_km",
    }
)


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


def _lifetime_energy(c: dict) -> float | None:
    v = c.get("lifetime_energy_kwh")
    return round(float(v), 3) if v is not None else None


def _lifetime_sessions(c: dict) -> int | None:
    v = c.get("lifetime_sessions")
    return int(v) if v is not None else None


def _temperature(c: dict) -> float | None:
    v = c.get("temperature_c")
    return round(float(v), 1) if v is not None else None


def _soc(c: dict) -> float | None:
    v = c.get("soc_percent")
    return round(float(v), 1) if v is not None else None


def _draw_current(c: dict) -> float | None:
    v = c.get("draw_current_a")
    return round(float(v), 2) if v is not None else None


def _charging_speed(c: dict) -> float | None:
    v = c.get("charging_speed_kmh")
    return round(float(v), 1) if v is not None else None


def _added_range(c: dict) -> float | None:
    v = c.get("added_range_km")
    return round(float(v), 1) if v is not None else None


def _connection_type(c: dict) -> str | None:
    v = c.get("connection_type")
    return str(v) if v else None


def _vin(c: dict) -> str | None:
    v = c.get("vin")
    return str(v) if v else None


def _parse_timestamp(c: dict, key: str) -> datetime | None:
    raw = c.get(key)
    if not raw:
        return None
    try:
        return dt_util.parse_datetime(raw)
    except (ValueError, TypeError):
        return None


def _last_connection_at(c: dict) -> datetime | None:
    return _parse_timestamp(c, "last_connection_at")


def _session_started_at(c: dict) -> datetime | None:
    return _parse_timestamp(c, "session_started_at")


SENSOR_DESCRIPTIONS: tuple[RoulezElectriqueSensorDescription, ...] = (
    RoulezElectriqueSensorDescription(
        key="power_kw",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        value_fn=_kw,
        capability="power",
    ),
    RoulezElectriqueSensorDescription(
        key="energy_kwh",
        translation_key="energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=_kwh,
        capability="energy_session",
    ),
    RoulezElectriqueSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=VALID_STATUSES,
        value_fn=_status,
        capability="status",
    ),
    RoulezElectriqueSensorDescription(
        key="current_a",
        translation_key="current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        value_fn=_current,
        capability="current",
    ),
    RoulezElectriqueSensorDescription(
        key="voltage_v",
        translation_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        value_fn=_voltage,
        capability="voltage",
    ),
    RoulezElectriqueSensorDescription(
        key="last_session",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last_seen,
        capability="last_session",
    ),
    # ── Optional, capability-gated sensors ──────────────────────────────
    # lifetime_energy_kwh/lifetime_sessions use state_class=TOTAL, not
    # TOTAL_INCREASING: charger_aggregates is a full recompute from
    # report_entries every 15 minutes, and report_entries can SHRINK
    # (sessions:dedupe --apply, orphan pruning, manual corrections). A
    # decrease on a TOTAL_INCREASING sensor is read by Home Assistant as a
    # meter reset and corrupts Energy-dashboard long-term statistics; TOTAL
    # tolerates a downward correction without misinterpreting it as a reset,
    # and (device_class=ENERGY + state_class=TOTAL) is still a valid Energy
    # dashboard source.
    RoulezElectriqueSensorDescription(
        key="lifetime_energy_kwh",
        translation_key="lifetime_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=_lifetime_energy,
        capability="energy_lifetime",
    ),
    RoulezElectriqueSensorDescription(
        key="lifetime_sessions",
        translation_key="lifetime_sessions",
        state_class=SensorStateClass.TOTAL,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_lifetime_sessions,
        capability="energy_lifetime",
    ),
    RoulezElectriqueSensorDescription(
        key="temperature_c",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_temperature,
        capability="temperature",
    ),
    RoulezElectriqueSensorDescription(
        key="soc_percent",
        translation_key="soc",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=_soc,
        capability="soc",
    ),
    RoulezElectriqueSensorDescription(
        key="draw_current_a",
        translation_key="draw_current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        value_fn=_draw_current,
        capability="draw_current",
    ),
    RoulezElectriqueSensorDescription(
        key="last_connection_at",
        translation_key="last_connection",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_last_connection_at,
        capability="last_connection",
    ),
    RoulezElectriqueSensorDescription(
        key="session_started_at",
        translation_key="session_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_session_started_at,
        capability="session_start",
    ),
    RoulezElectriqueSensorDescription(
        key="charging_speed_kmh",
        translation_key="charging_speed",
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        value_fn=_charging_speed,
        capability="charging_speed",
    ),
    RoulezElectriqueSensorDescription(
        key="added_range_km",
        translation_key="added_range",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        value_fn=_added_range,
        capability="added_range",
    ),
    RoulezElectriqueSensorDescription(
        key="connection_type",
        translation_key="connection_type",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_connection_type,
        capability="connection_type",
    ),
    RoulezElectriqueSensorDescription(
        key="vin",
        translation_key="vin",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_vin,
        capability="vin",
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

    # Per-charger sensors.
    #
    # The original six (LEGACY_SENSOR_KEYS) are ALWAYS created, for every
    # charger, regardless of `capabilities` — see the comment on
    # LEGACY_SENSOR_KEYS. This is required for registry compatibility with
    # every published <=0.3.x install, which created them unconditionally.
    #
    # Every OTHER sensor is gated on the server's per-charger `capabilities`
    # list, so it is created up front even behind a cold cache (rather than
    # hidden until the first non-null read). An older server that omits
    # `capabilities` entirely never gets these new sensors at all.
    charger_map = coordinator.data.chargers if coordinator.data else {}
    for charger_id, charger_data in charger_map.items():
        capabilities = charger_data.get("capabilities")
        for description in SENSOR_DESCRIPTIONS:
            if description.key in LEGACY_SENSOR_KEYS:
                entities.append(
                    RoulezElectriqueSensor(coordinator, charger_id, description)
                )
                continue
            if capabilities is None:
                continue
            if description.capability is not None and description.capability not in capabilities:
                continue
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
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Attach the server's vendor-diagnostics dict to the status sensor.

        Cryptic vendor codes (Tesla wall-connector state/fault codes,
        Sigenergy AC/DC diagnostics, …) have no dedicated sensor — they ride
        as extra state attributes on the status sensor instead. Omitted
        entirely when the server sends no diagnostics for this charger (older
        server, or a vendor with nothing to report).
        """
        if self.entity_description.key != "status":
            return None
        diagnostics = self._charger_data.get("diagnostics")
        return dict(diagnostics) if diagnostics else None

    @property
    def available(self) -> bool:
        """Sensors become unavailable when the coordinator fails or charger is stale."""
        if not super().available:
            return False
        charger = self._charger_data
        # Stale live data: sensors backed by live/near-real-time telemetry are
        # unavailable when the charger hasn't sent data recently (stale=True)
        # or is offline. Informational sensors (status, last-session,
        # lifetime totals, last connection, session start, VIN, connection
        # type) remain available even when stale — see STALE_GATED_SENSOR_KEYS.
        if self.entity_description.key in STALE_GATED_SENSOR_KEYS:
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
    # state_class=TOTAL, not TOTAL_INCREASING: backed by ChargerStats::compute
    # over report_entries, which can shrink (dedupe/corrections) — same
    # downward-correction risk as the per-charger lifetime_energy_kwh sensor
    # above, so it needs the same tolerant state class.
    RoulezElectriqueAccountSensorDescription(
        key="account_energy_kwh_lifetime",
        translation_key="account_energy_kwh_lifetime",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
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
