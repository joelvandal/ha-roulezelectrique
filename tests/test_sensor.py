"""Tests for the Roulez Électrique sensor platform."""

from __future__ import annotations

from datetime import timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.roulezelectrique.const import DOMAIN
from custom_components.roulezelectrique.coordinator import CoordinatorData
from custom_components.roulezelectrique.sensor import (
    KNOWN_CAPABILITIES,
    LEGACY_SENSOR_KEYS,
    SENSOR_DESCRIPTIONS,
    RoulezElectriqueSensor,
    async_setup_entry,
)

from .conftest import (
    AVE_CHARGER,
    BASELINE_CHARGER_FULL,
    NON_OCPP_CHARGER,
    OCPP_CHARGER,
    OCPP_CHARGER_CHARGING,
    OCPP_CHARGER_FULL,
    OCPP_CHARGER_WITH_CONFIG_DIAGNOSTICS,
    SIGENERGY_AC_CHARGER_FULL,
    SIGENERGY_DC_CHARGER,
    TESLA_CHARGER_FULL,
    TESLA_CHARGER_LIVE,
    WALLBOX_CHARGER_FULL,
)


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


# ---------------------------------------------------------------------------
# AVE / Tesla / Sigenergy DC — same sensor set as OCPP/Wallbox, no code
# changes required (SENSOR_DESCRIPTIONS is fully vendor-agnostic).
# ---------------------------------------------------------------------------


def test_ave_charger_yields_same_sensor_set_with_live_values():
    power = _make_sensor(AVE_CHARGER, "power_kw")
    assert power.native_value == pytest.approx(7.2)
    assert power.available is True

    energy = _make_sensor(AVE_CHARGER, "energy_kwh")
    assert energy.native_value == pytest.approx(5.5)

    current = _make_sensor(AVE_CHARGER, "current_a")
    assert current.native_value == pytest.approx(32.0)

    status = _make_sensor(AVE_CHARGER, "status")
    # AVE's gunStatus vocabulary passes through as-is — same OCPP status slugs.
    assert status.native_value == "charging"
    assert status.native_value in status.options


def test_tesla_charger_yields_same_sensor_set_with_live_values():
    power = _make_sensor(TESLA_CHARGER_LIVE, "power_kw")
    assert power.native_value == pytest.approx(7.2)
    assert power.available is True

    status = _make_sensor(TESLA_CHARGER_LIVE, "status")
    assert status.native_value == "charging"
    assert status.native_value in status.options


def test_sigenergy_dc_charger_yields_same_sensor_set():
    status = _make_sensor(SIGENERGY_DC_CHARGER, "status")
    assert status.native_value == "charging"
    assert status.native_value in status.options

    # DC has no live power/current/energy reading — reports None, not an error.
    power = _make_sensor(SIGENERGY_DC_CHARGER, "power_kw")
    assert power.native_value is None


# ---------------------------------------------------------------------------
# New sensor values/metadata
# ---------------------------------------------------------------------------


def test_lifetime_energy_sensor_metadata_and_value():
    from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
    from homeassistant.const import UnitOfEnergy

    sensor = _make_sensor(OCPP_CHARGER_FULL, "lifetime_energy_kwh")
    assert sensor.device_class == SensorDeviceClass.ENERGY
    # TOTAL, not TOTAL_INCREASING: the server value is a full recompute that
    # can occasionally decrease (dedupe/corrections) — TOTAL_INCREASING would
    # make HA treat a decrease as a meter reset and corrupt Energy-dashboard
    # long-term statistics.
    assert sensor.state_class == SensorStateClass.TOTAL
    assert sensor.native_unit_of_measurement == UnitOfEnergy.KILO_WATT_HOUR
    assert sensor.native_value == pytest.approx(512.75)


def test_lifetime_sessions_sensor_value():
    sensor = _make_sensor(OCPP_CHARGER_FULL, "lifetime_sessions")
    assert sensor.native_value == 42


def test_temperature_sensor_metadata_and_value():
    from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
    from homeassistant.const import UnitOfTemperature
    from homeassistant.helpers.entity import EntityCategory

    sensor = _make_sensor(OCPP_CHARGER_FULL, "temperature_c")
    assert sensor.device_class == SensorDeviceClass.TEMPERATURE
    assert sensor.state_class == SensorStateClass.MEASUREMENT
    assert sensor.native_unit_of_measurement == UnitOfTemperature.CELSIUS
    assert sensor.entity_category == EntityCategory.DIAGNOSTIC
    assert sensor.native_value == pytest.approx(28.4)


def test_soc_sensor_metadata_and_value():
    from homeassistant.components.sensor import SensorDeviceClass
    from homeassistant.const import PERCENTAGE

    sensor = _make_sensor(OCPP_CHARGER_FULL, "soc_percent")
    assert sensor.device_class == SensorDeviceClass.BATTERY
    assert sensor.native_unit_of_measurement == PERCENTAGE
    assert sensor.native_value == pytest.approx(63.0)


def test_draw_current_sensor_reads_its_own_field_not_current_a():
    """Sigenergy AC: draw_current_a is the live draw, current_a is the SET limit.

    They read DIFFERENT server fields even when their values coincide, so
    changing one in the fixture must not move the other.
    """
    charger = {**SIGENERGY_AC_CHARGER_FULL, "draw_current_a": 12.5, "current_a": 16}
    draw = _make_sensor(charger, "draw_current_a")
    current = _make_sensor(charger, "current_a")
    assert draw.native_value == pytest.approx(12.5)
    assert current.native_value == pytest.approx(16.0)


def test_last_connection_sensor_metadata_and_value():
    from homeassistant.components.sensor import SensorDeviceClass
    from homeassistant.helpers.entity import EntityCategory

    sensor = _make_sensor(OCPP_CHARGER_FULL, "last_connection_at")
    assert sensor.device_class == SensorDeviceClass.TIMESTAMP
    assert sensor.entity_category == EntityCategory.DIAGNOSTIC
    val = sensor.native_value
    assert val is not None
    assert val.year == 2026


def test_session_started_sensor_value():
    from homeassistant.components.sensor import SensorDeviceClass

    sensor = _make_sensor(OCPP_CHARGER_FULL, "session_started_at")
    assert sensor.device_class == SensorDeviceClass.TIMESTAMP
    val = sensor.native_value
    assert val is not None
    assert val.year == 2026


def test_charging_speed_and_added_range_sensor_values():
    speed = _make_sensor(WALLBOX_CHARGER_FULL, "charging_speed_kmh")
    assert speed.native_value == pytest.approx(32.5)

    added_range = _make_sensor(WALLBOX_CHARGER_FULL, "added_range_km")
    assert added_range.native_value == pytest.approx(8.1)


def test_connection_type_sensor_value():
    sensor = _make_sensor(SIGENERGY_AC_CHARGER_FULL, "connection_type")
    assert sensor.native_value == "ethernet"


def test_vin_sensor_value():
    sensor = _make_sensor(TESLA_CHARGER_FULL, "vin")
    assert sensor.native_value == "5YJ3E1EA0KF000099"


def test_new_optional_sensors_return_none_when_field_absent():
    """A charger dict missing the new field entirely must not raise."""
    sensor = _make_sensor(NON_OCPP_CHARGER, "lifetime_energy_kwh")
    assert sensor.native_value is None
    sensor2 = _make_sensor(NON_OCPP_CHARGER, "vin")
    assert sensor2.native_value is None


# ---------------------------------------------------------------------------
# Lifetime energy stays available while the charger is offline/stale
# ---------------------------------------------------------------------------


def test_lifetime_energy_sensor_available_when_offline():
    offline = {**OCPP_CHARGER_FULL, "online": False, "stale": True}
    sensor = _make_sensor(offline, "lifetime_energy_kwh")
    assert sensor.available is True


def test_last_connection_sensor_available_when_offline():
    offline = {**OCPP_CHARGER_FULL, "online": False, "stale": True}
    sensor = _make_sensor(offline, "last_connection_at")
    assert sensor.available is True


def test_temperature_sensor_unavailable_when_offline():
    """Live telemetry sensors (temperature included) still gate on offline/stale."""
    offline = {**OCPP_CHARGER_FULL, "online": False, "stale": True}
    sensor = _make_sensor(offline, "temperature_c")
    assert sensor.available is False


# ---------------------------------------------------------------------------
# Diagnostics dict → extra_state_attributes on the status sensor
# ---------------------------------------------------------------------------


def test_status_sensor_exposes_diagnostics_attributes():
    sensor = _make_sensor(SIGENERGY_AC_CHARGER_FULL, "status")
    attrs = sensor.extra_state_attributes
    assert attrs == {"rated_power_kw": 7.4, "max_current_a": 32}


def test_status_sensor_has_no_attributes_when_diagnostics_empty():
    sensor = _make_sensor(OCPP_CHARGER_FULL, "status")
    assert sensor.extra_state_attributes is None


def test_non_status_sensor_never_exposes_diagnostics():
    sensor = _make_sensor(SIGENERGY_AC_CHARGER_FULL, "power_kw")
    assert sensor.extra_state_attributes is None


def test_status_sensor_diagnostics_absent_on_legacy_charger():
    """A charger dict with no `diagnostics` key at all (older server)."""
    sensor = _make_sensor(OCPP_CHARGER, "status")
    assert sensor.extra_state_attributes is None


# ---------------------------------------------------------------------------
# OCPP GetConfiguration diagnostics (Wi-Fi signal, SoC envelope, intervals)
# ---------------------------------------------------------------------------


def test_config_diagnostic_sensors_read_their_values():
    for key, expected in (
        ("wifi_signal_percent", 92),
        ("soc_max_percent", 97),
        ("soc_min_percent", 9),
        ("configured_current_limit_a", 48),
        ("heartbeat_interval_seconds", 60),
        ("meter_sample_interval_seconds", 60),
    ):
        sensor = _make_sensor(OCPP_CHARGER_WITH_CONFIG_DIAGNOSTICS, key)
        assert sensor.native_value == expected, key


def test_config_diagnostic_sensors_stay_available_when_offline():
    """Config is not live telemetry: it stays true while the borne is offline.

    Blanking these on staleness would be wrong — hence their absence from
    STALE_GATED_SENSOR_KEYS.
    """
    offline = {**OCPP_CHARGER_WITH_CONFIG_DIAGNOSTICS, "online": False, "stale": True}
    for key in ("wifi_signal_percent", "configured_current_limit_a", "heartbeat_interval_seconds"):
        assert _make_sensor(offline, key).available is True, key


def test_config_diagnostic_sensor_reports_unknown_when_server_omits_value():
    """Capability advertised but value absent → unknown, never a crash."""
    without = {**OCPP_CHARGER_WITH_CONFIG_DIAGNOSTICS, "wifi_signal_percent": None}
    assert _make_sensor(without, "wifi_signal_percent").native_value is None


def test_only_wifi_signal_is_enabled_by_default_among_config_diagnostics():
    """The rarely-moving settings are opt-in so an install isn't flooded."""
    by_key = {d.key: d for d in SENSOR_DESCRIPTIONS}
    assert by_key["wifi_signal_percent"].entity_registry_enabled_default is True
    for key in (
        "soc_max_percent", "soc_min_percent", "configured_current_limit_a",
        "heartbeat_interval_seconds", "meter_sample_interval_seconds",
    ):
        assert by_key[key].entity_registry_enabled_default is False, key


@pytest.mark.asyncio
async def test_wallbox_over_ocpp_gets_config_diagnostic_sensors():
    added = await _setup({15: OCPP_CHARGER_WITH_CONFIG_DIAGNOSTICS})
    keys = {e.entity_description.key for e in added}
    assert {
        "wifi_signal_percent", "soc_max_percent", "soc_min_percent",
        "configured_current_limit_a", "heartbeat_interval_seconds",
        "meter_sample_interval_seconds",
    } <= keys


@pytest.mark.asyncio
async def test_ocpp_charger_without_config_keys_gets_no_diagnostic_sensors():
    """An EVduty reports no Wi-Fi/SoC keys, so the server advertises no such
    capability and the entity is never created — rather than created and
    permanently unavailable.
    """
    added = await _setup({10: OCPP_CHARGER_FULL})
    keys = {e.entity_description.key for e in added}
    for key in (
        "wifi_signal_percent", "soc_max_percent", "soc_min_percent",
        "configured_current_limit_a", "heartbeat_interval_seconds",
        "meter_sample_interval_seconds",
    ):
        assert key not in keys, key


# ---------------------------------------------------------------------------
# Two-repo capability contract (KNOWN_CAPABILITIES mirrors the server's
# HomeAssistantController::capabilitiesFor() CAP_* constants)
# ---------------------------------------------------------------------------


def test_every_sensor_capability_is_a_known_capability():
    """Every non-legacy sensor's `capability` must be a member of
    KNOWN_CAPABILITIES — a rename on the PHP side that isn't mirrored here
    would otherwise silently stop that sensor from ever being created.
    """
    for description in SENSOR_DESCRIPTIONS:
        if description.capability is None:
            continue
        assert description.capability in KNOWN_CAPABILITIES, (
            f"{description.key}'s capability {description.capability!r} is not "
            "in KNOWN_CAPABILITIES — mirror it from "
            "HomeAssistantController::capabilitiesFor()"
        )


def test_every_sensor_translation_key_is_translated():
    """A description whose translation_key is missing from strings.json or a
    translations/ file renders as an unnamed entity in that language.
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "custom_components" / "roulezelectrique"
    used = {d.translation_key for d in SENSOR_DESCRIPTIONS if d.translation_key}

    for name in ("strings.json", "translations/fr.json", "translations/en.json"):
        declared = json.loads((root / name).read_text())["entity"]["sensor"]
        missing = used - set(declared)
        assert not missing, f"{name} is missing sensor names for: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Entity creation: capability-gated vs. legacy fallback
# ---------------------------------------------------------------------------


async def _setup(charger_map: dict[int, dict[str, Any]]) -> list:
    coordinator = MagicMock()
    coordinator.data = CoordinatorData(chargers=charger_map, account=None)
    coordinator.last_update_success = True
    coordinator._listeners = {}
    hass = MagicMock()
    entry_id = "entry_id"
    hass.data = {DOMAIN: {entry_id: coordinator, f"{entry_id}_client": MagicMock()}}
    entry = MagicMock()
    entry.entry_id = entry_id

    added: list = []
    await async_setup_entry(hass, entry, lambda entities, **kw: added.extend(entities))
    return added


@pytest.mark.asyncio
async def test_legacy_charger_without_capabilities_gets_exactly_the_original_six():
    """No `capabilities` key at all (older server) → LEGACY_SENSOR_KEYS only."""
    added = await _setup({1: OCPP_CHARGER})
    keys = {e.entity_description.key for e in added}
    assert keys == set(LEGACY_SENSOR_KEYS)


@pytest.mark.asyncio
async def test_full_ocpp_charger_gets_capability_gated_sensors():
    added = await _setup({10: OCPP_CHARGER_FULL})
    keys = {e.entity_description.key for e in added}
    # The legacy six are always present, plus OCPP_CHARGER_FULL's
    # capabilities: lifetime energy/sessions, last connection, session
    # start, temperature, soc.
    assert keys == {
        "power_kw", "energy_kwh", "status", "current_a", "voltage_v", "last_session",
        "lifetime_energy_kwh", "lifetime_sessions",
        "last_connection_at", "session_started_at",
        "temperature_c", "soc_percent",
    }
    # Never created for OCPP: draw_current_a, connection_type, vin,
    # charging_speed_kmh, added_range_km.
    assert "draw_current_a" not in keys
    assert "vin" not in keys


@pytest.mark.asyncio
async def test_wallbox_full_charger_gets_charging_speed_and_added_range_only():
    added = await _setup({11: WALLBOX_CHARGER_FULL})
    keys = {e.entity_description.key for e in added}
    # Legacy six always present (WALLBOX_CHARGER_FULL's capabilities list
    # doesn't even include "voltage", but voltage_v is legacy → still created).
    assert LEGACY_SENSOR_KEYS <= keys
    assert "charging_speed_kmh" in keys
    assert "added_range_km" in keys
    assert "last_connection_at" in keys
    assert "lifetime_energy_kwh" in keys
    # Wallbox never gets the new temperature/soc/vin/connection_type extras.
    assert "temperature_c" not in keys
    assert "vin" not in keys
    assert "connection_type" not in keys


@pytest.mark.asyncio
async def test_sigenergy_ac_full_charger_gets_temperature_draw_current_connection_type():
    added = await _setup({12: SIGENERGY_AC_CHARGER_FULL})
    keys = {e.entity_description.key for e in added}
    assert LEGACY_SENSOR_KEYS <= keys
    assert "temperature_c" in keys
    assert "draw_current_a" in keys
    assert "connection_type" in keys
    assert "session_started_at" in keys
    # No vin (Tesla-only extra).
    assert "vin" not in keys


@pytest.mark.asyncio
async def test_tesla_full_charger_gets_power_and_vin_only_extras():
    added = await _setup({13: TESLA_CHARGER_FULL})
    keys = {e.entity_description.key for e in added}
    # Legacy six always present, even though TESLA_CHARGER_FULL's
    # capabilities only list "power" and "vin" — this is the upgrade
    # scenario (see test_upgrade_scenario_charger_keeps_legacy_registry_ids
    # below for the blocker regression test).
    assert LEGACY_SENSOR_KEYS <= keys
    assert "vin" in keys
    assert "lifetime_energy_kwh" in keys
    # No temperature/soc/last_connection/session_start/draw_current/
    # connection_type/charging_speed/added_range for Tesla.
    assert "temperature_c" not in keys
    assert "last_connection_at" not in keys
    assert "session_started_at" not in keys


@pytest.mark.asyncio
async def test_baseline_vendor_new_server_gets_only_legacy_six_and_lifetime():
    """capabilities present but only the three baseline entries (e.g. FLO).

    The legacy six are always present regardless of `capabilities` content.
    energy_lifetime is one of the three baseline capabilities (every vendor
    has it), so the two lifetime sensors ARE also created; every other
    optional sensor (temperature, vin, …) requires a capability FLO never
    reports and is correctly excluded.
    """
    added = await _setup({14: BASELINE_CHARGER_FULL})
    keys = {e.entity_description.key for e in added}
    assert keys == set(LEGACY_SENSOR_KEYS) | {"lifetime_energy_kwh", "lifetime_sessions"}
    assert "temperature_c" not in keys
    assert "vin" not in keys
    assert "connection_type" not in keys


@pytest.mark.asyncio
async def test_upgrade_scenario_charger_keeps_legacy_registry_ids_even_with_capabilities():
    """BLOCKER regression test.

    A charger dict WITH a `capabilities` list (new server) — including a
    vendor whose capabilities list does NOT mention some of the legacy six
    (Tesla: no "current"/"voltage"/"energy_session"; a baseline vendor: no
    "power"/"energy_session"/"current"/"voltage" at all) — must STILL create
    all six legacy entities, so a pre-existing <=0.3.x registry entry (unique_id
    `{charger_id}_{key}`) is never orphaned into a permanently-unavailable
    ghost entity on upgrade.
    """
    added = await _setup(
        {
            13: TESLA_CHARGER_FULL,
            14: BASELINE_CHARGER_FULL,
        }
    )
    tesla_keys = {e.entity_description.key for e in added if e._charger_id == 13}
    baseline_keys = {e.entity_description.key for e in added if e._charger_id == 14}

    assert LEGACY_SENSOR_KEYS <= tesla_keys, (
        "Tesla charger with `capabilities` lost a legacy sensor on upgrade"
    )
    assert LEGACY_SENSOR_KEYS <= baseline_keys, (
        "Baseline-vendor charger with `capabilities` lost a legacy sensor on upgrade"
    )
    # unique_id must be stable across the upgrade too.
    tesla_unique_ids = {e.unique_id for e in added if e._charger_id == 13}
    for key in LEGACY_SENSOR_KEYS:
        assert f"13_{key}" in tesla_unique_ids
