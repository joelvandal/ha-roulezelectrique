"""Tests for Roulez Électrique account-level sensor entities.

Covers:
  - Account device created with correct DeviceInfo (identifiers, name, model)
  - All 10 account sensors created from a full state envelope
  - Correct device_class / state_class / unit per sensor
  - Correct native_value extracted from the account block
  - Availability logic:
      - Available when coordinator succeeds + account block present
      - Unavailable when coordinator.last_update_success is False
      - Unavailable when account block is None (older server)
  - Absent account block → no account sensors created (no crash)
  - No account sensors created from an older-server envelope (missing key)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.roulezelectrique.coordinator import CoordinatorData
from custom_components.roulezelectrique.sensor import (
    ACCOUNT_SENSOR_DESCRIPTIONS,
    RoulezElectriqueAccountSensor,
    async_setup_entry,
)

from .conftest import ACCOUNT_DATA, OCPP_CHARGER, STATE_ENVELOPE_NO_ACCOUNT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_account_sensor(
    account: dict[str, Any] | None,
    description_key: str,
) -> RoulezElectriqueAccountSensor:
    """Build an account sensor entity for a given description key."""
    coordinator = MagicMock()
    coordinator.data = CoordinatorData(chargers={}, account=account)
    coordinator.last_update_success = True
    coordinator._listeners = {}

    description = next(d for d in ACCOUNT_SENSOR_DESCRIPTIONS if d.key == description_key)
    sensor = RoulezElectriqueAccountSensor(coordinator, description)
    return sensor


def _make_coordinator_with_data(
    account: dict[str, Any] | None,
    chargers: dict[int, dict[str, Any]] | None = None,
) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = CoordinatorData(
        chargers=chargers or {1: OCPP_CHARGER},
        account=account,
    )
    coordinator.last_update_success = True
    coordinator._listeners = {}
    return coordinator


# ---------------------------------------------------------------------------
# Entity creation via async_setup_entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_account_sensors_created_when_account_present():
    """async_setup_entry creates 10 account sensors when account block is present."""
    from custom_components.roulezelectrique.const import DOMAIN

    coordinator = _make_coordinator_with_data(account=ACCOUNT_DATA, chargers={})

    hass = MagicMock()
    entry_id = "test_entry"
    hass.data = {DOMAIN: {entry_id: coordinator}}
    entry = MagicMock()
    entry.entry_id = entry_id

    added_entities: list = []

    def add_entities(entities, **kwargs):
        added_entities.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    account_sensors = [
        e for e in added_entities if isinstance(e, RoulezElectriqueAccountSensor)
    ]
    # Expect all 10 account sensor descriptions to be instantiated.
    assert len(account_sensors) == len(ACCOUNT_SENSOR_DESCRIPTIONS)


@pytest.mark.asyncio
async def test_no_account_sensors_when_account_absent():
    """async_setup_entry creates zero account sensors when account block is None."""
    from custom_components.roulezelectrique.const import DOMAIN

    coordinator = _make_coordinator_with_data(account=None, chargers={})

    hass = MagicMock()
    entry_id = "test_entry"
    hass.data = {DOMAIN: {entry_id: coordinator}}
    entry = MagicMock()
    entry.entry_id = entry_id

    added_entities: list = []

    def add_entities(entities, **kwargs):
        added_entities.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    account_sensors = [
        e for e in added_entities if isinstance(e, RoulezElectriqueAccountSensor)
    ]
    assert len(account_sensors) == 0


# ---------------------------------------------------------------------------
# Device info
# ---------------------------------------------------------------------------


def test_account_sensor_device_info():
    """Account sensors share the (DOMAIN, 'account') device identifier."""
    from custom_components.roulezelectrique.const import DOMAIN

    sensor = _make_account_sensor(ACCOUNT_DATA, "account_rewards_total")
    device_info = sensor.device_info

    assert (DOMAIN, "account") in device_info["identifiers"]
    assert device_info.get("name") == "Roulez Électrique"
    assert device_info.get("model") == "Account"


def test_account_sensor_unique_id():
    """Each account sensor unique_id equals the description key exactly (no double-prefix).

    The description key already starts with 'account_' (e.g. 'account_rewards_total'),
    so the unique_id must NOT prepend another 'account_' — that would produce
    'account_account_rewards_total' which HA rejects as a duplicate ID.
    """
    sensor = _make_account_sensor(ACCOUNT_DATA, "account_rewards_total")
    assert sensor.unique_id == "account_rewards_total"


def test_all_account_sensor_unique_ids_are_distinct_and_non_doubled():
    """All 10 account sensors must have distinct unique_ids with no doubled segment.

    Regression test for the 'account_account_*' duplicate-ID bug: when the
    unique_id builder prepended 'account_' to a key that already started with
    'account_', HA discarded all sensors after the first with error
    'ID already exists — ignoring sensor.*'.
    """
    from custom_components.roulezelectrique.sensor import ACCOUNT_SENSOR_DESCRIPTIONS

    sensors = [
        _make_account_sensor(ACCOUNT_DATA, desc.key)
        for desc in ACCOUNT_SENSOR_DESCRIPTIONS
    ]
    unique_ids = [s.unique_id for s in sensors]

    # All must be distinct
    assert len(unique_ids) == len(set(unique_ids)), (
        f"Duplicate unique_ids found: {unique_ids}"
    )

    # None may have a doubled segment (e.g. 'account_account_' or 'rewards_rewards_')
    for uid in unique_ids:
        parts = uid.split("_")
        for i in range(len(parts) - 1):
            assert parts[i] != parts[i + 1], (
                f"unique_id '{uid}' has doubled segment '_{parts[i]}_'"
            )
        # Specifically guard against the known regression
        assert "account_account" not in uid, (
            f"unique_id '{uid}' contains double 'account_' prefix (regression)"
        )


# ---------------------------------------------------------------------------
# Rewards sensors — device_class / state_class / unit / value
# ---------------------------------------------------------------------------


def test_rewards_total_metadata():
    from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

    sensor = _make_account_sensor(ACCOUNT_DATA, "account_rewards_total")
    assert sensor.device_class == SensorDeviceClass.MONETARY
    assert sensor.state_class == SensorStateClass.TOTAL
    assert sensor.native_unit_of_measurement == "CAD"


def test_rewards_total_value():
    sensor = _make_account_sensor(ACCOUNT_DATA, "account_rewards_total")
    assert sensor.native_value == pytest.approx(19.50)


def test_rewards_client_value():
    sensor = _make_account_sensor(ACCOUNT_DATA, "account_rewards_client")
    assert sensor.native_value == pytest.approx(12.50)


def test_rewards_installer_value():
    sensor = _make_account_sensor(ACCOUNT_DATA, "account_rewards_installer")
    assert sensor.native_value == pytest.approx(5.00)


def test_rewards_referee_value():
    sensor = _make_account_sensor(ACCOUNT_DATA, "account_rewards_referee")
    assert sensor.native_value == pytest.approx(1.25)


def test_rewards_referrer_value():
    sensor = _make_account_sensor(ACCOUNT_DATA, "account_rewards_referrer")
    assert sensor.native_value == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# Invitations sensors
# ---------------------------------------------------------------------------


def test_invitations_pending_value():
    sensor = _make_account_sensor(ACCOUNT_DATA, "account_invitations_pending")
    assert sensor.native_value == 2


def test_invitations_accepted_value():
    sensor = _make_account_sensor(ACCOUNT_DATA, "account_invitations_accepted")
    assert sensor.native_value == 3


def test_invitations_referred_value():
    sensor = _make_account_sensor(ACCOUNT_DATA, "account_invitations_referred")
    assert sensor.native_value == 4


def test_invitations_no_device_class():
    """Invitation count sensors should have no energy/monetary device_class."""
    sensor = _make_account_sensor(ACCOUNT_DATA, "account_invitations_pending")
    # device_class must not be ENERGY or MONETARY — plain integer count
    assert sensor.device_class is None


# ---------------------------------------------------------------------------
# Lifetime energy sensor
# ---------------------------------------------------------------------------


def test_energy_kwh_lifetime_metadata():
    from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
    from homeassistant.const import UnitOfEnergy

    sensor = _make_account_sensor(ACCOUNT_DATA, "account_energy_kwh_lifetime")
    assert sensor.device_class == SensorDeviceClass.ENERGY
    assert sensor.state_class == SensorStateClass.TOTAL_INCREASING
    assert sensor.native_unit_of_measurement == UnitOfEnergy.KILO_WATT_HOUR


def test_energy_kwh_lifetime_value():
    sensor = _make_account_sensor(ACCOUNT_DATA, "account_energy_kwh_lifetime")
    assert sensor.native_value == pytest.approx(1234.567)


# ---------------------------------------------------------------------------
# Charger count sensor
# ---------------------------------------------------------------------------


def test_charger_count_value():
    sensor = _make_account_sensor(ACCOUNT_DATA, "account_charger_count")
    assert sensor.native_value == 2


def test_charger_count_no_device_class():
    sensor = _make_account_sensor(ACCOUNT_DATA, "account_charger_count")
    assert sensor.device_class is None


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_account_sensor_available_when_data_present():
    sensor = _make_account_sensor(ACCOUNT_DATA, "account_rewards_total")
    assert sensor.available is True


def test_account_sensor_unavailable_when_account_none():
    """Sensor unavailable when account block is None (older server)."""
    sensor = _make_account_sensor(None, "account_rewards_total")
    # Override last_update_success to True so only the None account triggers it
    sensor.coordinator.last_update_success = True
    assert sensor.available is False


def test_account_sensor_unavailable_when_coordinator_fails():
    """Sensor unavailable when coordinator last_update_success is False."""
    sensor = _make_account_sensor(ACCOUNT_DATA, "account_rewards_total")
    sensor.coordinator.last_update_success = False
    assert sensor.available is False


def test_account_sensor_returns_none_when_no_account():
    """native_value is None when the account block is absent."""
    sensor = _make_account_sensor(None, "account_rewards_total")
    assert sensor.native_value is None
