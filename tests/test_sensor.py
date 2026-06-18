"""Tests for the Roulez Électrique sensor platform."""

from __future__ import annotations

from datetime import timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.roulezelectrique.const import DOMAIN
from custom_components.roulezelectrique.sensor import (
    SENSOR_DESCRIPTIONS,
    RoulezElectriqueSensor,
)

from .conftest import NON_OCPP_CHARGER, OCPP_CHARGER, OCPP_CHARGER_CHARGING


def _make_coordinator(charger_data: dict[int, dict[str, Any]]):
    """Create a minimal coordinator mock with given charger map."""
    from custom_components.roulezelectrique.coordinator import CoordinatorData

    coordinator = MagicMock()
    coordinator.data = CoordinatorData(chargers=charger_data, account=None)
    # Satisfy CoordinatorEntity.available (needs last_update_success)
    coordinator.last_update_success = True
    coordinator._listeners = {}
    return coordinator


def _make_sensor(charger_data: dict[str, Any], description_key: str) -> RoulezElectriqueSensor:
    """Build a sensor entity for a given description key."""
    charger_id = charger_data["id"]
    coordinator = _make_coordinator({charger_id: charger_data})
    description = next(d for d in SENSOR_DESCRIPTIONS if d.key == description_key)
    sensor = RoulezElectriqueSensor(coordinator, charger_id, description)
    return sensor


# ---------------------------------------------------------------------------
# Device class / state class / units
# ---------------------------------------------------------------------------


def test_power_sensor_metadata():
    from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
    from homeassistant.const import UnitOfPower

    sensor = _make_sensor(OCPP_CHARGER, "power_kw")
    assert sensor.device_class == SensorDeviceClass.POWER
    assert sensor.state_class == SensorStateClass.MEASUREMENT
    assert sensor.native_unit_of_measurement == UnitOfPower.KILO_WATT


def test_energy_sensor_metadata():
    from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
    from homeassistant.const import UnitOfEnergy

    sensor = _make_sensor(OCPP_CHARGER_CHARGING, "energy_kwh")
    assert sensor.device_class == SensorDeviceClass.ENERGY
    assert sensor.state_class == SensorStateClass.TOTAL_INCREASING
    assert sensor.native_unit_of_measurement == UnitOfEnergy.KILO_WATT_HOUR


def test_energy_sensor_value():
    sensor = _make_sensor(OCPP_CHARGER_CHARGING, "energy_kwh")
    assert sensor.native_value == pytest.approx(2.1)


def test_current_sensor_metadata():
    from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
    from homeassistant.const import UnitOfElectricCurrent

    sensor = _make_sensor(OCPP_CHARGER_CHARGING, "current_a")
    assert sensor.device_class == SensorDeviceClass.CURRENT
    assert sensor.state_class == SensorStateClass.MEASUREMENT
    assert sensor.native_unit_of_measurement == UnitOfElectricCurrent.AMPERE
    assert sensor.native_value == pytest.approx(30.0)


def test_voltage_sensor_metadata():
    from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
    from homeassistant.const import UnitOfElectricPotential

    sensor = _make_sensor(OCPP_CHARGER_CHARGING, "voltage_v")
    assert sensor.device_class == SensorDeviceClass.VOLTAGE
    assert sensor.state_class == SensorStateClass.MEASUREMENT
    assert sensor.native_unit_of_measurement == UnitOfElectricPotential.VOLT


def test_status_sensor_metadata():
    from homeassistant.components.sensor import SensorDeviceClass

    sensor = _make_sensor(OCPP_CHARGER, "status")
    assert sensor.device_class == SensorDeviceClass.ENUM
    # ENUM sensors must emit one of the declared option slugs; the raw OCPP
    # "Available" status maps to the "available" slug (matches the translation
    # key, which Hassfest requires to be a lowercase slug).
    assert sensor.native_value == "available"
    assert sensor.native_value in sensor.options


def test_last_seen_sensor():
    from homeassistant.components.sensor import SensorDeviceClass

    sensor = _make_sensor(OCPP_CHARGER, "last_session")
    assert sensor.device_class == SensorDeviceClass.TIMESTAMP
    # Should parse as a datetime
    val = sensor.native_value
    assert val is not None
    assert val.year == 2026


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_power_sensor_unavailable_when_stale():
    """Power sensor is unavailable when charger data is stale."""
    stale_charger = {**OCPP_CHARGER, "stale": True, "online": False}
    sensor = _make_sensor(stale_charger, "power_kw")
    assert sensor.available is False


def test_power_sensor_unavailable_when_offline():
    offline_charger = {**OCPP_CHARGER, "online": False, "stale": False}
    sensor = _make_sensor(offline_charger, "power_kw")
    assert sensor.available is False


def test_status_sensor_available_when_offline():
    """Status sensor remains available even when charger is offline."""
    offline_charger = {**OCPP_CHARGER, "online": False}
    sensor = _make_sensor(offline_charger, "status")
    # Status does not require online
    assert sensor.available is True


def test_sensor_unavailable_when_coordinator_has_no_data():
    """Entity unavailable when coordinator.data is None or charger missing."""
    charger_id = 1
    coordinator = MagicMock()
    coordinator.data = None
    coordinator.last_update_success = True
    description = next(d for d in SENSOR_DESCRIPTIONS if d.key == "power_kw")
    sensor = RoulezElectriqueSensor(coordinator, charger_id, description)
    assert sensor.available is False


# ---------------------------------------------------------------------------
# Non-OCPP charger sensors
# ---------------------------------------------------------------------------


def test_non_ocpp_power_sensor_returns_none():
    """Non-OCPP charger has no live power data → None."""
    sensor = _make_sensor(NON_OCPP_CHARGER, "power_kw")
    assert sensor.native_value is None


def test_non_ocpp_last_session_available():
    """Non-OCPP charger has last_session populated."""
    sensor = _make_sensor(NON_OCPP_CHARGER, "last_session")
    val = sensor.native_value
    assert val is not None
    assert val.year == 2026
