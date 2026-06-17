"""Shared fixtures for Roulez Électrique integration tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixture data helpers
# ---------------------------------------------------------------------------

OCPP_CHARGER: dict[str, Any] = {
    "id": 1,
    "name": "Borne OCPP",
    "serial_number": "RE-ABC123",
    "vendor": "ocpp",
    "vendor_label": "Generic OCPP",
    "is_ocpp": True,
    "controllable": True,
    "online": True,
    "status": "Available",
    "charging": False,
    "power_kw": 0.0,
    "energy_kwh": 5.3,
    "current_a": 0.0,
    "voltage_v": 240.0,
    "transaction_id": None,
    "fresh": True,
    "stale": False,
    "last_session": {
        "occurred_at": "2026-06-01T12:00:00+00:00",
        "energy_kwh": 10.5,
        "duration_seconds": 3600,
    },
}

OCPP_CHARGER_CHARGING: dict[str, Any] = {
    **OCPP_CHARGER,
    "status": "Charging",
    "charging": True,
    "power_kw": 7.2,
    "energy_kwh": 2.1,
    "current_a": 30.0,
    "voltage_v": 240.0,
    "transaction_id": 42,
}

NON_OCPP_CHARGER: dict[str, Any] = {
    "id": 2,
    "name": "Tesla Wall Connector",
    "serial_number": "TW-XYZ789",
    "vendor": "tesla",
    "vendor_label": "Tesla",
    "is_ocpp": False,
    "controllable": False,
    "online": False,
    "status": None,
    "charging": False,
    "power_kw": None,
    "energy_kwh": None,
    "current_a": None,
    "voltage_v": None,
    "transaction_id": None,
    "fresh": False,
    "stale": True,
    "last_session": {
        "occurred_at": "2026-05-15T08:00:00+00:00",
        "energy_kwh": 20.0,
        "duration_seconds": 7200,
    },
}

STATE_ENVELOPE: dict[str, Any] = {
    "generated_at": "2026-06-17T10:00:00+00:00",
    "poll_interval_seconds": 30,
    "chargers": [OCPP_CHARGER],
}

STATE_ENVELOPE_MULTI: dict[str, Any] = {
    "generated_at": "2026-06-17T10:00:00+00:00",
    "poll_interval_seconds": 30,
    "chargers": [OCPP_CHARGER, NON_OCPP_CHARGER],
}

STATE_ENVELOPE_EMPTY: dict[str, Any] = {
    "generated_at": "2026-06-17T10:00:00+00:00",
    "poll_interval_seconds": 30,
    "chargers": [],
}

COMMAND_QUEUED: dict[str, Any] = {"id": 99, "status": "queued", "result": None, "error": None}
COMMAND_ACCEPTED: dict[str, Any] = {"id": 99, "status": "accepted", "result": None, "error": None}
COMMAND_REJECTED: dict[str, Any] = {"id": 99, "status": "rejected", "result": None, "error": "ChargePoint rejected"}
COMMAND_TIMEOUT: dict[str, Any] = {"id": 99, "status": "timeout", "result": None, "error": "No response"}
