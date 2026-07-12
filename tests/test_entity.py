"""Tests for the shared RoulezElectriqueEntity base (DeviceInfo)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from custom_components.roulezelectrique.coordinator import CoordinatorData
from custom_components.roulezelectrique.entity import RoulezElectriqueEntity

from .conftest import NON_OCPP_CHARGER, OCPP_CHARGER_FULL, SIGENERGY_AC_CHARGER_FULL


def _make_entity(charger_data: dict[str, Any]) -> RoulezElectriqueEntity:
    charger_id = charger_data["id"]
    coordinator = MagicMock()
    coordinator.data = CoordinatorData(chargers={charger_id: charger_data}, account=None)
    coordinator.last_update_success = True
    coordinator._listeners = {}
    return RoulezElectriqueEntity(coordinator, charger_id)


def test_device_info_uses_server_manufacturer_and_model_when_present():
    entity = _make_entity(OCPP_CHARGER_FULL)
    assert entity._attr_device_info["manufacturer"] == "EVDuty"
    assert entity._attr_device_info["model"] == "EVC48"


def test_device_info_falls_back_to_vendor_label_when_manufacturer_model_absent():
    """Non-OCPP legacy fixture has no manufacturer/model keys at all."""
    entity = _make_entity(NON_OCPP_CHARGER)
    assert entity._attr_device_info["manufacturer"] == NON_OCPP_CHARGER["vendor_label"]
    assert entity._attr_device_info["model"] == NON_OCPP_CHARGER["vendor_label"]


def test_device_info_falls_back_to_vendor_label_when_field_is_none():
    """Sigenergy AC reports model but not manufacturer — manufacturer falls back."""
    entity = _make_entity(SIGENERGY_AC_CHARGER_FULL)
    assert entity._attr_device_info["manufacturer"] == SIGENERGY_AC_CHARGER_FULL["vendor_label"]
    assert entity._attr_device_info["model"] == "SE-AC"


def test_device_info_serial_number_and_name():
    entity = _make_entity(OCPP_CHARGER_FULL)
    assert entity._attr_device_info["serial_number"] == OCPP_CHARGER_FULL["serial_number"]
    assert entity._attr_device_info["name"] == OCPP_CHARGER_FULL["name"]
