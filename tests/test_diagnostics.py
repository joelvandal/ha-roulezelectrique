"""Tests for the Club Roulez Électrique diagnostics dump (redaction)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from custom_components.roulezelectrique.const import (
    CONF_API_TOKEN,
    CONF_BASE_URL,
    DEFAULT_BASE_URL,
    DOMAIN,
)
from custom_components.roulezelectrique.coordinator import CoordinatorData
from custom_components.roulezelectrique.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import ACCOUNT_DATA, OCPP_CHARGER, TESLA_CHARGER_FULL

REDACTED = "**REDACTED**"
TOKEN = "secrettoken0123456789"


def _make_entry():
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.title = "Club Roulez Électrique — roulezelectrique.club"
    entry.unique_id = f"user-{TOKEN[:8]}"
    entry.data = {CONF_BASE_URL: DEFAULT_BASE_URL, CONF_API_TOKEN: TOKEN}
    entry.options = {}
    return entry


def _make_hass(coordinator):
    hass = MagicMock()
    hass.data = {DOMAIN: {"test_entry": coordinator}} if coordinator else {}
    return hass


async def test_diagnostics_redacts_identifying_data():
    chargers = {1: dict(OCPP_CHARGER), 13: dict(TESLA_CHARGER_FULL)}
    coordinator = MagicMock()
    coordinator.data = CoordinatorData(
        chargers=chargers, account=dict(ACCOUNT_DATA), time_zones=[]
    )

    result = await async_get_config_entry_diagnostics(
        _make_hass(coordinator), _make_entry()
    )

    assert result["entry"]["data"][CONF_API_TOKEN] == REDACTED
    assert result["entry"]["unique_id"] == REDACTED
    assert result["entry"]["data"][CONF_BASE_URL] == DEFAULT_BASE_URL
    for cid in (1, 13):
        charger = result["coordinator_data"]["chargers"][cid]
        assert charger["serial_number"] == REDACTED
        assert charger["name"] == REDACTED
    # The VIN is only present (non-null) on the Tesla fixture.
    assert result["coordinator_data"]["chargers"][13]["vin"] == REDACTED
    # Non-sensitive fields survive.
    assert result["coordinator_data"]["chargers"][1]["status"] == "Available"
    assert result["coordinator_data"]["chargers"][1]["vendor"] == "ocpp"
    assert result["coordinator_data"]["account"]["rewards"]["currency"] == "CAD"

    dump = json.dumps(result)
    for secret in (
        TOKEN,
        TOKEN[:8],
        OCPP_CHARGER["serial_number"],
        OCPP_CHARGER["name"],
        TESLA_CHARGER_FULL["serial_number"],
        TESLA_CHARGER_FULL["vin"],
    ):
        assert secret not in dump


async def test_diagnostics_without_coordinator():
    result = await async_get_config_entry_diagnostics(_make_hass(None), _make_entry())

    assert result["coordinator_data"] is None
    assert result["entry"]["data"][CONF_API_TOKEN] == REDACTED


async def test_diagnostics_with_no_data():
    coordinator = MagicMock()
    coordinator.data = None

    result = await async_get_config_entry_diagnostics(
        _make_hass(coordinator), _make_entry()
    )

    assert result["coordinator_data"] is None


async def test_diagnostics_redacts_at_any_depth():
    """Nested dicts and lists of dicts are redacted too, not only depth 2."""
    charger = dict(OCPP_CHARGER)
    charger["diagnostics"] = {"serial_number": "NESTED-SERIAL", "charge_mode": 2}
    coordinator = MagicMock()
    coordinator.data = CoordinatorData(
        chargers={7: charger},
        account=dict(ACCOUNT_DATA),
        time_zones=[{"value": "America/Toronto", "label": "Toronto", "name": "Zed"}],
    )

    result = await async_get_config_entry_diagnostics(
        _make_hass(coordinator), _make_entry()
    )

    nested = result["coordinator_data"]["chargers"][7]["diagnostics"]
    assert nested["serial_number"] == REDACTED
    assert nested["charge_mode"] == 2
    zone = result["coordinator_data"]["time_zones"][0]
    assert zone["name"] == REDACTED
    assert zone["value"] == "America/Toronto"
    dumped = json.dumps(result)
    assert "NESTED-SERIAL" not in dumped
    assert "Zed" not in dumped
